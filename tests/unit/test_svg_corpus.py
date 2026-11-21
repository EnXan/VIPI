"""Benign SVGs: compatibility and the exact text the detector receives.

B01 covers the repository's own SVGs, B02 minimal look-alikes of common
exporters, and B03 a golden snapshot of their detector text. That snapshot is
the input of the false-positive measurement, so a change must be reviewed.
Regenerate it with `VIPI_UPDATE_GOLDEN=1 uv run pytest tests/unit/test_svg_corpus.py`.
"""

import json
import os
from pathlib import Path
import re

import pytest

from tests.svg_cases import BENIGN, benign_svg
from vipi.svg import read_svg
from vipi.svg.render import render_svg

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/fixtures/svg/benign_detector_text.json"
REPOSITORY_SVGS = sorted(
    path.relative_to(ROOT).as_posix()
    for folder in ("assets", "research/workbench/static")
    for path in (ROOT / folder).rglob("*.svg")
)
# Features of the repository's SVGs as probed on 2026-11-17; all others: none.
REPOSITORY_FEATURES = {
    "assets/motion/vipi-reveal.svg": ("animation",),
    "assets/providers/liquidai.svg": ("embedded_image",),
    "assets/providers/typesafe.svg": ("embedded_image",),
}
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL)


def corpus():
    entries = {path: (ROOT / path).read_bytes() for path in REPOSITORY_SVGS}
    entries.update({case.id: benign_svg(case) for case in BENIGN})
    return entries


@pytest.mark.parametrize("path", REPOSITORY_SVGS)
def test_repository_svgs_parse_and_render(path):
    data = (ROOT / path).read_bytes()
    document = read_svg(data)
    render_svg(document)
    assert document.features == REPOSITORY_FEATURES.get(path, ())
    assert document.removed_references == ()
    for title in TITLE.findall(data.decode()):
        assert title.strip() in document.source_text


@pytest.mark.parametrize("case", BENIGN, ids=lambda case: case.id)
def test_exporter_look_alikes_parse_and_render(case):
    document = read_svg(benign_svg(case))
    rendered = render_svg(document)
    assert rendered.render_size[0] > 0
    assert document.features == case.features
    assert document.removed_references == case.removed
    assert document.invisible_characters == 0


def test_benign_detector_text_matches_the_golden_snapshot():
    actual = {name: read_svg(data).detector_text for name, data in corpus().items()}
    if os.environ.get("VIPI_UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n")
    expected = json.loads(GOLDEN.read_text())
    if not (ROOT / "assets").is_dir():
        # A source distribution ships tests but not the repository's assets.
        expected = {name: text for name, text in expected.items() if name in actual}
    assert actual == expected
