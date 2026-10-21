"""OCR adapters returning text and boxes in the supplied raster's coordinates."""

import csv
import io
import os
import subprocess
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from .models import FILES, REQUIRED, validate_model
from .runtime import (
    DEFAULT_BACKEND,
    prepare_backend,
    rapid_runtime_params,
    validate_backend,
    validate_session_providers,
)


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> dict:
        """Return text and regions in the supplied raster's coordinates."""
        ...


def box_region(text, polygon, confidence, level="word", line_id=None):
    return {
        "text": text,
        "polygon": np.asarray(polygon, dtype=float).tolist(),
        "confidence": float(confidence),
        "level": level,
        "line_id": line_id,
    }


class TesseractEngine:
    def __init__(self, directory: Path, *, threads=1):
        validate_model("tesseract", directory, verify=True)
        self.directory = directory.resolve()
        self.threads = threads

    def recognize(self, image: Image.Image) -> dict:
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        result = subprocess.run(
            [
                "tesseract",
                "stdin",
                "stdout",
                "--tessdata-dir",
                str(self.directory),
                "-l",
                "eng",
                "--oem",
                "1",
                "--psm",
                "3",
                "-c",
                "tessedit_create_tsv=1",
            ],
            input=encoded.getvalue(),
            capture_output=True,
            check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": str(self.threads)},
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                detail or f"Tesseract exited with code {result.returncode}."
            )
        regions, lines = [], {}
        for row in csv.DictReader(
            io.StringIO(result.stdout.decode("utf-8")),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        ):
            text = row["text"].strip()
            if row["level"] != "5" or not text:
                continue
            x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            line = ":".join(
                row[key] for key in ("page_num", "block_num", "par_num", "line_num")
            )
            regions.append(
                box_region(
                    text,
                    [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                    float(row["conf"]) / 100,
                    line_id=line,
                )
            )
            lines.setdefault(line, []).append(text)
        return {
            "text": "\n".join(" ".join(words) for words in lines.values()),
            "regions": regions,
            "preprocessing": {
                "detector_input": list(image.size),
                "resize": "none",
                "recognizer": "Tesseract LSTM, eng tessdata_best, OEM 1, PSM 3",
                "backend": "cpu",
                "threads_per_worker": self.threads,
            },
        }


class RapidEngine:
    def __init__(
        self, model: str, directory: Path, *, backend=DEFAULT_BACKEND, threads=1
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
        v5 = model == "ppocr-v5"
        v6_size = {
            "ppocr-v6": ModelType.MEDIUM,
            "ppocr-v6-medium": ModelType.MEDIUM,
            "ppocr-v6-small": ModelType.SMALL,
            "ppocr-v6-tiny": ModelType.TINY,
        }
        model_type = ModelType.SERVER if v5 else v6_size[model]
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
            "Det.ocr_version": OCRVersion.PPOCRV5 if v5 else OCRVersion.PPOCRV6,
            "Det.model_type": model_type,
            "Det.lang_type": LangDet.CH if v5 else LangDet.MULTI,
            "Rec.ocr_version": OCRVersion.PPOCRV5 if v5 else OCRVersion.PPOCRV6,
            "Rec.model_type": ModelType.MOBILE if v5 else model_type,
            "Rec.lang_type": LangRec.EN if v5 else LangRec.CH,
            "Cls.ocr_version": OCRVersion.PPOCRV5,
            **rapid_runtime_params(backend, threads, directory),
        }
        self.ocr = StrictRapidOCR(params=params)
        self.runtime = {
            "backend": backend,
            "threads_per_worker": threads,
            "providers": {
                name: component.session.session.get_providers()
                for name, component in [
                    ("detector", self.ocr.text_det),
                    ("recognizer", self.ocr.text_rec),
                ]
            },
        }
        validate_session_providers(backend, self.runtime["providers"])
        detector = self.ocr.text_det
        # The default detector adds an implicit 960/1500/2000 resize. Here only
        # network-required multiples of 32 are applied and recorded explicitly.
        detector.get_preprocess = lambda _: RasterPreprocess(
            mean=detector.mean, std=detector.std
        )
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
        return {
            "text": "\n".join(texts),
            "regions": regions,
            "preprocessing": {
                "detector_input": [tensor_w, tensor_h],
                "resize": "OpenCV INTER_LINEAR to nearest multiple of 32 (minimum 32)",
                "mean": prep.mean.tolist(),
                "std": prep.std.tolist(),
                "recognizer_inputs": list(self.recognizer_shapes),
                "orientation_classifier": False,
                **getattr(self, "runtime", {}),
            },
        }


def create_engine(model: str, directory: Path, *, backend=DEFAULT_BACKEND, threads=1):
    validate_backend(model, backend)
    if model == "tesseract":
        return TesseractEngine(directory, threads=threads)
    return RapidEngine(model, directory, backend=backend, threads=threads)
