"""Local models load their weights sequentially (ADR 0086)."""

import importlib.util
import inspect
import os
import sys
from types import SimpleNamespace

import pytest

from vipi import local_decisions
from vipi.detection.providers import wolf_defender
from vipi.weight_loading import ASYNC_LOAD_SWITCH, load_weights_sequentially


class StopBeforeLoading(Exception):
    pass


def stop():
    raise StopBeforeLoading


def test_sequential_loading_is_set_when_unset(monkeypatch):
    monkeypatch.delenv(ASYNC_LOAD_SWITCH, raising=False)
    load_weights_sequentially()
    assert os.environ["HF_DEACTIVATE_ASYNC_LOAD"] == "1"


def test_an_explicit_setting_is_kept(monkeypatch):
    monkeypatch.setenv(ASYNC_LOAD_SWITCH, "0")
    load_weights_sequentially()
    assert os.environ[ASYNC_LOAD_SWITCH] == "0"


def test_decision_models_load_sequentially(monkeypatch):
    monkeypatch.delenv(ASYNC_LOAD_SWITCH, raising=False)
    # A torch stand-in that ends _runtime() before any model loads.
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=stop))
    )
    model = object.__new__(local_decisions.LocalDecisionModel)
    model.name, model.directory = "d1", "unused"
    model.identity, model.runtime = {"revision": "test"}, "d1"
    with pytest.raises(StopBeforeLoading):
        model._runtime()
    assert os.environ[ASYNC_LOAD_SWITCH] == "1"


def test_wolf_defender_loads_sequentially(monkeypatch):
    monkeypatch.delenv(ASYNC_LOAD_SWITCH, raising=False)
    seen = []

    def record_and_stop():
        seen.append(os.environ.get(ASYNC_LOAD_SWITCH))
        stop()

    # quiet_redirects_notice() runs right before torch and transformers import.
    monkeypatch.setattr(wolf_defender, "quiet_redirects_notice", record_and_stop)
    detector = object.__new__(wolf_defender.WolfDefender)
    detector.directory = "unused"
    detector.manifest = {"revision": "test", "files": {}}
    with pytest.raises(StopBeforeLoading):
        detector._runtime()
    assert seen == ["1"]


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="needs detector-local transformers",
)
def test_locked_transformers_still_reads_the_switch():
    from transformers import core_model_loading

    assert f'"{ASYNC_LOAD_SWITCH}"' in inspect.getsource(core_model_loading)
