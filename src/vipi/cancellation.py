"""Cooperative cancellation between OCR and detector operations."""

from concurrent.futures import CancelledError


def check_cancelled(event):
    if event is not None and event.is_set():
        raise CancelledError("Scan cancelled.")
