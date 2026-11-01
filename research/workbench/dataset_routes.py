"""Read-only dataset browsing, references and thumbnail HTTP endpoints."""

import threading

from flask import jsonify, request, send_file


def register_routes(app, get_catalog, get_browser):
    """Attach catalog views; model execution stays in the workbench service."""

    @app.get("/api/datasets")
    def dataset_images():
        try:
            offset, limit = (
                int(request.args.get("offset", 0)),
                int(request.args.get("limit", 12)),
            )
            if offset < 0 or not 1 <= limit <= 48:
                raise ValueError("Invalid dataset page.")
            return jsonify(
                get_browser(request.args.get("dataset", "ocr_evaluation")).listing(
                    request.args.get("category", ""),
                    request.args.get("q", ""),
                    offset,
                    limit,
                )
            )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/datasets/<identifier>/reference")
    def dataset_reference(identifier):
        try:
            catalog = get_catalog(request.args.get("dataset", "ocr_evaluation"))
            return jsonify(catalog.reference(identifier))
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    @app.get("/api/datasets/<identifier>/image")
    def dataset_image(identifier):
        try:
            return send_file(
                get_catalog(request.args.get("dataset", "ocr_evaluation")).path(
                    identifier
                ),
                conditional=True,
            )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404

    thumbnail_slots = threading.Semaphore(2)

    @app.get("/api/datasets/<identifier>/thumbnail")
    def dataset_thumbnail(identifier):
        try:
            with thumbnail_slots:
                return send_file(
                    get_browser(
                        request.args.get("dataset", "ocr_evaluation")
                    ).thumbnail(identifier),
                    mimetype="image/jpeg",
                    max_age=3600,
                )
        except (ValueError, OSError) as error:
            return jsonify(error=str(error)), 404
