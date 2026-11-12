"""Judge whether readable image text is missing from the final OCR text."""

from concurrent.futures import CancelledError

from vipi.cancellation import check_cancelled
from vipi.storage.files import write_json

from .decisions import ASSESSMENT_CHOICES, read_choice


def reading(assessment):
    """Map a completeness assessment to ``ocr_incomplete`` (True, False or None)."""
    if assessment["completeness"] == "missing_text":
        return True
    if (
        assessment["completeness"] == "complete"
        and assessment["reviewability"] == "sufficient"
    ):
        return False
    return None


def judge_final_text(
    original, text, groups, first_text, selection, decider, store, cancel_event
):
    """Return ``ocr_incomplete`` for the final text and record where it came from.

    The assessment of the first reading is reused when the final text is that
    reading. A different final text is assessed again. Without any review the
    value is ``None`` and no call is made.
    """
    initial = selection.get("initial_assessment")
    if text == first_text:
        if initial is None:
            selection.update(ocr_incomplete=None, ocr_incomplete_source="not_reviewed")
        else:
            selection.update(
                ocr_incomplete=reading(initial), ocr_incomplete_source="reused"
            )
        return selection["ocr_incomplete"]
    decisions = selection["decisions"]
    number = len(decisions) + 1
    try:
        check_cancelled(cancel_event)
        record = decider.assess(
            original,
            {"text": text, "groups": groups},
            store.directory / "decisions" / f"{number:04d}",
        )
        check_cancelled(cancel_event)
        assessment = {
            name: read_choice(record["response"], name, choices)
            for name, choices in ASSESSMENT_CHOICES.items()
        }
    except CancelledError:
        raise
    except Exception as error:
        selection.update(
            ocr_incomplete=None,
            ocr_incomplete_source="error",
            ocr_incomplete_error=str(error) or type(error).__name__,
        )
        return None
    decisions.append({"kind": "final_completeness_assessment", **record})
    write_json(store.directory / "decisions.json", decisions)
    selection.update(
        ocr_incomplete=reading(assessment),
        ocr_incomplete_source="asked",
        final_assessment=assessment,
    )
    return selection["ocr_incomplete"]
