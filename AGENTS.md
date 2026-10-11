# Aktueller OCR-Auftrag und Ablage (Stand 2026-10-04)

Die folgenden Regeln ersetzen für die aktuelle OCR-Auswahl die historischen
Katalog-/Typografievorgaben weiter unten:

- Aktiver Index: `datasets/catalog/ocr/ocr_metadata.json`, JSON-Array mit nur
  `image`, `text`, `category`. Schema: `datasets/catalog/ocr/ocr_metadata.schema.json`.
- `image` referenziert Rohbilder, geprüfte globale Filtervarianten oder Anamorpher-Originale relativ zum Repository-Root;
  `text` ist das exakte Quelltranskript; `category` ist die Herkunftsquelle.
- Rebuild: `.venv/bin/python scripts/datasets/build_ocr_metadata.py --count 1000 --seed 42 --textocr-share 0.5`.
  Danach `.venv/bin/python scripts/datasets/obfuscate_ocr_images.py apply`, dann
  `.venv-anamorpher/bin/python scripts/datasets/generate_anamorpher_ocr.py append`, dann
  `.venv/bin/python scripts/inventory_datasets.py`.
- 150/1.000 zufällige Bilder (Seed 20261004) referenzieren abgeleitete Filterbilder
  unter `datasets/derived/ocr_obfuscation/v1/images/`; 850 bleiben Originale.
  Je 30 Bilder: Gaussian Blur, Motion Blur, Noise, JPEG-Artefakte, Auflösungsverlust.
  Text, Kategorie, Bildabmessungen und Rohdaten bleiben unverändert.
  Parameter, Sichtprüfung und SHA-256 stehen in `ocr_obfuscation_manifest.json`.
  Die `.clean.json`-Snapshots erhalten die Auswahl vor den Filtern. `render` setzt
  die Sichtprüfung der erneut erzeugten Bilder zurück; nie ungeprüft aktivieren.
  Sichtprüfung ist keine Gold-Transkription aller bereits schwer lesbaren Wörter.
- Auswahl: 1.000 Bilder, zufällig ohne Zurücklegen; 50% TextOCR (500 Bilder),
  die übrigen 500 gleichmäßig auf CyberSecEval3, MM-SafetyBench, Dagger7164 und
  VPI-Bench verteilt (je 125). Byte-identische Bilder sind dedupliziert.
  Es gibt keine Schwierigkeitslabels oder Sortierung nach vermuteter Angriffshäufigkeit.
- FigStep einschließlich FigStep-Pro wurde auf Nutzerwunsch aus den OCR-Quellen
  entfernt. Anamorpher ergänzt die bisherigen 1.000 Bilder mit 676 automatisch geprüften
  Fällen aus 1.728 vollständig generierten Kombinationen (insgesamt 1.676
  aktive Einträge; 1.052 Kontrollen außerhalb des Index). TextOCR nutzt die lokalen
  `datasets/external/text-ocr/TextOCR_0.1_train.json`-Annotationen und `train_images/`.
- Die alten Quell-Shards liegen laut Nutzer im Trash. Auf Nutzerauftrag wurden die
  anderen vier Quellen aus Rohdaten rekonstruiert, nicht aus Trash oder Cache.
  Frühere Gold-Labels und manuelle Korrekturen sind nicht wiederhergestellt.
- Nur belegter Bildtext zählt. CyberSecEval3-Fälle ohne `image_text` (100 CAPTCHA-
  Judge-Ziele) und das lokal fehlende Bild `4.png` sind ausgeschlossen.
- Der separate `ocr_selection_report.json` bewahrt Scope, Qualität (Silver für
  Quelltranskripte, `synthetic_reference` für Anamorpher),
  Herkunft, vorhandene Regionen, Inhaltsgruppen und Nutzungsinformationen.
  Zieltextreferenzen sind keine vollständigen Bildtranskripte; Hintergrund-/UI-Text
  darf bei der Evaluation nicht fälschlich als OCR-Fehler bewertet werden.
- Bei zukünftigen Splits Varianten derselben Inhaltsgruppe zusammenhalten.
- TextOCR liefert Worttranskripte und Polygone, keine garantierte globale Lesereihenfolge.
  `text` verbindet belegte Wörter in Quellreihenfolge mit Newlines (keine rekonstruierten
  Textzeilen). `.`-Platzhalter für unleserlichen/nichtenglischen Text sind ausgeschlossen;
  ihre Regionen bleiben im Bericht als `ignored_regions` erhalten. Für saubere
  Auswertung Wortregionen zuordnen und nicht eine willkürliche Bild-Lesereihenfolge bewerten.
- Anamorpher: drei Generatoren (Nearest mit allen vier Offsets), zwei Profile,
  zwei Zielgrößen, neun Ausrichtungen, zwei Schriftgrößen, zwei textfreie
  Hintergründe und zwei Texte. Alle zwölf Downsampler-Kombinationen werden
  vorgeprüft; die ausgewählte Gesamtbildansicht wird nochmals per OCR geprüft.
  Referenzscope ist `target_text_only_after_declared_downscale`, nicht eine
  Bestätigung nativer Sichtbarkeit. Parameter/Seeds/Hashes stehen separat in
  `ocr/anamorpher_manifest.json`. Fehlgeschlagene Fälle bleiben als Kontrollen
  erhalten. Varianten derselben Payload teilen eine Inhaltsgruppe.
  Rohquellen nicht verändern. Nicht mehrere Generatorläufe gleichzeitig starten.
- `datasets/catalog/ocr/ocr_datasets.csv` enthält die sechs aktuellen Quellen.
  `datasets/catalog/datasets.csv` bleibt das vollständige lokale Inventar; dort ist
  FigStep ausdrücklich aus OCR ausgeschlossen. Rohdaten werden nicht verändert.
- Die bisherigen rich-catalog Import-/Review-Workflows gelten nur für den alten
  Katalog und sind nicht für den vereinfachten OCR-Index zu verwenden.

## Historischer Kontext vor dem vereinfachten Neuaufbau

# Gemeinsamer Agent-Kontext: Bilddatensätze für OCR-Evaluation

## Ziel und Auftrag

Wir arbeiten die lokalen Quellen unter `datasets/` **Datensatz für Datensatz** durch. Das aktuelle Ziel ist eine belastbare Evaluation der Bild-Transformationspipeline: Sie soll bereits sichtbaren Text für OCR-Erkenner besser lesbar machen. Dafür brauchen wir pro geeignetem Bild den tatsächlich sichtbaren Text als Referenz sowie Herkunft, Bild-/Textkategorie, Varianten und Qualitätsstatus, damit sich Schwachstellen nach Bildtyp auswerten lassen. Training, zusätzliche ML-Labels und Pixel-Perturbation-Evaluation sind spätere Aufgaben und sollen jetzt nicht mit der OCR-Evaluation vermischt werden.

Aufgabe eines Agents: Zuerst den gewählten Datensatz und seine vorhandenen Bilder, Tabellen und Metadaten untersuchen und dem Nutzer Eignung, Abdeckung und Lücken berichten. Erst nach einem entsprechenden Auftrag den Import umsetzen. Bestehende Rohdaten nicht verändern.

## Auswahl- und Metadatenregeln

- Für die aktuelle OCR-Evaluation zählen **Text-Injection-Bilder mit im Bild sichtbarem Text**. Reine Pixel-Perturbationsdaten separat für die spätere MLL-Arbeit vormerken.
- Angreiferziel, System-/User-Prompt, Judge-Frage, erwartete Modellantwort und ähnlicher Begleittext sind **kein OCR-Transkript**, sofern sie nicht tatsächlich im Bild stehen.
- Exakte Quelltranskripte und für den Vergleich normalisierten Text getrennt halten. Angeben, ob die Referenz das ganze Bild oder nur einen Zieltextbereich abdeckt (`target_text_only`); bei Teilabdeckung Regionen erfassen, soweit möglich. Herkunft und Vertrauensniveau der Annotation (z. B. Quelle/Silver, manuell verifiziert/Gold, ausstehend) dokumentieren. Fehlende Transkripte nicht erraten.
- Zusammengehörige Bildvarianten über dieselbe Inhaltsgruppe verbinden und bei Evaluations-Splits zusammenhalten. Lizenz/Nutzungsrechte und eine eventuelle Trainingsfreigabe getrennt dokumentieren.
- Den vorhandenen Schemakontrakt in `datasets/catalog/schema/metadata.schema.json` beachten. Neue Quellen als eigene Shards in `datasets/catalog/sources/` importieren; den gemeinsamen Katalog und das Inventar anschließend mit den vorhandenen Skripten neu bauen und Pfade, Mengen, Zuordnungen und Annotationen prüfen.
- Für Bildtypografie ist Dagger7164 die Referenz für die gewünschten Felder (Schriftfamilienklasse/-kandidaten, Stil/Schnitt, Größe samt Einheit, Text-/Hintergrundfarbe, Innenabstand). Der gemeinsame Katalog führt diese Felder unter `visual.typography` für jedes Bild. Nur quellbelegte Werte eintragen; unbekannte Werte `null`/`[]` lassen und `metadata_status` sowie `evidence` beachten. CSS-Fontstapel sind deklarierte Kandidaten, keine Bestätigung der tatsächlich gerenderten Schrift. Der Katalogbuilder normalisiert die Quell-Shards in Schema 1.1.0; Quelltranskripte und manuelle Review-Labels nicht verändern.

## Ablage und bisheriger Stand

- `datasets/catalog/datasets.csv`: Inventar der Quellen und ihr Bearbeitungsstatus.
- `datasets/catalog/metadata.jsonl`: zusammengeführte Bildmetadaten; `datasets/catalog/sources/*.jsonl`: quellenspezifische Datensätze. `datasets/catalog/README.md` beschreibt Aufbau, Rebuild und Quellenbesonderheiten. Importskripte liegen unter `scripts/datasets/`.
- Bereits für OCR aufgenommen: CyberSecEval3 Visual Prompt Injection (815 aktive Einträge aus 1.000 Fällen; 5 CAPTCHAs, 10 gemeinsame `plain_background`/`list`-Bilder und alle 5 `single_line`-Bilder behalten; 95 CAPTCHA- und 90 Listen-Metadatensätze archiviert), FigStep einschließlich FigStep-Pro (731), Dagger7164 Typographic Visual Prompt Injection (135), MM-Safety-Bench (`TYPO`/`SD_TYPO`, 3.360) und eine manuell ausgewählte VPI-Bench-Teilmenge (11 Bilder aus 190 Screenshots). Die aktiven VPI-Bench-Einträge sind `gold`, bleiben aber ausdrücklich `target_text_only`; 179 nicht ausgewählte Einträge sind aus dem OCR-Katalog entfernt und ihre Metadaten liegen im Archiv unter `datasets/catalog/excluded_sources/`. Rohbilder bleiben erhalten. Details stehen im Katalog-README.
- `datasets/catalog/ocr_datasets.csv` ist die kompakte operative Übersicht der ausgewählten OCR-Quellen. Sie enthält die fünf importierten Quellen sowie Anamorpher als Generierungsprüfkandidat. Das vollständige lokale Quelleninventar bleibt separat in `datasets/catalog/datasets.csv`.
- Externe Rohdatensätze liegen gesammelt unter `datasets/external/`; Katalogdateien und Skripte bleiben unter `datasets/catalog/` bzw. `scripts/datasets/`. Den Cache `datasets/.cache/` nicht als Datensatzquelle behandeln.
- PHANTOM ist mit 48.552 Bildern als Archiv-Shard unter `datasets/catalog/excluded_sources/` erhalten, aber aus `metadata.jsonl` ausgeschlossen: Goals und Prompts sind keine verlässlichen Bildtranskripte (`ocr_eval=false`).
- VisInject (jeffliulab), `multimodal_injection` und Visual-Adversarial-Examples-Jailbreak wurden als Pixel-Perturbation bzw. nicht passende Text-Injection-Quelle eingeordnet und gehören nicht in die aktuelle Text-OCR-Evaluation. PRISM (`Zonghao2025/PRISM`) ist ebenfalls nicht für diese OCR-Evaluation geeignet. Anamorpher gehört zur OCR-Auswahl, muss aber als Scaling-Attack-Datensatz erst mit reproduzierbaren Generierungsparametern aufgebaut und genauer geprüft werden.

## VPI-Bench: aktueller Bearbeitungsstand

`datasets/external/VPI-Bench/vpi-bench` enthält 306 Testfälle; nach Ausschluss der BBC-Fälle verweisen 227 aktive Testfallreferenzen auf 190 eindeutige Web-URLs. Alle 190 gerenderten Screenshots liegen unter `datasets/external/VPI-Bench/screenshots/` und bleiben für spätere Aufgaben erhalten. Auf Nutzerwunsch sind 11 ausgewählte Bilder in `datasets/catalog/sources/vpi_bench.jsonl` und `metadata.jsonl` aktiv; die 179 übrigen Metadatensätze liegen in `datasets/catalog/excluded_sources/vpi_bench_omitted_from_ocr.jsonl`. Alle Screenshots haben eine Viewport-Auflösung von 1015×850. Doppelte URL-Verweise teilen einen Katalogdatensatz.

Die Referenzen stammen aus den Web-Konfigurationen: Pop-up-Beschreibungen, ausgewählte E-Mail-Inhalte oder Chat-Nachrichten. Die 11 aktiven Einträge sind nach Nutzerfreigabe manuell geprüft/`gold`, bleiben aber `target_text_only`: anderer sichtbarer Seitentext ist nicht Teil des Transkripts. Textregionen sind nicht annotiert. 36 Web-Pop-up-Konfigurationen verweisen auf lokal fehlende Hintergrundbilder. Die Aufnahme erfolgte über die veröffentlichten Benchmark-URLs. Es wurden keine Formulare abgesendet oder externen Links aus den Testfällen geöffnet. Der Prüfbericht liegt unter `datasets/catalog/reports/vpi_bench_capture_audit.json`.

VPI-Bench ist für die Zieltexttranskripte abgeschlossen. Zieltextregionen können später optional ergänzt werden. Die übrigen Silver-Quellen werden weiterhin manuell mit `scripts/datasets/review_ocr_catalog.py` geprüft; Anamorpher benötigt zuerst reproduzierbare Generierungsparameter.

Anamorpher ist ebenfalls für OCR ausgewählt. Die drei lokalen Demo-Bilder sind noch kein Evaluationsdatensatz: Scaling-Attack-Bilder müssen reproduzierbar generiert und mit Payload-Text sowie Downscaling-Parametern annotiert werden.

Wenn mehrere Sessions parallel arbeiten, vor Änderungen `git status` und den aktuellen Katalogstand prüfen, einen Datensatz klar übernehmen und Änderungen an gemeinsamen Dateien (`datasets.csv`, `metadata.jsonl`, `AGENTS.md`) koordinieren. Berichte klar, was untersucht, importiert, ausgeschlossen oder noch unbestätigt ist.
