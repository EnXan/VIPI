"""L1: every SVG technique through read_svg and render_svg, without models."""

import io

import pytest
from PIL import Image

from tests.svg_cases import (
    BLOCKED,
    CASES,
    COVERED,
    ERROR,
    INCOMPLETE,
    KNOWN_GAP,
    OCR,
    PAYLOAD,
    Assets,
)
from vipi.svg import read_svg
from vipi.svg.render import render_svg


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    return Assets.create(tmp_path_factory.mktemp("svg-assets"))


def raster(data):
    rendered = render_svg(read_svg(data))
    return Image.open(io.BytesIO(rendered.png)).convert("RGB")


def test_case_ids_are_unique_and_outcomes_consistent():
    assert len({case.id for case in CASES}) == len(CASES)
    for case in CASES:
        if case.outcome == COVERED:
            assert case.in_source, case.id
        if case.outcome == OCR:
            assert not case.in_source and case.drawn, case.id
        if case.outcome == INCOMPLETE:
            assert "embedded_font" in case.features and not case.in_source, case.id
        if case.outcome == KNOWN_GAP:
            assert not case.in_source and not case.drawn, case.id
        if case.outcome == BLOCKED:
            assert case.render_blank or case.removed, case.id
        assert (case.outcome == ERROR) == (case.error is not None), case.id
        assert case.sources, case.id


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_case(case, assets):
    data = case.svg(PAYLOAD, assets)
    if case.outcome == ERROR:
        with pytest.raises(ValueError, match=case.error):
            read_svg(data)
        return
    document = read_svg(data)
    assert (PAYLOAD in document.detector_text) == case.in_source
    assert document.features == tuple(sorted(case.features))
    assert document.removed_references == tuple(
        assets.format(item) for item in case.removed
    )
    for removed in document.removed_references:
        assert removed not in document.render_markup
    if case.drawn is not None:
        drawn = raster(data).tobytes() != raster(case.svg("", assets)).tobytes()
        assert drawn == case.drawn
    if case.render_blank:
        assert raster(data).getextrema() == ((255, 255),) * 3
