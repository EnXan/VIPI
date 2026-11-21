"""Text helpers for SVG source readings: `data:` URIs and invisible characters."""

import base64
import binascii
import re
import unicodedata
from urllib.parse import unquote_to_bytes

# RFC 2397: an omitted media type means text/plain.
TEXT_MEDIA_TYPES = {
    "",
    "application/ecmascript",
    "application/javascript",
    "application/json",
    "application/xml",
}
SVG_MEDIA_TYPE = "image/svg+xml"
# A CSS url() may quote a data URI that contains spaces (for example raw SVG);
# a bare data URI ends at whitespace, a quote, a bracket or a parenthesis.
# Each part has a character class disjoint from the next, so the expression
# cannot backtrack exponentially on attacker-controlled text.
DATA_URI = re.compile(
    r"""url\(\s*(?:"(data:[^"]*)"|'(data:[^']*)')\s*\)"""
    r"""|(data:[\w.+-]*(?:/[\w.+-]*)?(?:;[^;,\s"'<>()]*)*,[^\s"'<>()]*)""",
    re.IGNORECASE,
)
TAG_CHARACTERS = range(0xE0000, 0xE0080)
TAG_ASCII = range(0xE0020, 0xE007F)
VARIATION_SELECTORS = (range(0xFE00, 0xFE10), range(0xE0100, 0xE01F0))


def parse_data_uri(uri):
    """Return `(media type, payload bytes)`, or None when the URI is malformed."""
    header, separator, payload = uri.partition(",")
    if not separator or not header[:5].lower() == "data:":
        return None
    parameters = header[5:].split(";")
    media_type = parameters[0].strip().lower()
    try:
        if any(item.strip().lower() == "base64" for item in parameters[1:]):
            compact = "".join(unquote_to_bytes(payload).decode("ascii").split())
            return media_type, base64.b64decode(compact, validate=True)
        return media_type, unquote_to_bytes(payload)
    except (binascii.Error, UnicodeError, ValueError):
        return None


def is_text_media_type(media_type):
    return (
        media_type in TEXT_MEDIA_TYPES
        or media_type.startswith("text/")
        or media_type.endswith(("+xml", "+json"))
    )


def decode_text(payload):
    return payload.decode("utf-8", errors="replace")


def expand_data_uris(text, nested_svg):
    """Replace `data:` URIs by their decoded text; drop binary payloads.

    ``nested_svg(payload)`` returns the source text of an embedded SVG.
    """

    def replace(match):
        uri = next(group for group in match.groups() if group is not None)
        parsed = parse_data_uri(uri)
        if parsed is None:
            return match.group(0)
        media_type, payload = parsed
        if media_type == SVG_MEDIA_TYPE:
            return f" {nested_svg(payload)} "
        if is_text_media_type(media_type):
            return f" {decode_text(payload)} "
        return " "

    return DATA_URI.sub(replace, text)


def normalize_invisible(text):
    """Decode Unicode tag characters and remove other invisible characters.

    Tag characters U+E0020–U+E007E encode ASCII invisibly ("ASCII smuggling");
    zero-width, bidirectional and other format characters split trigger words
    for classifiers. Returns the normalised text and how many characters were
    decoded or removed.
    """
    output, tags, count = [], [], 0

    def flush_tags():
        if tags:
            output.append(f" {''.join(tags)} ")
            tags.clear()

    for character in text:
        code = ord(character)
        if code in TAG_CHARACTERS:
            count += 1
            if code in TAG_ASCII:
                tags.append(chr(code - 0xE0000))
            continue
        flush_tags()
        if unicodedata.category(character) == "Cf" or any(
            code in selectors for selectors in VARIATION_SELECTORS
        ):
            count += 1
            continue
        output.append(character)
    flush_tags()
    return "".join(output), count
