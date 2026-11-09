"""HTTP routes for contributing on the Dataset page: add images, submit changes."""

from pathlib import Path
from tempfile import TemporaryDirectory

from flask import jsonify, request
from werkzeug.utils import secure_filename

from research.curation import contribute

SOURCE_FIELDS = ("dataset", "license", "provenance", "repository")
LOGIN_HELP = (
    "Sign in to Hugging Face once in a terminal: uv run hf auth login "
    "(the token stays on this computer), then try again."
)


def counts(data):
    return {name: len(keys) for name, keys in data["changes"].items()}


def plan(data):
    """What the page shows about a submission, without the full catalog."""
    return {
        "changes": data["changes"],
        "counts": counts(data),
        "conflicts": data["conflicts"],
        "vocabulary_changed": data["vocabulary_changed"],
        "main_revision": data["main_revision"],
        "pull_request": data.get("pull_request"),
    }


def remote_failure(error):
    if "EntryNotFound" in type(error).__name__:
        message = (
            "The dataset on Hugging Face has no catalog.json on main yet, so "
            "there is nothing to apply your changes to. Submitting works once "
            "the dataset pull request that introduces catalog.json is merged."
        )
    else:
        message = (
            "The dataset on Hugging Face could not be read "
            f"({type(error).__name__}). Check the network connection and try again."
        )
    return jsonify(error=message), 503


def register(app, store):
    @app.post("/api/curation/images")
    def curation_add_images():
        files = [item for item in request.files.getlist("images") if item.filename]
        if not files:
            return jsonify(error="Choose at least one image."), 400
        form = request.form
        source = {key: form.get(key, "").strip() or None for key in SOURCE_FIELDS}
        with TemporaryDirectory() as folder:
            paths = []
            for number, upload in enumerate(files):
                name = secure_filename(upload.filename) or f"image{number}"
                path = Path(folder) / str(number) / name
                path.parent.mkdir()
                upload.save(path)
                paths.append(path)
            try:
                with store.lock:
                    added, skipped = contribute.add_images(
                        paths,
                        store.directory,
                        label=form.get("label", ""),
                        content=form.get("content", ""),
                        source=source,
                    )
            except ValueError as error:
                return jsonify(error=str(error).replace(f"{folder}/", "")), 400
        names = {str(path): path.name for path in paths}
        return jsonify(
            added=[entry["id"] for entry in added],
            skipped=[
                {"file": names[path], "id": identifier} for path, identifier in skipped
            ],
        )

    def submission(message, dry_run):
        try:
            data = contribute.upload(store.directory, message, dry_run=dry_run)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except (OSError, KeyError) as error:
            return remote_failure(error)
        return jsonify(plan(data))

    @app.get("/api/curation/submission")
    def curation_submission_plan():
        return submission("", dry_run=True)

    @app.post("/api/curation/submission")
    def curation_submit():
        data = request.get_json(silent=True) or {}
        if data.get("confirm") is not True:
            return jsonify(error="Confirm the submission first."), 400
        if not contribute.signed_in():
            return jsonify(error=LOGIN_HELP), 401
        message = str(data.get("message") or "").strip() or "Add evaluation images"
        return submission(message, dry_run=False)
