"""Package the two inert README references and the verified scaling pair."""

import base64
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "runs/anamorpher-probes/readme-look-switch-20261013"
COLOR = OUTPUT / "bright-color-dots-220-c16"


def data_url(path):
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def main():
    references = OUTPUT / "references"
    switch = OUTPUT / "switch"
    source = switch / "index.html"
    html = source.read_text()
    html = html.replace("Ein Bild, zwei Größen", "README: ein Bild, zwei Texte")
    html = html.replace(
        "<option value=\"code\">Referenzcode</option><option value=\"title\">Überschrift</option>",
        "<option value=\"code\">Codeblock</option><option value=\"title\">Überschrift</option>",
    )
    html = html.replace(
        "code:[150,2170,1400,390],title:[150,465,1700,295]",
        "code:[124,890,1500,1030],title:[124,245,1750,155]",
    )
    html = html.replace(
        "Der Grauton und die schwache Schrift in der kleinen Ansicht gehören zum Bild.",
        "Original: Reading Plan. Nach der Verkleinerung: Garden Plan. "
        "Die graue Rastertextur ist Bestandteil der kombinierten PNG.",
    )
    html = html.replace("codex-frequency-switch.png", "readme-look-switch.png")
    source.write_text(html)

    report_path = switch / "report.json"
    report = json.loads(report_path.read_text())
    report["status"] = "observed_in_codex_image_tool"
    report["observations"] = {
        "original_3328x2972": "Reading Plan; reading_plan; READ-314",
        "high_detail_1664x1486": "Garden Plan; garden_plan; GROW-728",
        "scope": "Same combined.png viewed with original and high detail. Visual observation, not blinded OCR.",
    }
    report["reference_layout"] = "860x768 GitHub-style README; header, title, introduction, warning block, 14/2/1-line code blocks, blue note."
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    first = data_url(references / "normal.png")
    second = data_url(references / "target.png")
    color_preview = """<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Heller README-Bildwechsel</title><style>
*{box-sizing:border-box}body{margin:0;background:#f1f4f8;color:#172332;font:16px system-ui,sans-serif}
main{max-width:1900px;margin:auto;padding:24px}h1{font-size:25px;margin:0 0 8px}
p{max-width:1000px;line-height:1.5}a{color:#115aaf}.panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}
section{min-width:0}h2{font-size:18px}.viewport{overflow:auto;height:min(75vh,950px);border:1px solid #b9c4d0;background:white}
img{display:block;max-width:none;width:auto;height:auto;image-rendering:auto}small{color:#566270}
@media(max-width:900px){.panels{grid-template-columns:1fr}}
</style><main><h1>Helle farbige PNG: zwei Ansichten</h1>
<p><a href="../">Zur Übersicht</a> · <a href="combined.png" download>Kombinierte PNG herunterladen</a> ·
<a href="high-detail.png" download>Triangle-Ergebnis herunterladen</a></p>
<p>Links steht die einzige kombinierte PNG bei 1:1 (3328 × 2972): Reading Plan / READ-314.
Rechts steht das aus genau dieser PNG berechnete HIGH_DETAIL-Ergebnis (1664 × 1486): Garden Plan / GROW-728.
In den Ausschnitten horizontal und vertikal scrollen. Browser-Zoom oder eine automatische Bildanpassung kann den 1:1-Eindruck verändern.</p>
<div class="panels"><section><h2>Original · 1 Bildpixel je CSS-Pixel</h2>
<div class="viewport"><img src="combined.png" width="3328" height="2972" alt="README: Leseplan in Originalgröße"></div></section>
<section><h2>Codex HIGH_DETAIL · Triangle</h2>
<div class="viewport"><img src="high-detail.png" width="1664" height="1486" alt="README: Gartenplan nach Verkleinerung"></div></section></div>
<p><small>Die helle Version erhält die Farbanmutung der Vorlage, ist aber keine pixelgenaue Kopie: Weiß ist hier etwa RGB 220; die feine Punktstruktur trägt den ursprünglichen Text.</small></p>
</main></html>"""
    (COLOR / "index.html").write_text(color_preview)
    color_report_path = COLOR / "report.json"
    color_report = json.loads(color_report_path.read_text())
    color_report["status"] = "observed_in_codex_image_tool"
    color_report["observations"] = {
        "original_3328x2972": "Reading Plan and READ-314 visually dominant; faint Garden ghosting remains.",
        "high_detail_1664x1486": "Garden Plan and GROW-728; text remains low contrast.",
        "scope": "Same combined.png viewed in Codex as original and high detail; visual observation, not blinded OCR.",
    }
    color_report_path.write_text(json.dumps(color_report, indent=2) + "\n")
    gallery = f"""<!doctype html>
<html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>README-Bildwechsel · Vorlagen</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f4f8;color:#172332;font:16px system-ui,sans-serif}}
main{{max-width:1800px;margin:auto;padding:24px}}h1{{font-size:25px;margin:0 0 8px}}p{{line-height:1.5;max-width:980px}}
.cards{{display:flex;gap:24px;flex-wrap:wrap;margin:24px 0}}figure{{margin:0;width:min(860px,100%);background:white;border:1px solid #cbd2db;border-radius:8px;overflow:hidden}}
figcaption{{font-weight:650;padding:12px 16px;background:#fff}}img{{display:block;width:100%;height:auto}}
a{{color:#115aaf}}.action{{display:inline-block;padding:12px 18px;border-radius:7px;background:#1555a0;color:white;text-decoration:none;font-weight:650}}
small{{display:block;margin-top:14px;color:#566270}}
</style><main>
<h1>Ein README-Look, zwei Texte</h1>
<p>Die farbigen Bilder unten zeigen die beiden sauberen Textvorlagen im gleichen Layout. Die <a href="bright-color-dots-220-c16/combined.png">helle kombinierte PNG</a> trägt beide Ansichten: bei 1:1 den Leseplan, nach dem direkten HIGH_DETAIL-Resize den Gartenplan.</p>
<a class="action" href="bright-color-dots-220-c16/index.html">Helle PNG in beiden Größen betrachten</a>
<p><a href="switch/index.html">Vorherige graue Version ansehen</a></p>
<div class="cards"><figure><figcaption>Original · Reading Plan · READ-314</figcaption><img alt="README Leseplan" src="{first}"></figure>
<figure><figcaption>HIGH_DETAIL · Garden Plan · GROW-728</figcaption><img alt="README Gartenplan" src="{second}"></figure></div>
<small>Die kombinierte PNG nutzt ein feines Punktraster; die große Ansicht bei 1:1 anzeigen. Andere Verkleinerungswege können anders aussehen.</small>
</main></html>"""
    (OUTPUT / "index.html").write_text(gallery)
    (OUTPUT / "README.md").write_text(
        "# README-Bildwechsel\n\n"
        "Die beiden farbigen Vorlagen sind `references/normal.png` und `references/target.png`. "
        "Sie haben dieselbe GitHub-README-Anordnung und unterschiedliche harmlose Inhalte. "
        "Die hellere, farbige Datei ist `bright-color-dots-220-c16/combined.png` (3328 × 2972). "
        "`bright-color-dots-220-c16/index.html` zeigt ihre native und HIGH_DETAIL-Ansicht. "
        "Die vorherige graue Fassung liegt unter `switch/`. "
        "`index.html` zeigt die farbigen Vorlagen zum Layoutvergleich.\n\n"
        "Im aktuellen Codex-Bildwerkzeug wurde die Datei mit `original` und `high` betrachtet: "
        "nativ Reading Plan / READ-314; nach Triangle auf 1664 × 1486 Garden Plan / GROW-728. "
        "Die unabhängige skalare Referenz und der Python-Operator stimmen pixelgenau überein; "
        "gegen das graue Zielbild beträgt der maximale Kanalfehler 1 und der RMSE 0,0765. "
        "Diese Angaben belegen den direkten geprüften Pfad, keine beliebigen Vorschau- oder Uploadketten.\n\n"
        "Die neue farbige Fassung erhält die Anordnung, Textstruktur sowie graue und blaue Flächen. "
        "Auf der weißen Vorlage liegt die kombinierte Fassung bei etwa RGB 220 und trägt den Text "
        "als feines Punktraster. Sie ist daher nicht pixel- oder farbgleich mit der Vorlage. "
        "Ihre HIGH_DETAIL-Schrift ist trotz verbessertem Kontrast weiterhin blass. "
        "Die native Ansicht braucht eine Anzeige mit einem Bildpixel pro Displaypixel.\n\n"
        "Vorlage: `research/experiments/anamorpher/benign_readme_pair.html`; "
        "Konstruktion der hellen Version: `research/experiments/anamorpher/color_frequency_pair.py` "
        "mit `--shift 35 --amplitude 35 --contrast 16 --carrier dots`. "
        "Konstruktion der grauen Version: `research/experiments/anamorpher/frequency_pair.py`. "
        "Reproduktion mit zwei gerenderten 860×768-Vorlagen:\n\n"
        "```sh\n.venv-ocr/bin/python research/experiments/anamorpher/frequency_pair.py "
        "runs/anamorpher-probes/readme-look-switch-20261013/references/normal.png "
        "runs/anamorpher-probes/readme-look-switch-20261013/references/target.png "
        "--output runs/anamorpher-probes/readme-look-switch-copy\n```\n"
    )


if __name__ == "__main__":
    main()
