"""OCR adapters returning text and boxes in the supplied raster's coordinates."""

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from vipi.config import MISTRAL_OCR_MODEL, GOOGLE_OCR_MODEL, LUNA_OCR_MODEL

from .models import FILES, REQUIRED, validate_model
from .types import OcrEngine, box_region
from .runtime import (
    DEFAULT_BACKEND,
    prepare_backend,
    rapid_runtime_params,
    validate_backend,
    validate_session_providers,
)


def load_rapid_models(ocr) -> dict[str, list[str]]:
    """Load RapidOCR's detector and recognizer and return their ONNX providers.

    RapidOCR 3.10 creates ``text_det`` and ``text_rec`` lazily on first use.
    Loading them here keeps the provider check and the pipeline patches in
    ``RapidEngine`` ahead of the first scan.
    """
    return {
        name: component.session.session.get_providers()
        for name, component in [
            ("detector", ocr._load_det_model()),
            ("recognizer", ocr._load_rec_model()),
        ]
    }


class RapidEngine:
    def __init__(
        self,
        model: str,
        directory: Path,
        *,
        backend=DEFAULT_BACKEND,
        threads=1,
        native_pipeline=False,
    ):
        validate_backend(model, backend)
        validate_model(model, directory, verify=True)
        prepare_backend(backend)
        from rapidocr import RapidOCR
        from rapidocr.ch_ppocr_det.utils import DetPreProcess
        from rapidocr.ch_ppocr_rec import TextRecOutput
        from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion

        class StrictRapidOCR(RapidOCR):
            def run_ocr_steps(self, image, op_record):
                # Empty detection is valid. Inference/cropping/recognition failures propagate.
                op_record["padding_1"] = {"top": 0, "left": 0}
                detection = self.text_det(image)
                if detection.boxes is None:
                    return detection, None, TextRecOutput(), []
                crops = self.crop_text_regions(image, detection.boxes)
                recognition = self.recognize_txt(crops)
                return detection, None, recognition, crops

            def build_final_output(
                self, image, detection, classification, recognition, crops, operations
            ):
                from rapidocr.ch_ppocr_cls import TextClsOutput

                return super().build_final_output(
                    image, detection, TextClsOutput(), recognition, crops, operations
                )

        class RasterPreprocess(DetPreProcess):
            def resize(self, image):
                h, w = image.shape[:2]
                size = (max(32, round(w / 32) * 32), max(32, round(h / 32) * 32))
                return cv2.resize(image, size, interpolation=cv2.INTER_LINEAR)

        det, rec, cls = [directory / FILES[key]["file"] for key in REQUIRED[model]]
        v6_size = {
            "ppocr-v6": ModelType.MEDIUM,
            "ppocr-v6-medium": ModelType.MEDIUM,
            "ppocr-v6-small": ModelType.SMALL,
            "ppocr-v6-tiny": ModelType.TINY,
        }
        model_type = v6_size[model]
        params = {
            "Global.use_cls": False,
            "Global.use_preprocess_img": False,
            "Global.use_vertical_padding": False,
            "Global.return_word_box": True,
            "Global.text_score": 0.0,
            "Global.log_level": "error",
            "Det.model_path": str(det.resolve()),
            "Rec.model_path": str(rec.resolve()),
            "Cls.model_path": str(cls.resolve()),
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": model_type,
            "Det.lang_type": LangDet.MULTI,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.model_type": model_type,
            "Rec.lang_type": LangRec.CH,
            "Cls.ocr_version": OCRVersion.PPOCRV5,
            **rapid_runtime_params(backend, threads, directory),
        }
        self.native_pipeline = native_pipeline
        if native_pipeline:
            for key in (
                "Global.use_cls",
                "Global.use_preprocess_img",
                "Global.use_vertical_padding",
                "Global.text_score",
            ):
                params.pop(key)
        self.ocr = (RapidOCR if native_pipeline else StrictRapidOCR)(params=params)
        self.runtime = {
            "backend": backend,
            "threads_per_worker": threads,
            "providers": load_rapid_models(self.ocr),
        }
        validate_session_providers(backend, self.runtime["providers"])
        detector = self.ocr.text_det
        # The default detector adds an implicit 960/1500/2000 resize. Here only
        # network-required multiples of 32 are applied and recorded explicitly.
        if not native_pipeline:
            detector.get_preprocess = lambda _: RasterPreprocess(
                mean=detector.mean, std=detector.std
            )
        self.detector_shapes = []
        if native_pipeline:
            shapes, session = self.detector_shapes, detector.session

            class RecordedSession:
                def __getattr__(self, name):
                    return getattr(session, name)

                def __call__(self, tensor):
                    shapes.append(list(tensor.shape))
                    return session(tensor)

            detector.session = RecordedSession()
        self.recognizer_shapes = []
        original_resize = self.ocr.text_rec.resize_norm_img

        def recorded_resize(image, ratio):
            result = original_resize(image, ratio)
            self.recognizer_shapes.append(
                {"crop": [image.shape[1], image.shape[0]], "tensor": list(result.shape)}
            )
            return result

        self.ocr.text_rec.resize_norm_img = recorded_resize

    def recognize(self, image: Image.Image) -> dict:
        self.recognizer_shapes.clear()
        if hasattr(self, "detector_shapes"):
            self.detector_shapes.clear()
        result = self.ocr(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
        regions = []
        texts = getattr(result, "txts", None) or ()
        boxes = getattr(result, "boxes", None)
        scores = getattr(result, "scores", None) or ()
        word_lines = getattr(result, "word_results", None) or ()
        if texts and (boxes is None or len(boxes) != len(texts)):
            raise RuntimeError("OCR returned text without matching positions.")
        for i, text in enumerate(texts):
            words = word_lines[i] if i < len(word_lines) else ()
            # Some native outputs omit word boxes for a line. Only use them
            # when they cover this exact reading; otherwise retain its line box.
            word_text = "".join("".join(word.split()) for word, _, _ in words)
            if words and word_text == "".join(text.split()):
                regions.extend(
                    box_region(word, polygon, score, line_id=str(i))
                    for word, score, polygon in words
                    if word.strip()
                )
            else:
                regions.append(box_region(text, boxes[i], scores[i], "line", str(i)))
        prep = self.ocr.text_det.preprocess_op
        tensor_w = max(32, round(image.width / 32) * 32)
        tensor_h = max(32, round(image.height / 32) * 32)
        native = getattr(self, "native_pipeline", False)
        native_metadata = {}
        if native:
            from importlib.metadata import version
            from omegaconf import OmegaConf

            native_metadata["native_configuration"] = json.loads(
                json.dumps(
                    OmegaConf.to_container(
                        self.ocr.cfg, resolve=True, enum_to_str=True
                    ),
                    default=str,
                )
            )
            native_metadata["detector_tensors"] = list(self.detector_shapes)
            native_metadata["package_versions"] = {
                name: version(name) for name in ("rapidocr", "onnxruntime")
            }
        return {
            "text": "\n".join(texts),
            "regions": regions,
            "preprocessing": {
                "detector_input": None if native else [tensor_w, tensor_h],
                "resize": "RapidOCR native preprocessing"
                if native
                else "OpenCV INTER_LINEAR to nearest multiple of 32 (minimum 32)",
                "mean": prep.mean.tolist(),
                "std": prep.std.tolist(),
                "recognizer_inputs": list(self.recognizer_shapes),
                "orientation_classifier": bool(self.ocr.cfg.Global.use_cls)
                if native
                else False,
                "pipeline": "RapidOCR native" if native else "VIPI RapidOCR adapter",
                **native_metadata,
                **getattr(self, "runtime", {}),
            },
        }


def create_engine(
    model: str,
    directory: Path,
    *,
    backend=DEFAULT_BACKEND,
    threads=1,
    native_pipeline=False,
) -> OcrEngine:
    """Create a local or hosted OCR adapter without changing its native contract."""
    validate_backend(model, backend)
    if model == GOOGLE_OCR_MODEL:
        from .cloud import GoogleVisionEngine

        return GoogleVisionEngine()
    if model == LUNA_OCR_MODEL:
        from .cloud import LunaEngine

        return LunaEngine()
    if model == MISTRAL_OCR_MODEL:
        from .cloud import MistralEngine

        return MistralEngine()
    return RapidEngine(
        model,
        directory,
        backend=backend,
        threads=threads,
        native_pipeline=native_pipeline,
    )
