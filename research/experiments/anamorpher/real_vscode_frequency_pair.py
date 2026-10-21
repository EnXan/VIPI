"""Apply the original gray checkerboard switch to a real VS Code editor pane.

The VS Code chrome surrounds a frequency-paired editor rectangle. It can be
mapped to matching neutral grays while retaining UI edges and labels.
Native display requires 1:1 pixels; HIGH_DETAIL uses direct 2:1 Triangle.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

from research.experiments.anamorpher.codex_preprocessing_probe import limited_size
from research.experiments.anamorpher.frequency_pair import encode
from research.experiments.anamorpher.triangle import Triangle, construct, rgb8
from research.experiments.anamorpher.triangle_probe import native_chain


SOURCE_SIZE = (3840, 2560)
EDITOR_RECT = (1368, 292, 3360, 1934)  # Even pixel boundaries around the code.


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normal", type=Path)
    parser.add_argument("alternate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contrast", type=int, default=8)
    parser.add_argument("--amplitude", type=int, default=110)
    parser.add_argument("--background", type=int, default=128)
    parser.add_argument("--normalize-editor", action="store_true",
                        help="Stretch the gray editor background to white before encoding.")
    parser.add_argument("--gray-chrome", type=float,
                        help="Map bright VS Code surfaces near gray 128 at this luminance slope.")
    parser.add_argument("--gray-chrome-ink", type=float,
                        help="Optional stronger slope for dark UI labels and lines.")
    parser.add_argument("--chrome-chroma", type=float, default=0,
                        help="Restore and strengthen the real UI's restrained color accents (0 to 2).")
    parser.add_argument("--native-syntax-color", type=float, default=0,
                        help="Restore source syntax colors in the native texture (0 to 1).")
    parser.add_argument("--syntax-chroma-gain", type=float, default=1,
                        help="Boost source syntax chroma before projection (1 to 5).")
    parser.add_argument("--shared-syntax-color", type=float, default=0,
                        help="Restore color on code glyphs identical in both references (0 to 1).")
    parser.add_argument("--alternate-syntax-color", type=float, default=0,
                        help="Color alternate-only glyphs in the HIGH_DETAIL target (0 to 1).")
    args = parser.parse_args()
    if args.gray_chrome_ink is not None and args.gray_chrome is None:
        parser.error("--gray-chrome-ink requires --gray-chrome.")
    if not 0 <= args.native_syntax_color <= 1:
        parser.error("--native-syntax-color must lie between 0 and 1.")
    if not 1 <= args.syntax_chroma_gain <= 5:
        parser.error("--syntax-chroma-gain must lie between 1 and 5.")
    if not 0 <= args.shared_syntax_color <= 1:
        parser.error("--shared-syntax-color must lie between 0 and 1.")
    if not 0 <= args.alternate_syntax_color <= 1:
        parser.error("--alternate-syntax-color must lie between 0 and 1.")
    if not 0 <= args.chrome_chroma <= 2:
        parser.error("--chrome-chroma must lie between 0 and 2.")
    if args.chrome_chroma and args.gray_chrome is None:
        parser.error("--chrome-chroma requires --gray-chrome.")

    normal = Image.open(args.normal).convert("RGB")
    alternate = Image.open(args.alternate).convert("RGB")
    if normal.size != SOURCE_SIZE or alternate.size != SOURCE_SIZE:
        parser.error("Both VS Code references must measure 3840 × 2560 pixels.")
    target_size = limited_size(SOURCE_SIZE, 2048, 2500)
    if target_size != (1920, 1280):
        raise AssertionError("The declared HIGH_DETAIL geometry changed.")
    x0, y0, x1, y1 = EDITOR_RECT
    normal_gray = np.asarray(normal.crop(EDITOR_RECT).convert("L"))
    alternate_gray = np.asarray(alternate.crop(EDITOR_RECT).convert("L"))
    if args.normalize_editor:
        def stretch(gray):
            return np.clip((gray.astype(np.float32) - 45) * (255 / 148), 0, 255).astype(np.uint8)

        normal_gray = stretch(normal_gray)
        alternate_gray = stretch(alternate_gray)
    paired, desired, history = encode(
        normal_gray, alternate_gray,
        contrast=args.contrast,
        amplitude=args.amplitude,
        background=args.background,
    )
    syntax_history = None
    if args.native_syntax_color:
        color = np.asarray(normal.crop(EDITOR_RECT), dtype=np.float32)
        luminance = np.asarray(normal.crop(EDITOR_RECT).convert("L"), dtype=np.float32)
        color = np.clip(
            luminance[..., None] + args.syntax_chroma_gain * (color - luminance[..., None]),
            0, 255,
        )
        ink = np.clip((193 - luminance) / 150, 0, 1)
        strength = args.native_syntax_color * ink[..., None]
        gray_carrier = paired[..., None].astype(np.float32)
        colored_carrier = rgb8((1 - strength) * gray_carrier + strength * color)
        operator = Triangle((x1 - x0, y1 - y0), ((x1 - x0) // 2, (y1 - y0) // 2))
        paired_rgb, syntax_history = construct(
            colored_carrier,
            np.repeat(desired[..., None], 3, axis=2),
            operator,
            preservation=0,
            iterations=30,
        )
    else:
        paired_rgb = np.repeat(paired[..., None], 3, axis=2)
    if args.shared_syntax_color:
        source_rgb = np.asarray(normal.crop(EDITOR_RECT), dtype=np.float32)
        other_rgb = np.asarray(alternate.crop(EDITOR_RECT), dtype=np.float32)
        source_l = np.asarray(normal.crop(EDITOR_RECT).convert("L"), dtype=np.float32)
        other_l = np.asarray(alternate.crop(EDITOR_RECT).convert("L"), dtype=np.float32)
        common_ink = np.clip((193 - np.maximum(source_l, other_l)) / 115, 0, 1)
        agreement = np.clip(
            1 - np.max(np.abs(source_rgb - other_rgb), axis=2) / 25,
            0, 1,
        )
        shared_strength = (args.shared_syntax_color * common_ink * agreement)[..., None]
        paired_rgb = rgb8(
            (1 - shared_strength) * paired_rgb.astype(np.float32)
            + shared_strength * source_rgb
        )
    alternate_color_history = None
    colored_target = None
    if args.alternate_syntax_color:
        operator = Triangle((x1 - x0, y1 - y0), ((x1 - x0) // 2, (y1 - y0) // 2))
        source_rgb = np.asarray(normal.crop(EDITOR_RECT), dtype=np.float32)
        other_rgb = np.asarray(alternate.crop(EDITOR_RECT), dtype=np.float32)
        other_l = np.asarray(alternate.crop(EDITOR_RECT).convert("L"), dtype=np.float32)
        difference = np.max(np.abs(source_rgb - other_rgb), axis=2)
        unique_ink = np.clip((193 - other_l) / 130, 0, 1) * np.clip(difference / 25, 0, 1)
        chroma = other_rgb - other_l[..., None]
        colored_target = np.clip(
            operator.forward(paired_rgb)
            + args.alternate_syntax_color * operator.forward(unique_ink[..., None] * chroma),
            0, 255,
        )
        paired_rgb, alternate_color_history = construct(
            paired_rgb, colored_target, operator, preservation=0, iterations=30
        )
    if args.gray_chrome is None:
        combined = np.asarray(normal).copy()
    else:
        if not 0 < args.gray_chrome <= 1:
            parser.error("--gray-chrome must lie between 0 and 1.")
        ink_slope = args.gray_chrome if args.gray_chrome_ink is None else args.gray_chrome_ink
        if not 0 < ink_slope <= 1:
            parser.error("--gray-chrome-ink must lie between 0 and 1.")
        original_rgb = np.asarray(normal, dtype=np.float32)
        chrome = np.asarray(normal.convert("L"), dtype=np.float32)
        original_luminance = chrome.copy()
        dark_base = 128 + args.gray_chrome * (170 - 193)
        chrome = np.where(
            chrome >= 170,
            128 + args.gray_chrome * (chrome - 193),
            dark_base + ink_slope * (chrome - 170),
        )
        chrome = np.clip(
            chrome[..., None]
            + args.chrome_chroma * (original_rgb - original_luminance[..., None]),
            0, 255,
        ).astype(np.uint8)
        combined = chrome
    combined[y0:y1, x0:x1] = paired_rgb
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    Image.fromarray(combined).save(output / "combined.png")
    Image.fromarray(desired).convert("RGB").save(output / "editor-target.png")

    binary = output / "triangle-reference"
    subprocess.run(
        ["clang++", "-std=c++17", "-O2", "-ffp-contract=off",
         str(Path(__file__).with_name("triangle_reference.cpp")), "-o", str(binary)],
        check=True,
    )
    actual = native_chain(binary, combined, [SOURCE_SIZE, target_size], output)
    Image.fromarray(actual).save(output / "high-detail.png")
    predicted = Triangle(SOURCE_SIZE, target_size).resize(combined)
    if not np.array_equal(actual, predicted):
        raise AssertionError("The C++ and sparse Python Triangle paths disagree.")

    # Exclude the first and last two scaled pixels, which mix with the chrome.
    hx0, hy0, hx1, hy1 = (x0 // 2, y0 // 2, x1 // 2, y1 // 2)
    interior = actual[hy0 + 2:hy1 - 2, hx0 + 2:hx1 - 2, 0].astype(float)
    intended = desired[2:-2, 2:-2]
    error = interior - intended
    rgb_error = actual[hy0 + 2:hy1 - 2, hx0 + 2:hx1 - 2].astype(float) - intended[..., None]
    colored_error = None
    if colored_target is not None:
        colored_error = actual[hy0 + 2:hy1 - 2, hx0 + 2:hx1 - 2].astype(float) - colored_target[2:-2, 2:-2]
        Image.fromarray(rgb8(colored_target)).save(output / "editor-color-target.png")
    # These crops show the same code lines at their respective native sizes.
    native_box = (x0 + 18, y0 + 485, x0 + 1730, y0 + 1135)
    Image.fromarray(combined).crop(native_box).save(output / "native-code.png")
    Image.fromarray(actual).crop(tuple(v // 2 for v in native_box)).save(
        output / "high-code.png"
    )
    report = {
        "method": "original frequency_pair.encode checkerboard construction within the actual VS Code editor; shared syntax colors can be restored in both views and real UI accents strengthened against a gray chrome",
        "source_size": SOURCE_SIZE,
        "high_detail_size": target_size,
        "editor_rect": EDITOR_RECT,
        "contrast": args.contrast,
        "checker_amplitude": args.amplitude,
        "mean_background": args.background,
        "editor_gray_normalized": args.normalize_editor,
        "gray_chrome_luminance_slope": args.gray_chrome,
        "gray_chrome_ink_slope": args.gray_chrome_ink,
        "chrome_chroma": args.chrome_chroma,
        "gray_chrome_midpoint": 193 if args.gray_chrome is not None else None,
        "gray_chrome_target": 128 if args.gray_chrome is not None else None,
        "history": history,
        "syntax_color_history": syntax_history,
        "native_syntax_color": args.native_syntax_color,
        "syntax_chroma_gain": args.syntax_chroma_gain,
        "shared_syntax_color": args.shared_syntax_color,
        "alternate_syntax_color": args.alternate_syntax_color,
        "alternate_color_history": alternate_color_history,
        "editor_target_max_error": int(np.abs(error).max()),
        "editor_target_rmse": float(np.sqrt(np.mean(error**2))),
        "editor_target_rgb_max_error": int(np.abs(rgb_error).max()),
        "editor_target_rgb_rmse": float(np.sqrt(np.mean(rgb_error**2))),
        "editor_target_error_scope": "difference from gray alternate target; shared syntax colors intentionally contribute when enabled",
        "editor_color_target_rgb_max_error": None if colored_error is None else int(np.abs(colored_error).max()),
        "editor_color_target_rgb_rmse": None if colored_error is None else float(np.sqrt(np.mean(colored_error**2))),
        "cpp_sparse_pixel_identical": True,
        "inputs": {name: {"path": str(path.resolve()), "sha256": sha256(path)}
                   for name, path in (("normal", args.normal), ("alternate", args.alternate))},
        "combined_sha256": sha256(output / "combined.png"),
        "high_detail_sha256": sha256(output / "high-detail.png"),
        "conditions": [
            "Native view requires one source pixel per physical display pixel.",
            "HIGH_DETAIL is a direct 3840×2560 to 1920×1280 Triangle resize.",
            "Browser fit-to-window changes the native appearance.",
            "The checkerboard editor cannot preserve the source's exact colors; varying values retain reduced saturation to protect the switch.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(output), "rmse": report["editor_target_rmse"],
                      "max_error": report["editor_target_max_error"]}), flush=True)


if __name__ == "__main__":
    main()
