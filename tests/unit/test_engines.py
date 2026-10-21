import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from vipi.ocr.engines import RapidEngine, TesseractEngine


def test_tesseract_preserves_quotes_low_scores_and_lines(tmp_path, monkeypatch):
    monkeypatch.setattr("vipi.ocr.engines.validate_model", lambda *args, **kwargs: None)
    data = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        '5\t1\t1\t1\t1\t1\t10\t10\t20\t10\t0\t"hello\n'
        '5\t1\t1\t1\t1\t2\t40\t10\t20\t10\t20\tworld"\n'
        "5\t1\t1\t1\t2\t1\t10\t30\t20\t10\t90\tsecond\n"
    ).encode()

    def run(command, **kwargs):
        assert "tessedit_create_tsv=1" in command
        assert kwargs["input"].startswith(b"\x89PNG")
        assert kwargs["env"]["OMP_THREAD_LIMIT"] == "2"
        return subprocess.CompletedProcess(command, 0, data, b"")

    monkeypatch.setattr("vipi.ocr.engines.subprocess.run", run)
    output = TesseractEngine(tmp_path, threads=2).recognize(Image.new("RGB", (100, 50)))
    assert output["text"] == '"hello world"\nsecond'
    assert len(output["regions"]) == 3
    assert output["regions"][0]["confidence"] == 0
    assert output["regions"][0]["polygon"][2] == [30, 20]


def test_native_failure_is_an_error_even_without_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr("vipi.ocr.engines.validate_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "vipi.ocr.engines.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, -6, b"", b""),
    )
    with pytest.raises(RuntimeError, match="code -6"):
        TesseractEngine(tmp_path).recognize(Image.new("RGB", (1, 1)))


def test_partial_word_boxes_do_not_drop_recognized_line_text():
    box = [[0, 0], [90, 0], [90, 20], [0, 20]]

    class OCR:
        text_det = SimpleNamespace(
            preprocess_op=SimpleNamespace(
                mean=np.array([0.5] * 3), std=np.array([0.5] * 3)
            )
        )

        def __call__(self, image):
            return SimpleNamespace(
                txts=("keep all text",),
                boxes=[box],
                scores=(0.1,),
                word_results=((("keep", 0.1, box),),),
            )

    engine = RapidEngine.__new__(RapidEngine)
    engine.ocr = OCR()
    engine.recognizer_shapes = []
    result = engine.recognize(Image.new("RGB", (100, 30)))
    assert result["regions"][0]["text"] == "keep all text"
    assert result["regions"][0]["level"] == "line"
