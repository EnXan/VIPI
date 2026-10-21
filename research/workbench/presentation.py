"""Web-only URLs and Server-Sent Events over product progress records."""

import json


def image_links(value, run_id):
    if isinstance(value, list):
        return [image_links(item, run_id) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: image_links(item, run_id) for key, item in value.items()}
    if {"id", "image", "view_id"} <= result.keys():
        result["image_url"] = f"/api/runs/{run_id}/steps/{result['id']}/image"
    return result


def sse_events(store, after=0):
    for event in store.iter_events(after):
        if event is None:
            yield ": keepalive\n\n"
        else:
            run_id = event.get("run_id", store.status.get("run_id"))
            data = json.dumps(image_links(event, run_id), ensure_ascii=False)
            yield f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"
