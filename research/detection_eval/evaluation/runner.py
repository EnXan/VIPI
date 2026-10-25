"""Score one scan without context against every reviewed case of an image."""

from .metrics import evaluate


def run_cases(run_id, cases, options, service, *, cancel_event=None):
    # Catalog context, labels and payload transcripts belong only to ground truth.
    selected = {**options, "context": {}}
    store = service.prepare(run_id, selected, cancel_event=cancel_event)
    error = None
    try:
        result = service.enqueue(store, selected).result()
        if store.status["state"] == "cancelled":
            return [
                {"check_id": store.id, "state": "cancelled", "outcome": "cancelled"}
                for case in cases
            ]
        if result is None:
            error = store.status.get("error", "Detector check failed.")
    except Exception as failure:
        result, error = None, str(failure)
    return [
        {"check_id": store.id, **evaluate(case, result, error=error)} for case in cases
    ]
