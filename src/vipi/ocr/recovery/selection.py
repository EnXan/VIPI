"""Choose OCR readings from measured signals and visual review."""

from vipi.cancellation import check_cancelled
from vipi.storage.files import write_json

from .attempts import recognize_plan, recovery_plans
from .decisions import ASSESSMENT_CHOICES, read_choice
from .extended_signals import RECOVERY_PARAMETERS, route_extended


def _correction_plans(original, selected, decider, store, selection, cancel_event):
    """Record independent completeness evidence and derive repair plans."""
    decisions = selection["decisions"]
    check_cancelled(cancel_event)
    store.transition("ocr_assessing", state="selecting", data={"decision": 1})
    record = decider.assess(original, selected, store.directory / "decisions" / "0001")
    check_cancelled(cancel_event)
    assessment = {
        name: read_choice(record["response"], name, choices)
        for name, choices in ASSESSMENT_CHOICES.items()
    }
    selection.update(assessment_status="completed", initial_assessment=assessment)
    decisions.append({"kind": "completeness_and_repair_assessment", **record})
    write_json(store.directory / "decisions.json", decisions)

    repair = assessment["repair"]
    if not selected["text"].strip():
        # Empty OCR never proves that the image contains no readable text.
        selection["repair_override"] = "empty_ocr_requires_contrast_probe"
        repair = "contrast"
    selection["repair_action"] = repair

    if repair == "none":
        if (
            assessment["completeness"] == "complete"
            and assessment["reviewability"] == "sufficient"
        ):
            selection.update(stop_reason="original_ready", review_action="accept")
        elif assessment["completeness"] == "missing_text":
            selection.update(
                stop_reason="visible_text_missing_without_supported_repair",
                review_action="uncertain",
            )
        else:
            selection.update(
                stop_reason="completeness_unjudged", review_action="uncertain"
            )
        return []
    if repair == "uncertain":
        selection.update(stop_reason="repair_uncertain", review_action="uncertain")
        return []

    orientation = "upright"
    if repair in {"orientation", "both"}:
        check_cancelled(cancel_event)
        store.transition(
            "orientation_selecting", state="selecting", data={"decision": 2}
        )
        orientation, record = decider.choose_orientation(
            original, store.directory / "decisions" / "0002"
        )
        check_cancelled(cancel_event)
        decisions.append({"kind": "orientation_selection", **record})
        write_json(store.directory / "decisions.json", decisions)
        selection["orientation"] = orientation

        if orientation == "uncertain":
            if repair == "orientation":
                selection.update(
                    stop_reason="orientation_uncertain", review_action="uncertain"
                )
                return []
            selection["unresolved_repairs"] = ["orientation"]
            repair = "contrast"
        elif repair == "both" and orientation == "upright":
            repair = "contrast"
        elif repair == "orientation" and orientation == "upright":
            selection.update(
                repair_action="none",
                stop_reason="orientation_not_confirmed",
                review_action="uncertain",
            )
            return []

    if repair == "orientation":
        return [{"orientation": orientation, "contrast": "unchanged", "crop": "full"}]
    if repair == "contrast":
        selection["repair_action"] = "contrast"
        return recovery_plans()
    if repair == "both":
        selection["repair_action"] = "both"
        return recovery_plans(orientation)
    raise ValueError(f"Unsupported repair action: {repair}")


def _compare_correction(
    original, selected, candidate, decider, store, attempts, decisions, cancel_event
):
    """Record a correction review, skipping empty or unchanged candidate text."""
    if not candidate["text"].strip() or candidate["text"] == selected["text"]:
        candidate["step"]["review"] = {
            "comparison": "skipped_no_new_text",
            "incumbent": selected["id"],
        }
        write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
        return None
    check_cancelled(cancel_event)
    number = len(decisions) + 1
    store.transition(
        "transformation_deciding",
        state="selecting",
        data={
            "decision": number,
            "incumbent": selected["id"],
            "candidate": candidate["id"],
        },
    )
    record = decider.compare(
        original, selected, candidate, store.directory / "decisions" / f"{number:04d}"
    )
    check_cancelled(cancel_event)
    outcome = read_choice(
        record["response"],
        "comparison",
        ("improved", "equivalent", "worse", "uncertain"),
    )
    review = {
        "incumbent": selected["id"],
        "candidate": candidate["id"],
        "comparison": outcome,
        "decision": number,
    }
    decisions.append({**record, **review})
    candidate["step"]["review"] = review
    write_json(store.directory / "decisions.json", decisions)
    write_json(store.directory / "attempts.json", [a["step"] for a in attempts])
    return outcome


def select_reading(
    original,
    model,
    engine,
    decider,
    store,
    attempts,
    initialization_seconds,
    cancel_event,
):
    """Read the original, then retain the first independently verified correction."""
    selected = recognize_plan(
        original,
        {"orientation": "upright", "contrast": "unchanged", "crop": "full"},
        engine,
        store,
        attempts,
        model=model,
        cancel_event=cancel_event,
        initialization_seconds=initialization_seconds,
    )
    routing = route_extended(
        selected["text"],
        selected["step"]["regions"],
        selected["groups"],
        original,
        RECOVERY_PARAMETERS,
    )
    selection = {
        "stop_reason": "no_verified_improvement",
        "review_action": "uncertain",
        "planned_candidates": 1,
        "assessment_status": "not_required",
        "initial_assessment": None,
        "selection_version": "separate-completeness-repair-v1",
        "routing": routing,
        "resolution_changes": [],
        "decisions": [],
    }
    if routing["route"] == "no_signal":
        selection.update(stop_reason="no_signal", review_action="not_required")
        return selected, selection

    plans = _correction_plans(
        original, selected, decider, store, selection, cancel_event
    )
    selection["planned_candidates"] += len(plans)
    if not plans:
        return selected, selection
    route = selection.get("repair_action", "contrast")
    store.transition(
        "corrections_planned",
        state="transforming",
        total=selection["planned_candidates"],
        data={"route": route},
    )
    for plan in plans:
        candidate = recognize_plan(
            original,
            plan,
            engine,
            store,
            attempts,
            model=model,
            cancel_event=cancel_event,
        )
        outcome = _compare_correction(
            original,
            selected,
            candidate,
            decider,
            store,
            attempts,
            selection["decisions"],
            cancel_event,
        )
        if outcome == "improved":
            selection.update(stop_reason="verified_improvement", review_action="accept")
            return candidate, selection
    return selected, selection
