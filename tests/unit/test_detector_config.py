import os

import pytest

from vipi.config import api_key
from vipi.detection.providers.jev import Jev
from vipi.detection.providers.openai import Decisions


@pytest.fixture
def credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("TYPESAFE_API_KEY", "JEV_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / ".env"


def test_providers_read_dotenv_without_changing_environment(credentials):
    credentials.write_text(
        "export TYPESAFE_API_KEY=\"file-jev\" # comment\nOPENAI_API_KEY='file-openai'\n"
    )
    assert Jev().key == "file-jev"
    assert Decisions().key == "file-openai"
    assert "TYPESAFE_API_KEY" not in os.environ
    assert "OPENAI_API_KEY" not in os.environ


@pytest.mark.parametrize("alias", ["TYPESAFE_API_KEY", "JEV_API_KEY"])
def test_terminal_key_overrides_both_dotenv_aliases(credentials, monkeypatch, alias):
    credentials.write_text(
        "TYPESAFE_API_KEY=file-typesafe\nJEV_API_KEY=file-jev\n"
        "OPENAI_API_KEY=file-openai\n"
    )
    monkeypatch.setenv(alias, "terminal-jev")
    monkeypatch.setenv("OPENAI_API_KEY", "terminal-openai")
    assert Jev().key == "terminal-jev"
    assert Decisions().key == "terminal-openai"


def test_jev_file_alias_is_supported(credentials):
    credentials.write_text("JEV_API_KEY=file-alias\n")
    assert Jev().key == "file-alias"


def test_empty_environment_key_disables_dotenv_fallback(credentials, monkeypatch):
    credentials.write_text("OPENAI_API_KEY=file-openai\n")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert Decisions().key is None


def test_missing_or_empty_dotenv_credentials_stay_unconfigured(credentials):
    assert api_key("OPENAI_API_KEY") is None
    credentials.write_text("OPENAI_API_KEY=\nTYPESAFE_API_KEY\n")
    assert Decisions().key is None
    assert Jev().key is None
