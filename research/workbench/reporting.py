"""Shape OCR result records and summarize workbench batches."""

import math
from statistics import mean, median


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


def performance_summary(items):
    """Summarize completed image time, validity, and known API fees."""
    done = [
        item
        for item in items
        if item["state"] in {"completed", "failed"}
        or (item["state"] == "cancelled" and item.get("run_id"))
    ]
    times = sorted(
        item["elapsed_seconds"]
        for item in done
        if isinstance(item.get("elapsed_seconds"), (int, float))
    )
    costs = [item.get("cost") or {} for item in done]
    amounts = [
        cost["estimated_usd"]
        for cost in costs
        if isinstance(cost.get("estimated_usd"), (int, float))
    ]
    unknown = len(done) - len(amounts)
    subtotal = sum(amounts)
    complete = subtotal if done and not unknown else None
    valid = sum(item.get("valid") is True for item in done)
    return {
        "measured_images": len(times),
        "total_seconds": sum(times),
        "mean_seconds": mean(times) if times else None,
        "median_seconds": median(times) if times else None,
        "initialization_seconds": sum(
            item.get("initialization_seconds", 0) for item in done
        ),
        "inference_seconds": sum(item.get("inference_seconds", 0) for item in done),
        "p95_seconds": times[max(0, math.ceil(len(times) * 0.95) - 1)]
        if times
        else None,
        "known_estimated_api_cost_usd": subtotal,
        "estimated_api_cost_usd": complete,
        "cost_unknown_images": unknown,
        "estimated_api_cost_per_image_usd": complete / len(done)
        if complete is not None
        else None,
        "estimated_api_cost_per_pass_usd": complete / valid
        if complete is not None and valid
        else None,
    }
