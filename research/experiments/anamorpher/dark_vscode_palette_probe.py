"""Compare neutral checkerboard samples on the user's dark editor references."""

import argparse
import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from research.experiments.anamorpher.codex_preprocessing_probe import ROOT, limited_size
from research.experiments.anamorpher.marked_vscode_frequency_pair import reference, restricted_operator
from research.experiments.anamorpher.triangle import Triangle, construct, rgb8
from research.experiments.anamorpher.triangle_probe import native_chain


CASES = [
    ("olive-exact", "Oliv · Screenshotfarbe", "olive", (39, 40, 35)),
    ("olive-medium", "Oliv · etwas heller", "olive", (55, 58, 46)),
    ("olive-light", "Oliv · heller", "olive", (75, 79, 62)),
    ("petrol-exact", "Petrol · Screenshotfarbe", "petrol", (13, 42, 53)),
    ("petrol-medium", "Petrol · etwas heller", "petrol", (20, 62, 77)),
    ("petrol-light", "Petrol · heller", "petrol", (28, 82, 100)),
]


def shared_syntax(size, family, font_size, line_height, weight):
    """Color only known identical strings at identical positions in both views."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    path = str(ROOT / "research/workbench/static/fonts/GeistMono.ttf")
    font = ImageFont.truetype(path, font_size)
    font.set_variation_by_axes([weight])
    common = {
        0: '<!doctype html>', 1: '<html lang="en">', 2: '<head>',
        3: '  <title>', 4: '</head>', 5: '<body>', 6: '  <!-- ',
        7: '  <main class="notes">', 8: '    <h1>', 9: '    <h2>',
        10: '    <p>', 12: '    <section id="reference">',
        13: '      <h2>Reference code</h2>', 14: '      <code>',
        15: '    </section>', 16: '  </main>', 17: '</body>', 18: '</html>',
    }
    for row, text in common.items():
        draw.text((124, row * line_height), text, font=font, fill=255)
    # Both reference codes contain exactly six characters.
    draw.text((124 + font.getlength('      <code>XXXXXX'), 14 * line_height),
              '</code>', font=font, fill=255)
    color = (249, 38, 114) if family == "olive" else (71, 137, 205)
    alpha = np.asarray(mask, dtype=np.float32)[..., None] / 255
    return alpha, np.array(color, dtype=np.float32)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--olive", type=Path, required=True)
    parser.add_argument("--petrol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--small-text", action="store_true",
                        help="24-pixel text with regular, semibold and increased contrast controls")
    parser.add_argument("--shared-syntax", action="store_true",
                        help="Small-text sample with readable common syntax; changing spans remain encoded")
    args = parser.parse_args()
    if args.shared_syntax:
        args.small_text = True
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    frames = {
        "olive": (Image.open(args.olive).convert("RGB"), (690, 158, 3116, 2026)),
        "petrol": (Image.open(args.petrol).convert("RGB"), (680, 150, 3120, 2010)),
    }
    binary = ROOT / "runs/anamorpher-probes/codex-frequency-switch-20261013/triangle-reference"
    records = []
    cases = [(name, label, frame, bg, 400, 8) for name, label, frame, bg in CASES]
    if args.small_text:
        cases = [(f"{family}-{preset}", f"{label} · {description}", family, bg, weight, contrast)
                 for family, label, bg in (("olive", "Oliv", (39, 40, 35)),
                                            ("petrol", "Petrol", (13, 42, 53)))
                 for preset, description, weight, contrast in (
                     ("regular", "24 px normal", 400, 8),
                     ("semibold", "24 px kräftiger", 600, 8),
                     ("contrast", "24 px kräftiger + Kontrast", 600, 12))]
    if args.shared_syntax:
        cases = [(f"{family}-syntax", f"{label} · 24 px + gemeinsame Syntax", family, bg, 600, 8)
                 for family, label, bg in (("olive", "Oliv", (39, 40, 35)),
                                          ("petrol", "Petrol", (13, 42, 53)))]
    font_size = 24 if args.small_text else 36
    line_height = 36 if args.small_text else 48
    for name, label, frame_name, background, weight, text_contrast in cases:
        folder = root / name
        folder.mkdir()
        frame, box = frames[frame_name]
        x0, y0, x1, y1 = box
        size = (x1 - x0, y1 - y0)
        target_size = limited_size(frame.size, 2048, 2500)
        full = Triangle(frame.size, target_size)
        op = restricted_operator(full, box)
        refs = [reference((size[0], size[1] + 94), alt, font_size,
                          weight=weight, line_height=line_height,
                          number_size=22 if args.small_text else None,
                          number_x=60 if args.small_text else 28).crop(
            (0, 94, size[0], size[1] + 94)) for alt in (False, True)]
        inks = [np.clip((255 - np.asarray(im, dtype=np.float32)) / 220, 0, 1)
                for im in refs]
        base = np.array(background, dtype=np.float32)
        amplitude = base * np.float32(.85)
        contrast = np.float32(text_contrast)
        mean = base + contrast * inks[1][..., None]
        y, x = np.indices((size[1], size[0]), sparse=True)
        checker = (2 * ((x + y) % 2) - 1)[..., None]
        initial = rgb8(mean + amplitude * (1 - inks[0][..., None]) * checker)
        encoded, history = construct(initial, op.forward(mean), op,
                                     preservation=0, iterations=30)
        if args.shared_syntax:
            alpha, color = shared_syntax(size, frame_name, font_size, line_height, weight)
            encoded = rgb8(encoded * (1 - alpha) + color * alpha)
            mean = mean * (1 - alpha) + color * alpha
        # The olive reference has a tooltip crossing the editor boundary.
        # Preserve its continuation so the existing outside half isn't cut off.
        protected = (690, 268, 906, 320) if frame_name == "olive" else None
        if protected:
            a, b, c, d = protected
            original_overlay = np.asarray(frame.crop(protected))
            encoded[b-y0:d-y0, a-x0:c-x0] = original_overlay
            mean[b-y0:d-y0, a-x0:c-x0] = original_overlay
        combined = frame.copy()
        combined.paste(Image.fromarray(encoded), box[:2])
        combined.save(folder / "combined.png")
        actual = native_chain(binary, np.asarray(combined), [frame.size, target_size], folder)
        high = Image.fromarray(actual)
        high.save(folder / "high-detail.png")
        target_frame = np.asarray(frame, dtype=np.float32).copy()
        target_frame[y0:y1, x0:x1] = mean
        desired = full.resize(target_frame)
        error = actual.astype(np.int16) - desired.astype(np.int16)
        mask = np.ones((frame.height, frame.width), dtype=bool)
        mask[y0:y1, x0:x1] = False
        changed = np.count_nonzero(np.any(np.asarray(combined)[mask] != np.asarray(frame)[mask], axis=1))
        assert changed == 0
        code_box = (x0 + 112, y0 + 14 * line_height - 6, x0 + 1050, y0 + 14 * line_height + line_height)
        title_box = (x0 + 112, y0 + 8 * line_height - 6, x0 + 1050, y0 + 8 * line_height + line_height)
        high_box = lambda crop: tuple(round(v * target_size[i % 2] / frame.size[i % 2]) for i, v in enumerate(crop))
        for kind, crop in (("code", code_box), ("title", title_box)):
            combined.crop(crop).save(folder / f"native-{kind}.png")
            high.crop(high_box(crop)).save(folder / f"high-{kind}.png")
        record = {
            "name": name, "label": label, "background_rgb": background,
            "background_hex": "#" + "".join(f"{v:02x}" for v in background),
            "source": str(getattr(args, frame_name).resolve()),
            "source_sha256": hashlib.sha256(getattr(args, frame_name).read_bytes()).hexdigest(),
            "source_size": frame.size, "high_size": target_size,
            "rectangle": box, "font_size": font_size, "font_weight": weight,
            "line_height": line_height, "text_polarity": "lighter_on_dark",
            "shared_syntax": args.shared_syntax,
            "protected_overlay": protected,
            "contrast_rgb": [text_contrast] * 3, "amplitude_rgb": amplitude.tolist(),
            "outside_changed_pixels": int(changed),
            "target_max_error": int(np.abs(error).max()),
            "target_rmse": float(np.sqrt(np.mean(error.astype(float)**2))),
            "combined_sha256": hashlib.sha256((folder / "combined.png").read_bytes()).hexdigest(),
            "history": history, "visual_observation": "pending",
            "scope": "neutral known-text local demonstration; no general OCR or upload-path guarantee",
        }
        (folder / "report.json").write_text(json.dumps(record, indent=2) + "\n")
        template = Path(__file__).with_name("marked_vscode_preview.html").read_text()
        template = template.replace("Das ursprüngliche graue Raster liegt ausschließlich im Editor.",
                                    "Das farbige Raster liegt ausschließlich im Editor. " + label + ".")
        template = template.replace("3346 × 2090", f"{frame.width} × {frame.height}")
        template = template.replace("1998 × 1248", f"{target_size[0]} × {target_size[1]}")
        template = template.replace("all:[0,0,3346,2090]", "all:" + json.dumps([0, 0, *frame.size]))
        template = template.replace("editor:[694,120,2744,1558]", "editor:" + json.dumps(box))
        template = template.replace("code:[806,1100,1994,1200]", "code:" + json.dumps(code_box))
        template = template.replace("1248/2090:1998/3346", f"{target_size[1]}/{frame.height}:{target_size[0]}/{frame.width}")
        for key, file in (("NATIVE", "combined.png"), ("HIGH", "high-detail.png")):
            template = template.replace(f"__{key}__", "data:image/png;base64," + base64.b64encode((folder / file).read_bytes()).decode())
        (folder / "index.html").write_text(template)
        records.append(record)
        print(json.dumps({k: record[k] for k in ("name", "background_hex", "target_rmse", "outside_changed_pixels")}), flush=True)
    (root / "report.json").write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    main()
