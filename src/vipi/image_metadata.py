"""Text in raster image metadata as a detector reading (ADR 0083).

Applications and agents read EXIF, XMP, IPTC, PNG text chunks and JPEG
comments, and OCR never sees them. Every text value becomes one line of a
single reading; binary values (thumbnails, maker notes, ICC profiles, C2PA
manifests) are not text and are left out.
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import pyexpat
import struct
import unicodedata
import zlib

from PIL import Image, IptcImagePlugin, PngImagePlugin
from PIL.ExifTags import GPSTAGS, IFD, TAGS

from .svg.text import normalize_invisible

READING = "image_metadata"
INCOMPLETE_UNREADABLE = (
    "Image metadata could not be read ({groups}); text that other tools read "
    "there was not checked."
)
XMP_KEY = "XML:com.adobe.xmp"
XMP_STANDARD = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXTENSION = b"http://ns.adobe.com/xmp/extension/\x00"
EXIF_HEADER = b"Exif\x00\x00"
# EXIF tags whose bytes are UTF-16LE (Windows XP* tags).
UTF16_TAGS = {0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F}
# EXIF tags that start with an 8-byte character code (EXIF 2.3, 4.6.5).
CHARSET_TAGS = {("exif", 0x9286), ("gps", 0x001B), ("gps", 0x001C)}
# XMP attributes with a fixed vocabulary rather than text.
XMP_STRUCTURAL = {"rdf:parseType", "xml:lang"}


@dataclass(frozen=True)
class ImageMetadata:
    """The text values of one image's metadata, ready for detection."""

    fields: tuple[str, ...]
    text: str
    detector_text: str
    invisible_characters: int
    unreadable: tuple[str, ...]

    @property
    def incomplete(self):
        if self.unreadable:
            return (INCOMPLETE_UNREADABLE.format(groups=", ".join(self.unreadable)),)
        return ()

    def report(self, answers=()):
        """The report's `metadata` object; `answers` adds the score per reading."""
        from .detection.evidence import reading_scores

        scores = reading_scores(answers, ("ocr", READING))
        return {
            "fields": list(self.fields),
            "characters": len(self.text),
            "invisible_characters": self.invisible_characters,
            "unreadable": list(self.unreadable),
            "scores": scores,
        }


def read_metadata(source):
    """Read the metadata text of a PNG, JPEG or WebP path or bytes."""
    lines, unreadable = [], []
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    with Image.open(BytesIO(data)) as image:
        for group, read in (
            ("text chunks", _png_text),
            ("JPEG comments", _jpeg_comments),
            ("XMP", _xmp),
            ("EXIF", _exif),
            ("IPTC", _iptc),
        ):
            try:
                lines += read(image, data)
            except Exception:  # noqa: BLE001 - any parser failure is unreadable
                unreadable.append(group)
    lines = [(name, value.strip()) for name, value in lines]
    lines = [(name, value) for name, value in lines if value]
    text = "\n".join(f"{name}: {value}" for name, value in lines)
    detector_text, invisible = normalize_invisible(text)
    return ImageMetadata(
        fields=tuple(dict.fromkeys(name for name, _ in lines)),
        text=text,
        detector_text=detector_text,
        invisible_characters=invisible,
        unreadable=tuple(unreadable),
    )


def _png_text(image, data):
    if image.format != "PNG":
        return []
    return [
        (f"PNG {key}", _value(text))
        for key, text in _png_chunks(data)
        if key != XMP_KEY
    ]


def _value(text):
    """A decoded chunk text, or the error that kept it from being decoded."""
    if isinstance(text, Exception):
        raise text
    return text


def _png_chunks(data):
    """Every text chunk as (keyword, text or error), before or after the pixels.

    Pillow's `Image.text` keeps one value per keyword, so a later chunk with
    the same keyword would hide an earlier one; the chunks are parsed here.
    Decompression is bounded by Pillow's own text chunk limits. A chunk that
    cannot be decoded carries its error, so only the group reading it fails.
    """
    chunks, position, memory = [], 8, 0
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        if len(body) < length:
            raise ValueError("PNG chunk is truncated.")
        position += 12 + length
        if kind in (b"tEXt", b"zTXt", b"iTXt"):
            key, _, rest = body.partition(b"\x00")
            try:
                text = _png_chunk_text(kind, rest)
                memory += len(text or "")
                if memory > PngImagePlugin.MAX_TEXT_MEMORY:
                    raise ValueError("PNG text exceeds Pillow's text memory limit.")
            except (ValueError, zlib.error) as error:
                text = ValueError(str(error))
            if text is not None:
                chunks.append((key.decode("latin-1"), text))
        if kind == b"IEND":
            break
    return chunks


def _png_chunk_text(kind, rest):
    if kind == b"tEXt":
        return rest.decode("latin-1")
    if kind == b"zTXt":
        return _inflate(rest[1:]).decode("latin-1")
    flag, rest = rest[:1], rest[2:]
    _, _, rest = rest.partition(b"\x00")  # language tag
    _, _, rest = rest.partition(b"\x00")  # translated keyword
    return _text(_inflate(rest) if flag == b"\x01" else rest)


def _inflate(data):
    inflater = zlib.decompressobj()
    text = inflater.decompress(data, PngImagePlugin.MAX_TEXT_CHUNK)
    if inflater.unconsumed_tail:
        raise ValueError("Compressed PNG text exceeds Pillow's text chunk limit.")
    return text


def _jpeg_comments(image, data):
    if image.format != "JPEG":
        return []
    return [
        ("JPEG comment", text)
        for marker, data in image.applist
        if marker == "COM" and (text := _text(data)) is not None
    ]


def _xmp(image, data):
    if image.format == "PNG":
        packets = [
            _value(text).encode() for key, text in _png_chunks(data) if key == XMP_KEY
        ]
    elif image.format == "JPEG":
        packets = _jpeg_xmp(image.applist)
    else:
        packets = [image.info["xmp"]] if image.info.get("xmp") else []
    return [line for packet in packets for line in _xmp_lines(packet)]


def _jpeg_xmp(applist):
    """Standard XMP packets and extended XMP reassembled in offset order."""
    packets, extended = [], {}
    for marker, data in applist:
        if marker != "APP1":
            continue
        if data.startswith(XMP_STANDARD):
            packets.append(data[len(XMP_STANDARD) :])
        elif data.startswith(XMP_EXTENSION):
            body = data[len(XMP_EXTENSION) :]
            guid, offset = body[:32], int.from_bytes(body[36:40], "big")
            extended.setdefault(guid, []).append((offset, body[40:]))
    for parts in extended.values():
        packets.append(b"".join(part for _, part in sorted(parts)))
    return packets


def _xmp_lines(packet):
    # Expat delivers one text node in pieces (at entity references, for
    # example), so text is collected until the next markup event.
    lines, stack, pending = [], [], []

    def label():
        names = [name for name in stack if not name.startswith(("rdf:", "x:"))]
        return f"XMP {names[-1] if names else 'text'}"

    def flush():
        data = "".join(pending)
        pending.clear()
        if data.strip():
            lines.append((label(), data))

    def start(name, attributes):
        flush()
        stack.append(name)
        for key, value in zip(attributes[::2], attributes[1::2]):
            if not key.startswith("xmlns") and key not in XMP_STRUCTURAL:
                lines.append((f"XMP {key}", value))

    def end(name):
        flush()
        stack.pop()

    def comment(data):
        flush()
        lines.append(("XMP comment", data))

    def instruction(target, data):
        flush()
        if target != "xpacket":
            lines.append((f"XMP {target}", data))

    parser = pyexpat.ParserCreate()
    parser.ordered_attributes = True
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = pending.append
    parser.CommentHandler = comment
    parser.ProcessingInstructionHandler = instruction
    parser.Parse(packet, True)
    flush()
    return lines


def _exif(image, data):
    raw = image.info.get("exif") or b""
    exif = image.getexif()
    groups = [
        ("exif", TAGS, dict(exif)),
        ("exif", TAGS, dict(exif.get_ifd(IFD.Exif))),
        ("gps", GPSTAGS, dict(exif.get_ifd(IFD.GPSInfo))),
    ]
    if not any(values for _, _, values in groups) and len(
        raw.removeprefix(EXIF_HEADER)
    ) > len(b"MM\x00*\x00\x00\x00\x08"):
        # Pillow ignores EXIF it cannot parse instead of raising.
        raise ValueError("EXIF data could not be parsed.")
    endian = getattr(exif, "endian", None) or "<"
    lines = []
    for group, names, values in groups:
        for tag, value in values.items():
            text = _exif_text(group, tag, value, endian)
            if text is not None:
                lines.append((f"EXIF {names.get(tag, hex(tag))}", text))
    return lines


def _exif_text(group, tag, value, endian):
    if isinstance(value, str):
        return _utf8_from_latin1(value).replace("\x00", " ")
    if isinstance(value, tuple) and tag in UTF16_TAGS:
        value = bytes(value)
    if not isinstance(value, bytes):
        return None
    if tag in UTF16_TAGS:
        return value.decode("utf-16-le", "replace").replace("\x00", " ")
    if (group, tag) in CHARSET_TAGS:
        code, body = value[:8].rstrip(b"\x00 "), value[8:]
        if code == b"UNICODE":
            if body.startswith((b"\xff\xfe", b"\xfe\xff")):
                return body.decode("utf-16", "replace").replace("\x00", " ")
            encoding = "utf-16-be" if endian == ">" else "utf-16-le"
            return body.decode(encoding, "replace").replace("\x00", " ")
        if code == b"JIS":
            return body.decode("shift_jis", "replace").replace("\x00", " ")
        return _text(body.rstrip(b"\x00"))
    return _text(value.rstrip(b"\x00"))


def _iptc(image, data):
    if image.format != "JPEG":
        return []
    info = IptcImagePlugin.getiptcinfo(image) or {}
    lines = []
    for (record, dataset), values in info.items():
        if record != 2:  # the application record holds the descriptive text
            continue
        for value in values if isinstance(values, list) else [values]:
            text = _text(value) if isinstance(value, bytes) else None
            if text is not None:
                lines.append((f"IPTC 2:{dataset}", text))
    return lines


def _utf8_from_latin1(text):
    """Pillow decodes ASCII tags as Latin-1; writers commonly store UTF-8 there."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text


def _text(data):
    """Decode bytes that are text; binary data is not a text value."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(
        unicodedata.category(character) == "Cc" and character not in "\t\n\r"
        for character in text
    ):
        return None
    return text
