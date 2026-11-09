"""Generators work on any platform, describe their templates and can preview."""

import json

from research.curation import render, templates
from research.curation.__main__ import main
from research.curation.screen_templates import TEMPLATES


def test_fonts_prefer_macos_then_windows_then_linux(tmp_path, monkeypatch):
    linux = tmp_path / "linux/truetype/liberation"
    linux.mkdir(parents=True)
    (linux / "LiberationSerif-Regular.ttf").write_bytes(b"")
    monkeypatch.setattr(render, "SUPPLEMENTAL", tmp_path / "mac")
    monkeypatch.setattr(render, "WINDOWS_FONTS", tmp_path / "windows")
    monkeypatch.setattr(render, "LINUX_FONTS", tmp_path / "linux")
    paths = render.font_paths("Times New Roman", False)
    assert paths == [
        tmp_path / "mac/Times New Roman.ttf",
        tmp_path / "windows/times.ttf",
        linux / "LiberationSerif-Regular.ttf",
    ]
    assert render.font_paths("Tahoma", True) == []


def test_bundled_font_keeps_rendering_without_system_fonts(tmp_path, monkeypatch):
    for name in ("SUPPLEMENTAL", "WINDOWS_FONTS", "LINUX_FONTS"):
        monkeypatch.setattr(render, name, tmp_path / name)
    assert render.available(False) == ["Arial"]
    assert render.available(True) == []
    assert render.font("Arial", False, 20).path.endswith("Geist.ttf")


def test_every_template_is_described_with_its_fields_and_examples():
    described = {item["template"]: item for item in templates.describe()}
    assert set(described) == set(TEMPLATES)
    assert described["messenger"]["fields"] == ["others", "title"]
    # helper functions that receive the item are followed
    assert "modal_title" in described["product_desktop"]["fields"]
    assert described["messenger"]["examples"]
    assert all("text" not in item["fields"] for item in described.values())


def test_templates_command_lists_and_explains(capsys):
    assert main(["templates"]) == 0
    assert "messenger" in capsys.readouterr().out
    assert main(["templates", "messenger"]) == 0
    output = capsys.readouterr().out
    assert "fields read by the template: others, title" in output
    assert '"template": "messenger"' in output
    assert main(["templates", "nope"]) == 2


def test_preview_renders_without_changing_the_dataset(draft_dir, tmp_path, capsys):
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "label": "benign",
                "content": "text_image",
                "items": [
                    {"kind": "test", "text": "Lunch is at noon.", "obfuscation": []}
                ],
            }
        )
    )
    before = (draft_dir / "catalog.json").read_text()
    preview = tmp_path / "preview"
    assert (
        main(
            ["generate", str(spec), "--dir", str(draft_dir), "--preview", str(preview)]
        )
        == 0
    )
    assert len(list((preview / "images").glob("*.png"))) == 1
    assert (draft_dir / "catalog.json").read_text() == before
    assert "the dataset is unchanged" in capsys.readouterr().out


def test_starter_spec_is_valid_and_uses_known_templates():
    spec = json.loads(
        (templates.SPECS.parent / "examples/starter.json").read_text(encoding="utf-8")
    )
    assert spec["label"] in {"benign", "injection", "jailbreak"}
    assert all(item.get("template", "messenger") in TEMPLATES for item in spec["items"])
