from pathlib import Path

import pytest

from vipi.inputs import select_images
from vipi.inputs.exclusions import ExclusionRules


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image fixture")
    return path


def relative_image_paths(selection, root):
    return {
        image.path.relative_to(root).as_posix() for image in selection.images
    }


def test_rules_exclude_directories_and_types_then_reinclude_a_nested_image(
    tmp_path,
):
    (tmp_path / ".vipiignore").write_text(
        "generated/\n*.webp\n!generated/reviewed.webp\nprivate/\n",
        encoding="utf-8",
    )
    for relative_path in (
        "keep.png",
        "generated/skip.png",
        "generated/reviewed.webp",
        "photos/cover.webp",
        "private/secret.png",
    ):
        touch(tmp_path / relative_path)

    selection = select_images([tmp_path])

    assert relative_image_paths(selection, tmp_path) == {
        "keep.png",
        "generated/reviewed.webp",
    }
    skipped = {
        Path(item["path"]).relative_to(tmp_path).as_posix(): item
        for item in selection.skipped
    }
    assert skipped["generated/skip.png"] == {
        "path": str(tmp_path / "generated/skip.png"),
        "reason": "excluded_by_user",
        "rule": "generated/",
        "source": str(tmp_path / ".vipiignore"),
        "line": 1,
    }
    assert skipped["photos/cover.webp"]["rule"] == "*.webp"
    assert skipped["photos/cover.webp"]["line"] == 2
    assert skipped["private"] == {
        "path": str(tmp_path / "private"),
        "reason": "excluded_by_user",
        "rule": "private/",
        "source": str(tmp_path / ".vipiignore"),
        "directory": True,
        "line": 4,
    }


def test_command_line_rules_follow_file_rules_and_report_argument_number(tmp_path):
    (tmp_path / ".vipiignore").write_text("assets/\n", encoding="utf-8")
    keep = touch(tmp_path / "assets/keep.png")
    touch(tmp_path / "assets/skip.png")

    included = select_images([tmp_path], exclude_patterns=["!assets/keep.png"])
    assert [image.path for image in included.images] == [keep]

    excluded = select_images(
        [tmp_path],
        exclude_patterns=["!assets/keep.png", "assets/keep.png"],
    )
    assert not excluded.images
    keep_skip = next(
        item for item in excluded.skipped if item["path"] == str(keep)
    )
    assert keep_skip["rule"] == "assets/keep.png"
    assert keep_skip["source"] == "command line --exclude"
    assert keep_skip["argument"] == 2


def test_path_globs_support_recursive_and_root_relative_matching(tmp_path):
    rules = ExclusionRules(
        tmp_path,
        ["docs/**/logo.png", "/assets/logo.png"],
    )

    assert rules.decision(tmp_path / "docs/logo.png")[1].raw == "docs/**/logo.png"
    assert (
        rules.decision(tmp_path / "docs/nested/deep/logo.png")[1].raw
        == "docs/**/logo.png"
    )
    assert rules.decision(tmp_path / "assets/logo.png")[1].raw == "/assets/logo.png"
    assert rules.decision(tmp_path / "other/assets/logo.png") is None


@pytest.mark.parametrize("pattern", ["", "!", "../outside.png", "images//logo.png"])
def test_invalid_exclusion_patterns_fail_before_selection(tmp_path, pattern):
    touch(tmp_path / "image.png")

    with pytest.raises(ValueError, match="Invalid exclusion rule|non-empty rule"):
        select_images([tmp_path], exclude_patterns=[pattern])
