"""Shared concurrency limits for the pipeline, CLI and web."""

DEFAULT_WORKERS = 4
MAX_WORKERS = 8


def worker_count(value):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 1 <= value <= MAX_WORKERS:
        raise ValueError(f"Workers must be an integer between 1 and {MAX_WORKERS}.")
    return value
