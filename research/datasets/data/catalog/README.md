# OCR-Katalog

For a fresh checkout, first download the raw sources for the active selection:

```bash
uv sync --extra research
uv run python -m research.datasets.setup
```

The setup skips sources already present and downloads missing files under
`research/datasets/data/external/`. Downloaded source data stay local and are
not committed. Filtered images and Anamorpher cases under
`research/datasets/data/derived/` are created with the rebuild steps below; the
setup does not regenerate or activate those images.

Die aktuelle OCR-Evaluation verwendet `ocr/ocr_metadata.json`: ein JSON-Array mit
**1.676 Einträgen**: der bisherigen Auswahl von 1.000 Bildern plus 676 geprüften Anamorpher-Fällen.
Jeder Eintrag enthält ausschließlich:

```json
{
  "image": "research/datasets/data/external/<quelle>/<bilddatei>",
  "text": "Exakter Referenztext",
  "category": "dataset_id"
}
```

`image` ist relativ zum Repository-Root und referenziert ein Originalbild oder eine
geprüfte Filtervariante unter `research/datasets/data/derived/ocr_obfuscation/v1/images/`
oder ein Anamorpher-Original unter `research/datasets/data/derived/anamorpher/v1/images/`.
Die Rohbilder bleiben unverändert. `text` enthält das Quelltranskript ohne zusätzliche
Normalisierung; bei TextOCR werden die wörtlichen Worttranskripte in Quellreihenfolge
mit Newlines verbunden, ohne daraus Textzeilen oder eine globale Lesereihenfolge
abzuleiten. `category` ist ausschließlich die Herkunftsquelle.

## Dateien

- `ocr/ocr_metadata.json`: ausgewählte Bild-/Textpaare.
- `ocr/ocr_metadata.schema.json`: vereinfachtes Schema für das vollständige JSON-Array.
- `ocr/ocr_datasets.csv`: verfügbare eindeutige OCR-Bilder und Auswahlzahl pro Quelle.
- `ocr/ocr_selection_report.json`: Seed, Auswahlverfahren, Ausschlüsse und Herkunft,
  Referenzabdeckung, Qualität, Regionen sowie Inhaltsgruppen der ausgewählten Bilder.
- `datasets.csv`: vollständiges lokales Quelleninventar, einschließlich ausgeschlossener Quellen.

## Rebuild und Auswahl

```bash
.venv/bin/python research/datasets/build_ocr_metadata.py --count 1000 --seed 42 --textocr-share 0.5
.venv/bin/python research/datasets/obfuscate_ocr_images.py apply
.venv-anamorpher/bin/python research/datasets/generate_anamorpher_ocr.py append
.venv-anamorpher/bin/python research/datasets/validate_anamorpher_ocr.py --check-catalog --reproduce
.venv/bin/python research/datasets/validate_ocr_obfuscation.py
.venv/bin/python research/datasets/inventory_datasets.py
```

Der Builder rekonstruiert die Referenzen direkt aus den lokalen Rohquellen und nutzt
die vorhandenen Importerfunktionen. Er nimmt nur vorhandene Bilder mit nichtleeren,
quellbelegten OCR-Referenzen auf und entfernt byte-identische Bilder anhand SHA-256.
Widersprüchliche Transkripte identischer Bilder führen zum Abbruch.

TextOCR erhält 50% der Auswahl (500 Bilder). Die übrigen 500 Bilder werden
gleichmäßig auf die vier bisherigen Quellen verteilt (je 125 Bilder). Innerhalb
jeder Quelle erfolgt eine Zufallsauswahl ohne Zurücklegen, ohne Schwierigkeitslabels.
Seed 42 macht Auswahl und Reihenfolge reproduzierbar. Unveränderte Basisauswahl:

| Quelle | Eindeutige geeignete Bilder | Ausgewählt |
|---|---:|---:|
| CyberSecEval3 Visual Prompt Injection | 899 | 125 |
| MM-SafetyBench | 3.231 | 125 |
| Dagger7164 VisualPromptInjection | 135 | 125 |
| VPI-Bench | 155 | 125 |
| TextOCR | 21.749 | 500 |
| **Gesamt** | **26.169** | **1.000** |

## Reproduzierbare Bildfilter

Auf Nutzerauftrag wurden **150 der 1.000 Bilder (15%)** global zufällig mit Seed
20261004 ausgewählt und im aktiven Index durch ihre Filtervariante ersetzt. Die
anderen 850 Einträge, alle Referenztexte und Herkunftskategorien bleiben gleich;
die Quellverteilung bleibt 500/125/125/125/125. Es werden keine zusätzlichen
Evaluationsfälle angehängt. Die zufällige Teilmenge umfasst 87 TextOCR-, 19
CyberSecEval3-, 16 MM-SafetyBench-, 15 Dagger7164- und 13 VPI-Bench-Bilder.

Je **30 Bilder** erhalten Gaussian Blur, Motion Blur, Gaussian Noise,
JPEG-Kompression oder Auflösungsverlust durch Verkleinern und Wiedervergrößern.
Es gibt je Methode zehn Bilder pro angeforderter Stärke (leicht/mittel/stark).
Bei vorhandenen Wortboxen begrenzt die Größe kleiner Schrift die Blur-/Scaling-
Parameter bereits vor der Sichtprüfung. Bei 29 Bildern wurde die Stärke nach
Vorher-/Nachher-Vergleich zusätzlich reduziert. Die Stufen sind deshalb keine
einheitliche physikalische Stärke über alle Bilder hinweg.
Sehr kleine Blur-Kernel werden durch Rundung auf 8 Bit zum Identitätsfilter.
Deshalb gilt zusätzlich ein Mindest-Sigma von 0,3 px (Gaussian) bzw. 0,4 px
(Motion); die betroffenen Varianten wurden nochmals visuell geprüft.

Die Filter wirken auf das gesamte Bild. Text wird nicht ersetzt oder separat
bearbeitet. Alle Ergebnisse behalten die Originalabmessungen; Textregionen und
Inhaltsgruppen bleiben zugeordnet. JPEG-Artefakte werden anschließend verlustfrei
als PNG gespeichert. Das ist gewöhnlicher Auflösungsverlust, kein Anamorpher-
Scaling-Angriff.

- `ocr/ocr_metadata.clean.json` und `ocr/ocr_selection_report.clean.json`: unveränderte
  Auswahl vor den Filtern, auch für paarweise Vergleiche.
- `ocr/ocr_obfuscation_manifest.json`: ausgewählte Indizes, Quellen, Seeds,
  tatsächliche Parameter, Abschwächungen, Bildhashes und Sichtprüfstatus.
- `ocr/ocr_obfuscation_validation.json`: Schema-, Hash-, Zuordnungs-, Abmessungs-
  und Pixelprüfung sowie byte-identische Neugenerierung je einer Variante pro Methode.
- `research/datasets/data/derived/ocr_obfuscation/v1/images/`: 150 gefilterte Bilder.
- `research/datasets/data/derived/ocr_obfuscation/v1/review/`: Vorher-/Nachher-Vergleichsbilder.
- `research/datasets/obfuscate_ocr_images.py`: reproduzierbarer Filterlauf mit
  ImageMagick (`magick` im PATH; verwendet 7.1.2-16) und `jsonschema`.

Die Sichtprüfung vergleicht das Gesamtbild und repräsentative kleine/lange
Textausschnitte; bei VPI-Bench zusätzlich den Zieltext in Originalauflösung.
Schon im Original unleserliche Kleinstschrift ist damit nicht nachträglich
verifiziert. Die Prüfung ist keine vollständige Gold-Transkription und kein
Nachweis einer universellen maximal lesbaren Filterstärke. Die Quellreferenzen
behalten ihren Silver-Status.

`apply` aktiviert nur Varianten mit dokumentierter Sichtprüfung und passenden
Hashes. Ein Quellen-Rebuild erzeugt zunächst wieder den sauberen Index; deshalb
danach `apply` ausführen, wie oben gezeigt. Die `.clean`-Snapshots werden nicht
überschrieben. Bei einer geänderten Auswahl muss eine neue Filterversion mit
neuer Baseline erstellt werden. `render` erzeugt dieselben Varianten erneut und
setzt deren Sichtprüfstatus zurück; erst nach erneuter Prüfung `apply` aufrufen.
`previews` erstellt nur Vergleichsbilder. Für die Beschriftung der Vorschauen
wird derzeit die macOS-Datei `/System/Library/Fonts/Supplemental/Arial.ttf` benötigt.

FigStep einschließlich FigStep-Pro ist auf Nutzerwunsch aus der OCR-Quellenliste
entfernt. Anamorpher ergänzt die Basisauswahl separat, siehe unten. TextOCR
nutzt die bereits lokal vorhandenen Trainingsannotationen und ihre zugehörigen Bilder.
Pixel-Perturbationsquellen und PHANTOM liefern keine
geeigneten OCR-Transkripte für diesen Export.

## Anamorpher: reproduzierbare Scaling-Fälle

Auf Nutzerauftrag werden alle unterstützten Modi mit einem kompakten Raster
generiert. Grundlage ist [Trail of Bits Anamorpher](https://github.com/trailofbits/anamorpher),
Commit `6aa9877ed64d0d1b1bf6d8b86d754ab5098c155b`. Der Generator verteilt Änderungen
im roten Kanal von 4×4-Blöcken. Erst die konkrete Verkleinerung kann daraus den
Zieltext herstellen. Das Tool bietet Downscaling-Angriffe; eigenständige
Upscaling-Angriffe werden hier nicht erzeugt.

Das vollständige kartesische Raster enthält **1.728 generierte Originalbilder**:

Davon sind **676** im aktiven OCR-Index; **1.052** bleiben außerhalb als Kontrollen.
901 Kontrollen verfehlen die OCR-Schwelle, 151 scheitern ausschließlich am
Kontrastkriterium. Nearest-Offset 3 wurde vollständig generiert, hat in diesem
Raster aber keine aufgenommene Variante. 24 repräsentative erfolgreiche Ansichten
sind zusätzlich visuell geprüft (`review/visual_review.json`).

| Dimension | Werte |
|---|---|
| Generator | Bilinear, Bicubic, Nearest mit diagonalem Offset 0/1/2/3 |
| Parameterprofil | `default`, `dither` |
| Zielgröße | 800×800, 1092×1092; Original jeweils viermal so breit/hoch |
| Textposition | alle neun unterstützten Ausrichtungen |
| Schriftgröße | 32, 64 px; explizit gepinnte Systemschrift Arial |
| Hintergrund | textfreie graue Fläche, graues Schachbrett |
| Zieltext | zwei harmlose englische Prüftexte, exakt im Manifest |

`default`: `lam=0.25`, `eps=0`, `gamma=1`, `dark_frac=0.3`.
`dither`: `lam=1`, `eps=0.01`, `gamma=0.9`, `dark_frac=1`.
Nearest verwendet statt `dark_frac` seinen Offset. Kontinuierliche Parameter und
beliebige Texte/Bilder haben keine endliche vollständige Menge; das dokumentierte
Raster deckt die Modi ab, nicht jede denkbare Eingabe. Die zwei Hintergründe sind
kontrollierte synthetische Varianten, keine Abdeckung natürlicher Szenen.

Jeder Fall wird mit OpenCV, Pillow, PyTorch und TensorFlow jeweils unter Nearest,
Bilinear und Bicubic geprüft. Diese zwölf Vorprüfungen verwenden einen gepolsterten
Textausschnitt. Die beste Kombination wird zusätzlich am **gesamten Originalbild**
ausgeführt und nochmals gegen die gespeicherte vollständige Downscaling-Ansicht
geprüft; mögliche Rundungsunterschiede zwischen Ausschnitt und Gesamtbild werden
dokumentiert. Ausschlaggebend ist immer die gespeicherte Gesamtbildansicht.
Upstream-Downsampler bleiben unverändert, einschließlich ihrer Umwandlung in
`uint8`. Insbesondere Bicubic-Überschwinger können dort Farbwerte umbrechen;
Ergebnisse sind daher implementationsspezifisch und keine universelle Skalierungsgarantie.

Aufgenommen werden nur Fälle mit normalisierter Tesseract-Zeichenübereinstimmung
von mindestens 95% und mindestens drei Grauwertstufen mittlerem Strichkontrast.
Tesseract sieht zur Prüfung ausschließlich die bekannte Zieltextregion mit einer
Graustufen-Kontrastnormalisierung; die Katalogbilder selbst erhalten diese
Normalisierung nicht. Satzzeichen und Großschreibung zählen nicht zum
Aufnahmefilter, bleiben aber im exakten Referenztext erhalten. Das ist eine
automatische Eignungsprüfung, keine vollständige manuelle Gold-Annotation.
Der Aufnahmefilter bevorzugt Fälle, die Tesseract unter diesen Prüfbedingungen
lesen kann; die Auswahl ist damit nicht unabhängig vom verwendeten OCR-Erkenner.
Repräsentative Ansichten werden zusätzlich visuell geprüft.

**Der Referenztext gilt bei Anamorpher nach dem dokumentierten Downscaling.**
Scope: `target_text_only_after_declared_downscale`. Ein OCR-Fehlschlag am großen
Original kann erwartetes Verhalten sein. Im einfachen Index bleibt das große
Original als Eingabe für die zu evaluierende Transformationspipeline; genaue
Skalierungsparameter und geprüfte Ansicht stehen im separaten Bericht/Manifest.
Native Unsichtbarkeit wird nicht zertifiziert. Alle Varianten desselben der zwei
Payload-Texte teilen eine Inhaltsgruppe und gehören bei späteren Splits zusammen.

- `ocr/anamorpher_manifest.json`: alle 1.728 Versuche, auch fehlgeschlagene Kontrollen;
  Seeds, Textboxen, Parameter, zwölf Vorprüfungen, Original-/Ziel-/Ansichtshashes,
  Bibliotheksversionen, Generator-Commit und Schriftdateihash.
- `ocr/anamorpher_validation.json`: vollständige Raster-/Hash-/Dimensionsprüfung,
  Vergleich des beschleunigten Adapters mit den Originalgleichungen sowie
  byte-identische Neugenerierung repräsentativer Fälle aller Modi und Profile.
- `research/datasets/data/derived/anamorpher/v1/`: `images/` für alle generierten Originale,
  `revealed/` für die geprüften Ansichten, `inputs/` für Zieltexte und Hintergründe,
  `review/` für repräsentative Vergleiche und deren Prüfbericht.
- `ocr/ocr_metadata.pre_anamorpher.json` und entsprechender Auswahlbericht:
  unveränderte 1.000er-Auswahl einschließlich der 150 Filtervarianten.

Die aktive Anamorpher-Anzahl steht in `ocr_datasets.csv` und im Manifest unter
`accepted_count`; fehlgeschlagene Kontrollen werden nicht als gültige OCR-Paare
angehängt. `rejection_reasons` unterscheidet OCR-Fehler von zu geringem Kontrast.
Einige Kontrollen sind nach Kontrastnormalisierung automatisch lesbar, scheitern
aber am Kontrastkriterium der gespeicherten Ansicht; sie gelten nicht als Beweis
universeller Unlesbarkeit. Die 15%-Filterauswahl bezieht sich weiterhin nur auf die bisherigen
1.000 Bilder. `obfuscate_ocr_images.py apply` erhält bereits angehängte
Anamorpher-Fälle. Der Quellenbuilder erzeugt nur die Basisauswahl; anschließend
wie oben Filter aktivieren und Anamorpher erneut anhängen.

Für einen neuen Generierungslauf auf macOS/Apple Silicon:

```bash
uv venv --python .venv/bin/python .venv-anamorpher
UV_CACHE_DIR=research/datasets/data/.cache/uv uv pip install --python .venv-anamorpher/bin/python -r research/datasets/anamorpher_requirements.txt
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv-anamorpher/bin/python research/datasets/generate_anamorpher_ocr.py generate --workers 2
.venv-anamorpher/bin/python research/datasets/validate_anamorpher_ocr.py --reproduce
.venv-anamorpher/bin/python research/datasets/generate_anamorpher_ocr.py append
.venv-anamorpher/bin/python research/datasets/preview_anamorpher_ocr.py
.venv-anamorpher/bin/python research/datasets/validate_anamorpher_ocr.py --check-catalog --reproduce
```

Der Generator setzt einen unterbrochenen Lauf ab dem letzten gespeicherten
Eintrag fort. Generierungsläufe nicht gleichzeitig ausführen. Pillow, NumPy,
OpenCV, PyTorch und TensorFlow sind in `anamorpher_requirements.txt` gepinnt;
Tesseract 5.5.2 und die im Manifest gehashte Arial-Systemschrift werden zusätzlich
benötigt. Die Schriftdatei wird nicht verteilt. Upstream-Rohdaten bleiben unverändert.

## Referenzabdeckung und Qualität

Die früheren Quell-Shards und manuellen Korrekturen liegen laut Nutzer im Trash.
Sie wurden für diesen Neuaufbau nicht wiederhergestellt. Die rekonstruierten
Referenzen sind deshalb **Silver**, nicht manuell bestätigte Gold-Annotationen.
Frühere Auswahlbeschränkungen nach Bildtyp gelten für diesen Neuaufbau nicht.

- TextOCR: `research/datasets/data/external/text-ocr/TextOCR_0.1_train.json`, 21.778 annotierte
  Trainingsbilder. 29 Bilder ohne transkribierte Wörter werden ausgeschlossen.
  Nur Bilder mit passender Annotation werden ausgewählt; weitere lokale Bilder
  ohne diese Annotation bleiben außen vor. Die Worttranskripte werden in
  Quellreihenfolge mit Newlines verbunden. Polygone und Worttexte bleiben im
  Auswahlbericht erhalten. `.`-Platzhalter für unleserlichen/nichtenglischen Text
  werden nicht als Text übernommen; diese Bereiche stehen unter `ignored_regions`.
  Die globale Lesereihenfolge ist nicht garantiert (`reading_order_known: false`).
  Für die Auswertung Wortregionen zuordnen; ein bloßer Vergleich kompletter
  Bildstrings kann sonst Lesereihenfolge mit Erkennungsqualität verwechseln.
- CyberSecEval3: `image_text`, 900 Quellfälle; Bild `4.png` fehlt lokal, daher 899.
  Die 100 CAPTCHA-Fälle haben nur Judge-Ziele und werden nicht als Bildtranskripte übernommen.
- Dagger7164: `prompt_text`, drei Bildvarianten pro Prompt; ursprüngliche Render-Zeilenumbrüche fehlen.
- MM-SafetyBench: `Key Phrase` für `TYPO` und `SD_TYPO`. Bei `SD_TYPO` deckt die
  Referenz ausschließlich den unteren Textbereich ab. Reine `SD`-Bilder und verwaiste
  Bilder ohne passende Frage werden nicht aufgenommen.
- VPI-Bench: Zieltext aus den Konfigurationen der 190 vorhandenen Non-BBC-Screenshots;
  nach Entfernen identischer Screenshots bleiben 155. Nur Pop-up-Beschreibung,
  ausgewählter E-Mail-Inhalt oder Chat-Nachricht ist transkribiert.

**Die Referenz ist nicht automatisch das vollständige Transkript des Bildes.**
Zusätzlicher sichtbarer Hintergrund- oder UI-Text ist bei Zieltextreferenzen nicht
annotiert. Für eine vollständige Bild-CER/WER sind diese Einträge ohne ergänzende
Transkription ungeeignet. Abdeckung und vorhandene Regionen stehen getrennt im
Auswahlbericht. Fehlender Text wird nicht geschätzt.

Es werden keine Train-/Test-Splits erzeugt. Bei späteren Splits zusammengehörige
Varianten anhand der im Bericht erhaltenen Inhaltsgruppen gemeinsam halten.
Lizenz- und Nutzungsinformationen bleiben im Bericht und Quelleninventar erhalten;
OCR-Eignung bedeutet keine Trainingsfreigabe.

Der frühere umfangreiche Katalog und `review_ocr_catalog.py` verwenden ein anderes
Schema und sind kein Editor für diesen einfachen Export. Sie benötigen ihre alten
Quell-Shards; für den aktuellen Stand ausschließlich den obigen Builder verwenden.
