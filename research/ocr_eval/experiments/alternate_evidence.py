"""Experimental provenance-bearing alternatives for downstream evaluation."""

from vipi.detection.evidence import digest


def separate_readings(primary, alternatives):
    """Keep distinct OCR readings separate and preserve their provenance."""
    readings = []
    by_text = {}
    for item in [{"text": primary, "source": "selected_ocr"}, *alternatives]:
        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            continue
        source = {"kind": item["source"], "id": item.get("id", item["source"])}
        if item.get("box") is not None:
            source["box"] = item["box"]
        if text in by_text:
            by_text[text]["sources"].append(source)
            continue
        reading = {"id": digest(text), "text": text, "sources": [source]}
        readings.append(reading)
        by_text[text] = reading
    return readings
