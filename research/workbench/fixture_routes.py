"""HTTP routes for the Editor page: encode hidden layers and read them back."""

import base64
import json
import re

from flask import jsonify, request

from research.curation.vocabulary import seed
from research.fixtures import (
    alpha,
    codes,
    heal,
    metadata,
    scaling,
    stego,
    svg,
    text_boxes,
)
from research.fixtures.encode import FORMATS, LABELS, encode, fixture

UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value):
    name = UNSAFE_NAME.sub("-", str(value or "")).strip(".-")
    return name or "fixture"


def _b64(data):
    return base64.b64encode(data).decode() if data else None


def register(app):
    @app.post("/api/fixtures/code")
    def code_image():
        data = request.get_json(silent=True) or {}
        try:
            png, name = codes.module_png(data.get("format"), data.get("text"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(image=_b64(png), name=name)

    @app.post("/api/fixtures/heal")
    def heal_image():
        image, mask = request.files.get("image"), request.files.get("mask")
        if image is None or mask is None:
            return jsonify(error="The image and the painted mask are needed."), 400
        try:
            return jsonify(image=_b64(heal.heal(image.read(), mask.read())))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post("/api/fixtures/text-lines")
    def text_lines():
        image = request.files.get("image")
        if image is None:
            return jsonify(error="The background image is needed."), 400
        try:
            return jsonify(available=True, lines=text_boxes.find_lines(image.read()))
        except text_boxes.Unavailable as error:
            return jsonify(available=False, lines=[], hint=str(error))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/fixtures/options")
    def fixture_options():
        titles = metadata.field_titles()
        return jsonify(
            formats=list(FORMATS),
            labels=list(LABELS),
            scaling=scaling.methods(),
            codes=codes.options(),
            alpha_modes=[
                {"id": key, "title": title} for key, title in alpha.MODES.items()
            ],
            stego=[{"id": key, "title": title} for key, title in stego.KINDS.items()],
            svg_placements=[
                {"id": key, "title": title} for key, title in svg.PLACEMENTS.items()
            ],
            obfuscation=seed()["fields"]["obfuscation"]["values"],
            containers=[
                {
                    "id": container,
                    "title": spec["title"],
                    "formats": list(spec["formats"]),
                    "note": spec["note"],
                    "fields": [
                        {
                            "id": field,
                            "label": label,
                            "title": titles.get(container, {}).get(field, field),
                        }
                        for field, label in spec["fields"].items()
                    ],
                }
                for container, spec in metadata.CONTAINERS.items()
            ],
        )

    @app.post("/api/fixtures/encode")
    def encode_fixture():
        upload = request.files.get("raster")
        if upload is None:
            return jsonify(error="The composed image is missing."), 400
        try:
            recipe = json.loads(request.form.get("recipe") or "")
        except json.JSONDecodeError:
            return jsonify(error="The recipe is not valid JSON."), 400
        if not isinstance(recipe, dict):
            return jsonify(error="The recipe must be an object."), 400
        name = safe_name(request.form.get("name"))
        try:
            encoded = encode(upload.read(), recipe)
            record = fixture(encoded, recipe, name) if recipe.get("label") else None
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(
            name=name,
            image=base64.b64encode(encoded.data).decode(),
            mime=encoded.mime,
            extension=encoded.extension,
            sha256=encoded.sha256,
            bytes=len(encoded.data),
            layers=list(encoded.layers),
            readings=encoded.readings,
            lsb_statistics=encoded.lsb_statistics,
            fixture=record,
            preview=_b64(encoded.preview),
            display=_b64(encoded.display),
        )
