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
    ):
        validate_backend(model, backend)
        validate_model(model, directory, verify=True)
        prepare_backend(backend)
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion

        det, rec, cls = [directory / FILES[key]["file"] for key in REQUIRED[model]]
        v6_size = {
            "ppocr-v6": ModelType.MEDIUM,
            "ppocr-v6-medium": ModelType.MEDIUM,
            "ppocr-v6-small": ModelType.SMALL,
            "ppocr-v6-tiny": ModelType.TINY,
        }
        model_type = v6_size[model]
        params = {
            "Global.return_word_box": True,
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
        self.ocr = RapidOCR(params=params)
        self.runtime = {
            "backend": backend,
            "threads_per_worker": threads,
            "providers": load_rapid_models(self.ocr),
        }
        validate_session_providers(backend, self.runtime["providers"])
        detector = self.ocr.text_det
        self.detector_shapes = []
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
        from importlib.metadata import version
        from omegaconf import OmegaConf

        native_configuration = json.loads(
            json.dumps(
                OmegaConf.to_container(self.ocr.cfg, resolve=True, enum_to_str=True),
                default=str,
            )
        )
        return {
            "text": "\n".join(texts),
            "regions": regions,
            "preprocessing": {
                "detector_input": None,
                "resize": "RapidOCR native preprocessing",
                "mean": prep.mean.tolist(),
                "std": prep.std.tolist(),
                "recognizer_inputs": list(self.recognizer_shapes),
                "orientation_classifier": bool(self.ocr.cfg.Global.use_cls),
                "pipeline": "RapidOCR native",
                "native_configuration": native_configuration,
                "detector_tensors": list(self.detector_shapes),
                "package_versions": {
                    name: version(name) for name in ("rapidocr", "onnxruntime")
                },
                **getattr(self, "runtime", {}),
            },
        }


def create_engine(
    model: str,
    directory: Path,
    *,
    backend=DEFAULT_BACKEND,
    threads=1,
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
    )
