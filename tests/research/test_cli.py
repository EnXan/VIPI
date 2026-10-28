import pytest

from research.workbench.__main__ import main


def test_web_server_keeps_credential_loading_in_shared_resolver(monkeypatch):
    options = []

    class App:
        def run(self, **kwargs):
            options.append(kwargs)

    monkeypatch.setattr(
        "research.workbench.web.create_app", lambda *args, **kwargs: App()
    )
    assert main(["serve"]) == 0
    assert options[0]["load_dotenv"] is False


@pytest.mark.parametrize("workers", [None, "1", "8"])
def test_cli_forwards_workers(monkeypatch, capsys, workers):
    calls = []

    def extract(*args, **kwargs):
        calls.append(kwargs["workers"])
        return {"text": "recognized"}

    monkeypatch.setattr("research.workbench.__main__.extract", extract)
    argv = ["extract", "image.png", "--ocr-profile", "transforms"]
    if workers is not None:
        argv += ["--workers", workers]
    assert main(argv) == 0
    assert calls == [4 if workers is None else int(workers)]
    assert capsys.readouterr().out == "recognized\n"


@pytest.mark.parametrize("workers", ["0", "9", "-1", "1.5", "abc"])
def test_cli_rejects_invalid_workers(capsys, workers):
    with pytest.raises(SystemExit) as error:
        main(["extract", "image.png", "--workers", workers])
    assert error.value.code == 2
    assert "between 1 and 8" in capsys.readouterr().err


def test_cli_evaluation_uses_dataset_reference(dataset_repository, monkeypatch):
    monkeypatch.chdir(dataset_repository)
    references = []

    def extract(*args, **kwargs):
        references.append(kwargs["reference"])
        return {"text": "recognized"}

    monkeypatch.setattr("research.workbench.__main__.extract", extract)
    assert main(["extract", "research/ocr_eval/images/0.png", "--evaluate"]) == 0
    assert references[0]["text"] == "Required"


@pytest.mark.parametrize("backend", ["cpu", "coreml", "cuda"])
def test_cli_forwards_hardware_backend(monkeypatch, backend):
    calls = []

    def extract(*args, **kwargs):
        calls.append(kwargs["backend"])
        return {"text": "recognized"}

    monkeypatch.setattr("research.workbench.__main__.extract", extract)
    assert main(["extract", "image.png", "--backend", backend]) == 0
    assert calls == [backend]


@pytest.mark.parametrize("command", ["extract", "prepare-models"])
def test_cli_excludes_removed_models(capsys, command):
    with pytest.raises(SystemExit) as error:
        main([command, "--help"])

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    for removed in ("ppocr-v5", "florence", "surya", "gpt-6-sol"):
        assert removed not in help_text
