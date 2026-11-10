"""The CLI references document every subcommand and option the parsers define."""

import argparse
import importlib
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
REFERENCES = {
    "docs/cli.md": ["vipi.cli"],
    "docs/research-cli.md": [
        "research.download",
        "research.curation.__main__",
        "research.workbench.__main__",
        "research.evaluate.__main__",
        "research.ocr_eval.benchmark",
        "research.ocr_eval.benchmark_report",
    ],
}


def documented_words(text):
    """Every word written as code: inline spans and fenced command blocks."""
    spans = re.findall(r"`+([^`]+)`+", text)
    return {word for span in spans for word in re.split(r"[\s|\[\],=]+", span) if word}


def commands_and_options(parser):
    """Subcommand names and option strings of a parser and its subparsers."""
    names = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                names.add(name)
                names |= commands_and_options(subparser)
        elif not isinstance(action, argparse._HelpAction):
            names.update(
                option for option in action.option_strings if option.startswith("--")
            )
    return names


@pytest.mark.parametrize(
    ("reference", "module"),
    [
        (reference, module)
        for reference, modules in REFERENCES.items()
        for module in modules
    ],
)
def test_reference_lists_every_subcommand_and_option(reference, module):
    words = documented_words((ROOT / reference).read_text(encoding="utf-8"))
    parser = importlib.import_module(module).build_parser()
    missing = sorted(commands_and_options(parser) - words)
    assert not missing, f"{reference} does not document {missing} from {module}"
