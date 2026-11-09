"""HTTP routes for the Dataset page: browse and label entries."""

from io import BytesIO

from flask import jsonify, request, send_file
from PIL import Image, ImageOps

from research.curation import contribute, schema
from research.curation.store import DraftMissing
from research.curation.vocabulary import FIELDS

from . import contribute_routes


def thumbnail_bytes(path):
    """Render a 320×180 JPEG preview on white, honoring EXIF orientation."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((320, 180))
        rgba = image.convert("RGBA")
        image = Image.alpha_composite(
            Image.new("RGBA", image.size, "white"), rgba
        ).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    buffer.seek(0)
    return buffer


def register_routes(app, store, pinned_catalog=None):
    """``pinned_catalog`` returns the downloaded revision's catalog; by default
    it is read from the Hugging Face cache (network on first use)."""
    contribute_routes.register(app, store)
    pinned = {}

    def downloaded():
        if "catalog" not in pinned:
            if pinned_catalog is not None:
                pinned["catalog"] = pinned_catalog()
            else:
                _, revision = contribute.pinned_dataset()
                pinned["catalog"] = contribute.remote_files(revision)[0]
        return pinned["catalog"]

    def failure(error, status=400):
        if isinstance(error, DraftMissing):
            return jsonify(error=str(error)), 409
        if isinstance(error, KeyError):
            return jsonify(error="Entry not found."), 404
        return jsonify(error=str(error)), status

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Send a JSON object.")
        return data

    @app.get("/api/curation")
    def curation_status():
        status = store.status()
        if status["available"]:
            _, vocabulary = store.load()
            status["vocabulary"] = vocabulary
            status["fields"] = list(FIELDS)
        return jsonify(status)

    @app.get("/api/curation/entries")
    def curation_entries():
        try:
            only = None
            if request.args.get("changed") == "1":
                try:
                    only = store.changed_ids(downloaded())
                except (OSError, ValueError, KeyError) as error:
                    return failure(
                        ValueError(
                            "Your changes are found by comparing with the "
                            "downloaded revision on Hugging Face, which could "
                            f"not be read ({type(error).__name__}). Check the "
                            "network connection once."
                        ),
                        503,
                    )
            return jsonify(
                store.listing(
                    request.args.get("status", "all"),
                    request.args.get("field", ""),
                    request.args.get("value", ""),
                    request.args.get("source", ""),
                    request.args.get("q", "").strip(),
                    request.args.get("group") == "1",
                    only,
                )
            )
        except (ValueError, DraftMissing) as error:
            return failure(error)

    @app.get("/api/curation/balance")
    def curation_balance():
        try:
            catalog, vocabulary = store.load()
        except DraftMissing as error:
            return failure(error)
        return jsonify(schema.summary(catalog, vocabulary)["balance"])

    @app.get("/api/curation/entries/<identifier>")
    def curation_entry(identifier):
        try:
            return jsonify(store.entry(identifier))
        except (KeyError, DraftMissing) as error:
            return failure(error)

    @app.post("/api/curation/entries/<identifier>")
    def curation_update(identifier):
        try:
            return jsonify(store.update(identifier, body()))
        except (KeyError, ValueError) as error:
            return failure(error)

    @app.get("/api/curation/entries/<identifier>/image")
    def curation_image(identifier):
        try:
            return send_file(store.image_path(identifier), conditional=True)
        except (KeyError, ValueError, OSError):
            return jsonify(error="Image not found."), 404

    @app.get("/api/curation/entries/<identifier>/thumbnail")
    def curation_thumbnail(identifier):
        try:
            return send_file(
                thumbnail_bytes(store.image_path(identifier)),
                mimetype="image/jpeg",
                max_age=3600,
            )
        except (KeyError, ValueError, OSError):
            return jsonify(error="Thumbnail not found."), 404

    @app.post("/api/curation/vocabulary/<field>")
    def curation_add_value(field):
        try:
            data = body()
            return jsonify(
                store.add_value(
                    field,
                    str(data.get("value", "")),
                    str(data.get("description", "")),
                    bool(data.get("confirm")),
                )
            )
        except (ValueError, DraftMissing) as error:
            return failure(error)

    @app.post("/api/curation/vocabulary/<field>/<value>/rename")
    def curation_rename_value(field, value):
        try:
            return jsonify(store.rename_value(field, value, str(body().get("to", ""))))
        except (ValueError, DraftMissing) as error:
            return failure(error)

    @app.post("/api/curation/vocabulary/<field>/<value>/remove")
    def curation_remove_value(field, value):
        try:
            return jsonify(store.remove_value(field, value))
        except (ValueError, DraftMissing) as error:
            return failure(error)
