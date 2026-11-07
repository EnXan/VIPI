"""Saved-run views, downloads, event streaming and cancellation endpoints."""

import re

from flask import Response, jsonify, request, send_file

from vipi.storage.ocr import RunStore
from .batch import Batch
from .presentation import image_links, sse_events


def register_routes(app, root, jobs, batches, run_cancellations, detection):
    """Attach run/batch views to the existing workbench job registries."""

    def get_batch(identifier):
        if identifier not in batches:
            batches[identifier] = Batch.restore(root, identifier)
        return batches[identifier]

    @app.get("/api/batches/<identifier>")
    def batch_status(identifier):
        try:
            return jsonify(get_batch(identifier).snapshot())
        except (ValueError, OSError):
            return jsonify(error="Selection run not found."), 404

    @app.get("/api/batches/<identifier>/report.json")
    def batch_report(identifier):
        try:
            batch = get_batch(identifier)
            return send_file(
                batch.directory / "report.json",
                as_attachment=True,
                download_name=f"vipi-selection-{identifier}.json",
            )
        except (ValueError, OSError):
            return jsonify(error="Selection run not found."), 404

    @app.get("/api/batches/<identifier>/input")
    def batch_input(identifier):
        try:
            batch = get_batch(identifier)
            return send_file(
                batch.directory / "input.png", mimetype="image/png", conditional=True
            )
        except (ValueError, OSError):
            return jsonify(error="Uploaded image not found."), 404

    @app.post("/api/batches/<identifier>/cancel")
    def cancel_batch(identifier):
        try:
            batch = get_batch(identifier)
            requested = batch.cancel()
            if requested and batch.status.get("current_run_id"):
                detection.cancel(batch.status["current_run_id"])
            return jsonify(batch.snapshot()), 202 if requested else 200
        except (ValueError, OSError):
            return jsonify(error="Selection run not found."), 404

    def get_job(run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            return None
        if run_id not in jobs and (root / run_id / "status.json").is_file():
            jobs[run_id] = RunStore.restore(root / run_id)
        return jobs.get(run_id)

    @app.get("/api/runs/<run_id>")
    def snapshot(run_id):
        job = get_job(run_id)
        return (
            jsonify(image_links(job.snapshot(), run_id))
            if job
            else (jsonify(error="Run not found."), 404)
        )

    @app.post("/api/runs/<run_id>/cancel")
    def cancel_run(run_id):
        job = get_job(run_id)
        if job is None:
            return jsonify(error="Run not found."), 404
        # A batch owns its current OCR run and any following detector work.
        for batch in list(batches.values()):
            if batch.status.get("current_run_id") == run_id and batch.status[
                "state"
            ] not in {"completed", "failed", "cancelled"}:
                batch.cancel()
                detection.cancel(run_id)
                return jsonify(cancel_requested=True), 202
        requested = detection.cancel(run_id)
        event = run_cancellations.get(run_id)
        if event is not None:
            event.set()
            requested = True
            with job.condition:
                if job.status["state"] not in {
                    "completed",
                    "failed",
                    "cancelled",
                } and not job.status.get("cancel_requested"):
                    job.transition("cancellation_requested", cancel_requested=True)
        return jsonify(cancel_requested=requested), 202 if requested else 200

    @app.get("/api/runs/<run_id>/events")
    def events(run_id):
        job = get_job(run_id)
        if job is None:
            return jsonify(error="Run not found."), 404
        try:
            after = int(
                request.headers.get("Last-Event-ID", request.args.get("after", 0))
            )
            if after < 0 or after > len(job.events):
                raise ValueError()
        except ValueError:
            return jsonify(error="Invalid event cursor."), 400
        return Response(
            sse_events(job, after),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/<run_id>/input")
    def original_image(run_id):
        job = get_job(run_id)
        if job is None:
            return jsonify(error="Image not found."), 404
        path = job.directory / "input.png"
        # Older runs saved only transformed images; the unchanged original is equivalent.
        if not path.is_file():
            original = next(
                (
                    step
                    for step in job.snapshot()["variants"]
                    if step.get("view_id") == "original"
                    and step.get("filter") == "unchanged"
                ),
                None,
            )
            if original:
                path = job.directory / "images" / f"{original['id']}.png"
        if not path.is_file():
            return jsonify(error="Image not found."), 404
        return send_file(path, mimetype="image/png", conditional=True)

    @app.get("/api/runs/<run_id>/steps/<step_id>/image")
    def step_image(run_id, step_id):
        job = get_job(run_id)
        if job is None or not re.fullmatch(r"\d{4,6}", step_id):
            return jsonify(error="Image not found."), 404
        path = job.directory / "images" / f"{step_id}.png"
        if not path.is_file():
            return jsonify(error="Image not found."), 404
        return send_file(path, mimetype="image/png", conditional=True)

    @app.get("/api/runs/<run_id>/result.<extension>")
    def download(run_id, extension):
        job = get_job(run_id)
        if job is None or extension not in {"txt", "json"}:
            return jsonify(error="Result not found."), 404
        if job.status["state"] != "completed":
            return jsonify(error="The pipeline has no final result yet."), 409
        return send_file(
            job.directory / f"result.{extension}",
            as_attachment=True,
            download_name=f"vipi-{run_id}.{extension}",
        )
