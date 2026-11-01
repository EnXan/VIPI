"""Convert completed OCR results into selection-report fields."""


def ocr_record(result):
    """Keep timing, cost and evaluation fields independent of batch scheduling."""
    evaluation = result.get("evaluation")
    record = dict(
        state="running",
        recognized_text=result.get("text", ""),
        ocr_profile=result.get("ocr_profile"),
        elapsed_seconds=result.get("elapsed_seconds"),
        cost=result.get("cost"),
        inference_seconds=sum(
            step.get("preprocessing", {}).get(
                "runtime_inference_seconds",
                step.get("timing", {}).get("ocr_seconds", 0),
            )
            for step in result.get("variants", [])
        ),
        initialization_seconds=sum(
            step.get("timing", {}).get("engine_acquire_seconds", 0)
            + step.get("preprocessing", {}).get("runtime_initialization_seconds", 0)
            for step in result.get("variants", [])
        ),
    )
    if evaluation:
        record.update(
            valid=evaluation["valid"],
            coverage=evaluation["final"]["coverage"],
            missing=evaluation["final"]["missing"],
            exact_valid=evaluation["final"]["exact"]["valid"],
            exact_coverage=evaluation["final"]["exact"]["coverage"],
            exact_missing=evaluation["final"]["exact"]["missing"],
            group_conflicts=evaluation["final"].get("group_conflicts", []),
            pipeline_coverage=evaluation["detection"]["coverage"],
            final_valid=evaluation["final"]["valid"],
            best_step_id=evaluation["best_step_id"],
            effects=evaluation["effects"],
        )
    if result.get("evaluation_unavailable"):
        record["scoring_unavailable"] = result["evaluation_unavailable"]["reason"]

    return record
