from research.ocr_eval.experiments.alternate_evidence import separate_readings


def test_distinct_readings_keep_provenance_without_concatenation():
    values = separate_readings(
        "original", [{"text": "alternate", "source": "upscaled", "box": [0, 0, 10, 10]}]
    )
    assert [r["text"] for r in values] == ["original", "alternate"]
    assert values[1]["sources"][0]["box"] == [0, 0, 10, 10]


def test_identical_readings_are_not_repeated_but_keep_both_sources():
    values = separate_readings("same", [{"text": "same", "source": "crop"}])
    assert len(values) == 1
    assert [source["kind"] for source in values[0]["sources"]] == [
        "selected_ocr",
        "crop",
    ]
