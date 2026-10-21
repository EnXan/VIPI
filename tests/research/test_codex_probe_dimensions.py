"""Regression checks against raster sizes reported by the actual image tool."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "research/experiments/anamorpher/codex_preprocessing_probe.py"
)
spec = importlib.util.spec_from_file_location("codex_probe_dimensions", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize(
    "source,dimension,patches,expected",
    [
        ((2048, 1536), 2048, 2500, (1824, 1368)),
        ((3440, 3072), 2048, 2500, (1664, 1486)),
        ((3440, 3072), 6000, 10000, (3360, 3000)),
        ((1280, 960), 2048, 2500, (1280, 960)),
    ],
)
def test_matches_reported_raster_dimensions(source, dimension, patches, expected):
    actual = probe.limited_size(source, dimension, patches)
    assert actual == expected
    assert probe.fits(*actual, dimension, patches)


def test_rejects_empty_dimensions():
    with pytest.raises(ValueError):
        probe.limited_size((0, 100), 2048, 2500)
