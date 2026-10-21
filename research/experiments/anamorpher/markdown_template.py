"""Local editable Markdown image-pair template; never executes Markdown content."""

import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from research.experiments.anamorpher.codex_preprocessing_probe import ROOT, limited_size
from research.experiments.anamorpher.marked_vscode_frequency_pair import restricted_operator
from research.experiments.anamorpher.triangle import Triangle, construct, rgb8
from research.experiments.anamorpher.triangle_probe import native_chain

FONT_PATH = ROOT / "research/workbench/static/fonts/GeistMono.ttf"
BOX = (680, 150, 3120, 2010)
RIGHT_BOX = (1900, 150, 3120, 2010)
SOURCE = ROOT / "runs/anamorpher-probes/vscode-dark-colors-20261014/report.json"
DEFAULT_FIXED = """# Projektbegleiter

Diese Übersicht bleibt in beiden Ansichten gleich.
Sie sammelt Struktur, Hinweise und nächste Schritte.

## Überblick
- Kleine Aufgaben in Ruhe bearbeiten.
- Ergebnisse verständlich festhalten.
- Offene Fragen für später notieren.

## Dokumente
```text
notes/
├── README.md
├── NOTES.md
└── archive/
```

## Arbeitsweise
1. Die aktuelle Aufgabe auswählen.
2. Einen überschaubaren Schritt erledigen.
3. Das Ergebnis kurz zusammenfassen.
4. Den nächsten Schritt festhalten.

## Checkliste
- [x] Übersicht vorbereitet
- [x] Notizbereich eingerichtet
- [ ] Aktuellen Stand ergänzen
- [ ] Offene Punkte durchsehen

## Notizen
> Klare Notizen helfen beim Wiedereinstieg.

Kurze Absätze machen den Text leichter lesbar.
Listen halten zusammengehörige Punkte beieinander.

## Nächster Schritt
Die Notizen rechts ergänzen und später prüfen.

---
Stand: Entwurf · Format: Markdown
"""


def font(size=24, weight=600):
    result = ImageFont.truetype(str(FONT_PATH), size)
    result.set_variation_by_axes([weight])
    return result


def wrap_markdown(text, max_width):
    """Visual word wrap only; saved Markdown retains the exact input."""
    face = font()
    rows = []
    for source_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = source_line.expandtabs(4)
        while face.getlength(line) > max_width:
            end = min(len(line), int(max_width / face.getlength("M")))
            while end > 1 and face.getlength(line[:end]) > max_width:
                end -= 1
            space = line.rfind(" ", 0, end + 1)
            if space > end // 2:
                end = space + 1
            rows.append(line[:end])
            line = line[end:]
        rows.append(line)
    if len(rows) > 49:
        raise ValueError(f"Der Text benötigt {len(rows)} Anzeigezeilen. Bitte auf höchstens 49 Zeilen kürzen.")
    return rows


def ink_image(text, size):
    rows = wrap_markdown(text, size[0] - 70)
    im = Image.new("L", size, 0)
    draw = ImageDraw.Draw(im)
    face = font()
    for index, line in enumerate(rows):
        y = 12 + 36 * index
        draw.text((24, y), line, font=face, fill=255)
    return np.asarray(im, dtype=np.float32) / 255, len(rows)


def generate(scaled, output, fixed=DEFAULT_FIXED, native_strength=.65):
    for value in (scaled, fixed):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Bitte beide Markdown-Felder ausfüllen.")
        if len(value) > 6000:
            raise ValueError("Pro Ansicht sind maximal 6000 Zeichen möglich.")
    if not isinstance(native_strength, (int, float)) or not .05 <= native_strength <= 1:
        raise ValueError("Die Rasterstärke muss zwischen 5 und 100 Prozent liegen.")
    x0, y0, x1, y1 = RIGHT_BOX
    size = (x1 - x0, y1 - y0)
    b, lines_b = ink_image(scaled, size)
    sources = json.loads(SOURCE.read_text())
    path = Path(next(r["source"] for r in sources if r["name"] == "petrol-exact"))
    frame = Image.open(path).convert("RGB")
    # Update only the active filename and its breadcrumb for the Markdown demo.
    draw = ImageDraw.Draw(frame)
    draw.rectangle((690, 55, 1138, 103), fill=(13, 54, 66))
    draw.text((714, 61), "M  README.md     ×", font=font(24, 400), fill=(180, 198, 202))
    draw.rectangle((710, 110, 2420, 149), fill=(13, 42, 53))
    draw.text((716, 112), "notes  >  README.md", font=font(24, 400), fill=(140, 164, 172))
    # Both Markdown areas share one editor, one tab and one line-number gutter.
    draw.rectangle((BOX[0], BOX[1], BOX[2]-1, BOX[3]-1), fill=(13, 42, 53))
    fixed_rows = wrap_markdown(fixed, RIGHT_BOX[0] - BOX[0] - 170)
    face = font()
    numbers = font(22, 400)
    for index, line in enumerate(fixed_rows):
        y = BOX[1] + 12 + 36 * index
        color = (203, 217, 221)
        if line.lstrip().startswith("#"):
            color = (94, 205, 196)
        elif line.lstrip().startswith(("- ", "1.", "2.", "3.", "4.")):
            color = (153, 192, 219)
        elif line.startswith(("```", ">", "---")):
            color = (188, 166, 217)
        draw.text((BOX[0] + 60, y + 2), str(index + 1).rjust(2), font=numbers, fill=(104, 133, 143))
        draw.text((BOX[0] + 124, y), line, font=face, fill=color)
    target_size = limited_size(frame.size, 2048, 2500)
    full = Triangle(frame.size, target_size)
    op = restricted_operator(full, RIGHT_BOX)
    base = np.array((13, 42, 53), dtype=np.float32)
    mean = base + 8 * b[..., None]
    y, x = np.indices((size[1], size[0]), sparse=True)
    checker = (2 * ((x + y) % 2) - 1)[..., None]
    # A content-free carrier replaces the former native text.
    initial = rgb8(mean + base * native_strength * checker)
    encoded, history = construct(initial, op.forward(mean), op, preservation=0, iterations=40)
    output.mkdir(parents=True, exist_ok=False)
    combined = frame.copy()
    combined.paste(Image.fromarray(encoded), RIGHT_BOX[:2])
    combined.save(output / "combined.png")
    frame.save(output / "frame.png")
    binary = ROOT / "runs/anamorpher-probes/codex-frequency-switch-20261013/triangle-reference"
    actual = native_chain(binary, np.asarray(combined), [frame.size, target_size], output)
    Image.fromarray(actual).save(output / "high-detail.png")
    combined.crop((x0, y0, x1, y0 + 410)).save(output / "native-excerpt.png")
    target_frame = np.asarray(frame, dtype=np.float32).copy()
    target_frame[y0:y1, x0:x1] = mean
    error = actual.astype(float) - full.resize(target_frame)
    mask = np.ones((frame.height, frame.width), dtype=bool)
    mask[y0:y1, x0:x1] = False
    assert np.array_equal(np.asarray(frame)[mask], np.asarray(combined)[mask])
    (output / "scaled.md").write_text(scaled)
    (output / "fixed.md").write_text(fixed)
    report = {
        "source_size": frame.size, "high_size": target_size, "rectangle": RIGHT_BOX,
        "font_size": 24, "line_height": 36, "font_weight": 600,
        "display_lines": [len(fixed_rows), lines_b], "style": "text-free-checker",
        "native_strength": native_strength,
        "fixed_region": (BOX[0], BOX[1], RIGHT_BOX[0] - 2, BOX[3]),
        "method": "single editor: static readable Markdown left; text-free carrier right; target Markdown in mean",
        "background_rgb": [13, 42, 53], "scaled_text_contrast": 8,
        "source_frame_edits": ["single README tab", "single breadcrumb", "static left Markdown"],
        "outside_editor_unchanged_relative_to_frame": True,
        "target_rmse": float(np.sqrt(np.mean(error ** 2))),
        "target_max_error": int(np.abs(error).max()), "history": history,
        "combined_sha256": hashlib.sha256((output / "combined.png").read_bytes()).hexdigest(),
        "limitation": "No before text. Target can remain faintly visible at native size; arbitrary new texts require checking both views",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def serve(root, port):
    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if host not in (f"127.0.0.1:{port}", f"localhost:{port}") or (
                origin and origin != f"http://{host}"
            ):
                return self.reply(403, {"error": "Nur lokale Anfragen aus dieser Vorlage sind erlaubt."})
            if self.path != "/api/generate":
                return self.reply(404, {"error": "Unbekannter Endpunkt."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100000 or "application/json" not in self.headers.get("Content-Type", ""):
                    raise ValueError("Ungültige Textanfrage.")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("Ungültige Textanfrage.")
            except (ValueError, json.JSONDecodeError) as exc:
                return self.reply(400, {"error": str(exc)})
            if not lock.acquire(blocking=False):
                return self.reply(409, {"error": "Ein Bild wird bereits erzeugt. Bitte kurz warten."})
            try:
                name = uuid.uuid4().hex[:12]
                report = generate(request.get("scaled"), root / "outputs" / name,
                                  fixed=request.get("fixed", DEFAULT_FIXED),
                                  native_strength=request.get("native_strength", .65))
                self.reply(200, {"base": f"outputs/{name}", "report": report})
            except (ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})
            except Exception:
                self.reply(500, {"error": "Das Bild konnte nicht erzeugt werden. Bitte den lokalen Server prüfen."})
                raise
            finally:
                lock.release()

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8038)
    parser.add_argument("--scaled", type=Path)
    parser.add_argument("--fixed", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.root.resolve(), args.port)
    elif args.scaled:
        print(json.dumps(generate(args.scaled.read_text(), args.root.resolve(),
                                  fixed=args.fixed.read_text() if args.fixed else DEFAULT_FIXED)))
    else:
        parser.error("Use --serve or supply --scaled.")


if __name__ == "__main__":
    main()
