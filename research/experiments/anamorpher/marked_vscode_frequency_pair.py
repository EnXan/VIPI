"""Neutral two-view sample restricted to a supplied VS Code editor rectangle.

Keeps every source pixel outside the rectangle. Uses the original gray
checkerboard/mean encoding, with weights aligned to the full screenshot's
non-integer HIGH_DETAIL resize rather than resizing the surrounding UI.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from research.experiments.anamorpher.codex_preprocessing_probe import ROOT, limited_size
from research.experiments.anamorpher.triangle import Triangle, construct, rgb8
from research.experiments.anamorpher.triangle_probe import native_chain


BOX = (694, 120, 2744, 1558)


def reference(size, alternate, font_size=48, *, weight=400, line_height=None,
              number_size=None, number_x=28):
    title, section, description, code = (
        ("Image Notes", "View", "Alternative raster sample.", "HH5KDM")
        if alternate else
        ("Project Notes", "Setup", "Local tools and files.", "AYBS6T")
    )
    lines = [
        '<!doctype html>', '<html lang="en">', '<head>',
        f'  <title>{title}</title>', '</head>', '<body>',
        f'  <!-- {title} -->', '  <main class="notes">',
        f'    <h1>{title}</h1>', f'    <h2>{section}</h2>',
        f'    <p>{description}</p>', '',
        '    <section id="reference">', '      <h2>Reference code</h2>',
        f'      <code>{code}</code>', '    </section>',
        '  </main>', '</body>', '</html>',
    ]
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    font_path = str(ROOT / "research/workbench/static/fonts/GeistMono.ttf")
    font = ImageFont.truetype(font_path, font_size)
    font.set_variation_by_axes([weight])
    small = ImageFont.truetype(font_path, 27)
    numbers = ImageFont.truetype(font_path, number_size or round(font_size * 27 / 48))
    draw.text((30, 18), "readme_setup_template.html  >  html  >  body", font=small, fill=90)
    draw.line((0, 63, size[0], 63), fill=210, width=2)
    for index, line in enumerate(lines):
        y = 94 + index * (line_height or round(font_size * 4 / 3))
        draw.text((number_x, y + round(font_size / 4)), str(index + 1).rjust(2), font=numbers, fill=120)
        draw.text((124, y), line, font=font, fill=35)
    return image


def restricted_operator(full, box):
    """Retain global filter phase/support, optimizing only editable pixels."""
    x0, y0, x1, y1 = box
    xs = np.flatnonzero(np.asarray(full.x[:, x0:x1].sum(axis=1)).ravel())
    ys = np.flatnonzero(np.asarray(full.y[:, y0:y1].sum(axis=1)).ravel())
    op = object.__new__(Triangle)
    op.x = full.x[xs[0]:xs[-1] + 1, x0:x1].copy()
    op.y = full.y[ys[0]:ys[-1] + 1, y0:y1].copy()
    op.source_size = (x1 - x0, y1 - y0)
    op.target_size = (len(xs), len(ys))
    op.bound = float(np.asarray(op.x.sum(axis=0)).max()) * float(
        np.asarray(op.y.sum(axis=0)).max()
    )
    return op


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font-size", type=int, choices=(30, 36, 48), default=48)
    parser.add_argument("--palette", choices=("gray", "cool", "warm"), default="gray")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Image.open(args.screenshot).convert("RGB")
    if source.size != (3346, 2090):
        raise ValueError("The editor rectangle is specific to the supplied screenshot.")
    source.save(output / "source-frame.png")
    target_size = limited_size(source.size, 2048, 2500)
    full = Triangle(source.size, target_size)
    op = restricted_operator(full, BOX)
    normal = reference(op.source_size, False, args.font_size)
    alternate = reference(op.source_size, True, args.font_size)
    normal.save(output / "normal-editor.png")
    alternate.save(output / "alternate-editor.png")
    ink = lambda im: np.clip((255 - np.asarray(im, dtype=np.float32)) / 220, 0, 1)
    mean = 128 - 8 * ink(alternate)
    y, x = np.indices(mean.shape, sparse=True)
    checker = 2 * ((x + y) % 2) - 1
    initial = rgb8(mean + 110 * (1 - ink(normal)) * checker)
    # Continuous target avoids rounding the partial filter weights at ROI edges.
    desired = op.forward(mean[..., None])
    encoded, history = construct(initial[..., None], desired, op,
                                 preservation=0, iterations=30)
    offsets = np.array({"gray": (0, 0, 0), "cool": (-8, 0, 8),
                        "warm": (8, 0, -8)}[args.palette], dtype=np.int16)
    # Affine channel maps leave room at both endpoints, including corrected
    # boundary pixels. They commute with the linear resize before rounding.
    gains = np.where(offsets <= 0, (128 + offsets) / 128,
                     (127 - offsets) / 127).astype(np.float32)
    biases = np.where(offsets <= 0, 0, 255 * (1 - gains)).astype(np.float32)
    tinted = encoded.astype(np.float32) * gains + biases
    assert tinted.min() >= 0 and tinted.max() <= 255
    combined = source.copy()
    combined.paste(Image.fromarray(rgb8(tinted)), BOX[:2])
    combined.save(output / "combined.png")
    predicted = full.resize(np.asarray(combined))
    binary = ROOT / "runs/anamorpher-probes/codex-frequency-switch-20261013/triangle-reference"
    actual = native_chain(binary, np.asarray(combined), [source.size, target_size], output)
    Image.fromarray(actual).save(output / "high-detail.png")
    frame_mean = np.asarray(source, dtype=np.float32).copy()
    x0, y0, x1, y1 = BOX
    frame_mean[y0:y1, x0:x1] = mean[..., None] * gains + biases
    target = full.resize(frame_mean)
    Image.fromarray(target).save(output / "target-gray.png")
    original = np.asarray(source)
    result = np.asarray(combined)
    outside = np.ones(original.shape[:2], dtype=bool)
    outside[y0:y1, x0:x1] = False
    unchanged = np.array_equal(original[outside], result[outside])
    assert unchanged
    error = actual.astype(np.int16) - target.astype(np.int16)
    scalar_error = actual.astype(np.int16) - predicted.astype(np.int16)
    code_y = y0 + 94 + 14 * round(args.font_size * 4 / 3)
    native_box = (x0 + 112, code_y - 10, x0 + 1300, code_y + 90)
    combined.crop(native_box).save(output / "native-code.png")
    high_box = tuple(round(v * target_size[i % 2] / source.size[i % 2])
                     for i, v in enumerate(native_box))
    Image.fromarray(actual).crop(high_box).save(output / "high-code.png")
    report = {
        "source": str(args.screenshot.resolve()),
        "source_sha256": hashlib.sha256(args.screenshot.read_bytes()).hexdigest(),
        "source_size": source.size, "high_detail_size": target_size,
        "editor_rectangle_xyxy": BOX,
        "source_dimensions_preserved": True,
        "outside_rectangle_pixel_identical": unchanged,
        "outside_rectangle_changed_pixels": int(np.count_nonzero(np.any(original[outside] != result[outside], axis=1))),
        "method": "original gray checkerboard amplitude / alternate mean; global-phase Triangle weights restricted to editor",
        "background": 128, "contrast": 8, "amplitude": 110, "iterations": 30,
        "font_size": args.font_size, "palette": args.palette,
        "background_rgb": (128 + offsets).tolist(), "tint_clipped_values": 0,
        "channel_gains": gains.tolist(), "channel_biases": biases.tolist(),
        "adaptation": "3346x2090 to 1998x1248, not 2:1; continuous target at rectangle boundaries",
        "scalar_sparse_max_channel_difference": int(np.abs(scalar_error).max()),
        "target_max_channel_error": int(np.abs(error).max()),
        "target_rmse": float(np.sqrt(np.mean(error.astype(float) ** 2))),
        "history": history,
        "native_text": "Project Notes / Setup / Local tools and files. / AYBS6T",
        "high_text": "Image Notes / View / Alternative raster sample. / HH5KDM",
        "implementation": "Local float32 port and independent scalar C++ reference; Rust crate not executed",
        "visual_observation": "pending",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    template = Path(__file__).with_name("marked_vscode_preview.html").read_text()
    template = template.replace("code:[806,1100,1994,1200]", "code:" + json.dumps(native_box))
    for key, file in (("NATIVE", "combined.png"), ("HIGH", "high-detail.png")):
        template = template.replace(f"__{key}__", "data:image/png;base64," + base64.b64encode((output / file).read_bytes()).decode())
    (output / "index.html").write_text(template)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
