"""Text in raster image metadata as a detector reading (ADR 0083).

Applications and agents read EXIF, XMP, IPTC, PNG text chunks and JPEG
comments, and OCR never sees them. Every text value becomes one line of a
single reading; binary values (thumbnails, maker notes, ICC profiles, C2PA
manifests) are not text and are left out.
"""

from dataclasses import dataclass
from io import BytesIO
import pyexpat
import unicodedata

from PIL import Image, IptcImagePlugin
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
    with Image.open(BytesIO(source) if isinstance(source, bytes) else source) as image:
        for group, read in (
            ("text chunks", _png_text),
            ("JPEG comments", _jpeg_comments),
            ("XMP", _xmp),
            ("EXIF", _exif),
            ("IPTC", _iptc),
        ):
            try:
                lines += read(image)
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


def _png_text(image):
    if image.format != "PNG":
        return []
    # `text` loads the image, so chunks after the pixel data are included.
    return [
        (f"PNG {key}", value)
        for key, value in image.text.items()
        if key != XMP_KEY and isinstance(value, str)
    ]


def _jpeg_comments(image):
    if image.format != "JPEG":
        return []
    return [
        ("JPEG comment", text)
        for marker, data in image.applist
        if marker == "COM" and (text := _text(data)) is not None
    ]


def _xmp(image):
    if image.format == "PNG":
        packets = [image.text[XMP_KEY].encode()] if XMP_KEY in image.text else []
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
    lines, stack = [], []

    def label():
        names = [name for name in stack if not name.startswith(("rdf:", "x:"))]
        return f"XMP {names[-1] if names else 'text'}"

    def start(name, attributes):
        stack.append(name)
        for key, value in zip(attributes[::2], attributes[1::2]):
            if not key.startswith("xmlns") and key not in XMP_STRUCTURAL:
                lines.append((f"XMP {key}", value))

    def characters(data):
        if data.strip():
            lines.append((label(), data))

    def instruction(target, data):
        if target != "xpacket":
            lines.append((f"XMP {target}", data))

    parser = pyexpat.ParserCreate()
    parser.ordered_attributes = True
    parser.StartElementHandler = start
    parser.EndElementHandler = lambda name: stack.pop()
    parser.CharacterDataHandler = characters
    parser.CommentHandler = lambda data: lines.append(("XMP comment", data))
    parser.ProcessingInstructionHandler = instruction
    parser.Parse(packet, True)
    return lines


def _exif(image):
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
        return value.replace("\x00", " ")
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


def _iptc(image):
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
