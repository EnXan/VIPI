"""Small JSON transport with bounded retries and no credential-bearing errors."""

import json
import time
import urllib.error
import urllib.request


class RequestFailure(RuntimeError):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = attempts


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def post_json(url, key, body, *, timeout=30, attempts=3, sleep=time.sleep):
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "VIPI-Detector/0.1",
        },
    )
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(1, attempts + 1):
        delay = min(2 ** (attempt - 1), 4)
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = json.load(response)
            if not isinstance(raw, dict):
                raise ValueError()
            return raw, {"attempts": attempt, "cost_uncertain": attempt > 1}
        except urllib.error.HTTPError as error:
            retry = error.code == 429 or 500 <= error.code < 600
            message = f"Provider HTTP {error.code}."
            header = error.headers.get("Retry-After", "") if error.headers else ""
            if header.isdigit():
                delay = min(int(header), 4)
        except (urllib.error.URLError, TimeoutError, OSError):
            retry, message = True, "Provider connection failed or timed out."
        except (ValueError, UnicodeError):
            retry, message = False, "Provider returned invalid JSON."
        if not retry or attempt == attempts:
            raise RequestFailure(message, attempt)
        sleep(delay)
