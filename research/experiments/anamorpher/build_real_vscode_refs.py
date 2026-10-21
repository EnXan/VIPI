"""Prepare aligned two-view references from a real VS Code window capture."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


CAPTURE_SIZE = (2400, 1600)
SOURCE_SIZE = (3840, 2560)
CODE_RECT = (855, 183, 2100, 1208)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normal", type=Path)
    parser.add_argument("alternate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    normal = np.asarray(Image.open(args.normal).convert("RGB"))
    alternate = np.asarray(Image.open(args.alternate).convert("RGB"))
    if normal.shape != alternate.shape or normal.shape[:2] != CAPTURE_SIZE[::-1]:
        parser.error("Both VS Code captures must be aligned at 2400 × 1600.")
    x0, y0, x1, y1 = CODE_RECT
    background = np.median(normal[1300:1450, 1300:2000], axis=(0, 1)).astype(np.uint8)
    normal_frame = normal.copy()
    alternate_frame = normal.copy()
    alternate_frame[y0:y1, x0:x1] = alternate[y0:y1, x0:x1]
    blank_frame = normal.copy()
    blank_frame[y0:y1, x0:x1] = background
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, pixels in (
        ("normal", normal_frame),
        ("alternate", alternate_frame),
        ("blank", blank_frame),
    ):
        image = Image.fromarray(pixels).resize(SOURCE_SIZE, Image.Resampling.LANCZOS)
        image.save(output / f"{name}.png")
    (output / "provenance.json").write_text(json.dumps({
        "normal_capture": str(args.normal.resolve()),
        "alternate_capture": str(args.alternate.resolve()),
        "capture_size": CAPTURE_SIZE,
        "source_size": SOURCE_SIZE,
        "code_rect_in_capture": CODE_RECT,
        "editor_background_rgb": background.tolist(),
        "interface_source": "Real Visual Studio Code window, guided by the official VS Code UI screenshot",
        "official_reference_url": "https://code.visualstudio.com/assets/docs/editing/userinterface/hero.png",
    }, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
