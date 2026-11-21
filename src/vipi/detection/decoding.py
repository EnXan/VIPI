"""Recover base64 plaintext from OCR text for an extra detector check (ADR 0079).

OCR damages encoded strings: it swaps look-alike glyphs (z/Z, l/I, 0/O, ...)
and drops or inserts single characters. A swapped character corrupts three
bytes; a dropped one shifts every following byte. ``repair`` tries the
look-alike variants of each 4-character group and allows a skipped or missing
character, keeping the reading whose bytes look most like text.
"""

import base64
from functools import lru_cache
import itertools
import re
import string

# Application parameters measured on the development split (ADR 0079).
MIN_ENCODED = 16  # characters in the longest piece of a candidate
MIN_TEXT_SHARE = 0.85  # share of PLAIN characters in a decoded plaintext
CHANGE_PENALTY = 0.25  # per character replaced by a look-alike
RESYNC_PENALTY = 1.5  # per character skipped or assumed missing
MAX_VARIANTS = 256  # look-alike combinations tried per group

PIECE = re.compile(r"[A-Za-z0-9+/]*={0,2}")
TOKEN = re.compile(r"\S+")
LOOK_ALIKES = {}
for _letter in "cosuvwxzkpjy":
    LOOK_ALIKES[_letter] = (_letter, _letter.upper())
    LOOK_ALIKES[_letter.upper()] = (_letter.upper(), _letter)
for _group in ("lI1", "0O", "5S", "8B", "2Z"):
    for _char in _group:
        known = LOOK_ALIKES.get(_char, (_char,))
        LOOK_ALIKES[_char] = (*known, *(c for c in _group if c not in known))
TEXT = set(string.ascii_letters + string.digits + " .,;:'\"-()!?/%&+=_@#*–’")
PLAIN = set(string.ascii_letters + string.digits + " .,;:'-")


def byte_score(data):
    score = 0.0
    for value in data:
        char = chr(value)
        if char in string.ascii_lowercase or char == " ":
            score += 1.0
        elif char in TEXT:
            score += 0.8
        elif value >= 0x80:
            score += 0.3  # possibly part of a UTF-8 character
        else:
            score -= 2.0
    return score


@lru_cache(maxsize=4096)
def best_group(group):
    """Best (score, bytes) over the look-alike variants of one group."""
    choices = [LOOK_ALIKES.get(char, (char,)) for char in group]
    size = len(group) * 3 // 4
    best = None
    for variant in itertools.islice(itertools.product(*choices), MAX_VARIANTS):
        data = base64.b64decode("".join(variant) + "=" * (-len(group) % 4))[:size]
        changes = sum(a != b for a, b in zip(variant, group))
        score = byte_score(data) - CHANGE_PENALTY * changes
        if best is None or score > best[0]:
            best = (score, data)
    return best


def repair(encoded):
    """Bytes of the most text-like reading of ``encoded`` (no padding)."""
    length = len(encoded)
    score = [0.0] * (length + 1)
    step = [None] * (length + 1)
    for index in range(length - 1, -1, -1):
        options = [(score[index + 1] - RESYNC_PENALTY, 1, b"")]
        for size in (4, 3, 2):
            end = index + size
            if end > length or (size == 2 and end != length):
                continue
            value, data = best_group(encoded[index:end])
            # A short group is a dropped character unless it ends the string.
            if size < 4 and end != length:
                value -= RESYNC_PENALTY
            options.append((score[end] + value, size, data))
        score[index], *step[index] = max(options, key=lambda option: option[0])
    out, index = bytearray(), 0
    while index < length:
        size, data = step[index]
        out += data
        index += size
    return bytes(out)


def looks_encoded(token):
    body = token.rstrip("=")
    return any(c.isdigit() or c in "+/" for c in body) or any(
        c.isupper() for c in body[1:]
    )


def candidates(text):
    """Spans of encoded-looking tokens, joined across OCR-inserted whitespace."""
    run = []
    for match in [*TOKEN.finditer(text), None]:
        token = match.group(0) if match else ""
        if (
            match
            and PIECE.fullmatch(token)
            and (looks_encoded(token) or (run and not token.strip("=")))
        ):
            run.append(match)
            continue
        if run and max(len(m.group(0).rstrip("=")) for m in run) >= MIN_ENCODED:
            yield run[0].start(), run[-1].end()
        run = []


def plausible(plaintext):
    if not plaintext.strip():
        return False
    share = sum(char in PLAIN for char in plaintext) / len(plaintext)
    return share >= MIN_TEXT_SHARE


def decoded(text):
    """Detector parts for the readable base64 plaintexts in ``text``."""
    for start, end in candidates(text):
        encoded = re.sub(r"[\s=]+", "", text[start:end])
        plaintext = repair(encoded).decode("utf-8", errors="replace")
        if not plausible(plaintext):
            continue
        yield {
            "text": "".join(c if c.isprintable() else "�" for c in plaintext),
            "start": start,
            "end": end,
            "partial_context": True,
            "kind": "decoded",
            "encoding": "base64",
        }
