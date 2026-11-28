"""Write metadata text fields that `vipi.image_metadata` reads (ADR 0083).

Each container lists the output formats that carry it and its fields. A
field's `label` is the name VIPI's reader gives the value, so the read-back can
match a written value to the reading line `label: value`.
"""

import struct
import zlib
from io import BytesIO
from xml.sax.saxutils import escape

from PIL import Image, PngImagePlugin
from PIL.ExifTags import IFD

XMP_KEY = "XML:com.adobe.xmp"
EXIF_UNICODE = b"UNICODE\x00"
# Largest payload of one JPEG marker segment: 65535 minus the length field.
JPEG_SEGMENT_BYTES = 65533
PHOTOSHOP = b"Photoshop 3.0\x00"
IPTC_RESOURCE = 0x0404
# Record 1:90 "ESC % G" declares UTF-8 for the IPTC application record.
IPTC_UTF8 = b"\x1c\x01\x5a\x00\x03\x1b\x25\x47"

XMP_NAMESPACES = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
}
# XMP property → RDF container type (None for a simple value).
XMP_FIELDS = {
    "dc:description": "Alt",
    "dc:title": "Alt",
    "dc:rights": "Alt",
    "dc:creator": "Seq",
    "dc:subject": "Bag",
    "photoshop:Instructions": None,
    "photoshop:Headline": None,
    "xmp:CreatorTool": None,
}
# EXIF field → (IFD, tag, encoding). "ascii" tags get UTF-8 bytes, as
# exiftool and most editors write them; Pillow would replace non-ASCII
# characters of a str with "?".
EXIF_FIELDS = {
    "ImageDescription": (None, 0x010E, "ascii"),
    "Make": (None, 0x010F, "ascii"),
    "Model": (None, 0x0110, "ascii"),
    "Software": (None, 0x0131, "ascii"),
    "Artist": (None, 0x013B, "ascii"),
    "Copyright": (None, 0x8298, "ascii"),
    "XPTitle": (None, 0x9C9B, "utf16"),
    "XPComment": (None, 0x9C9C, "utf16"),
    "XPAuthor": (None, 0x9C9D, "utf16"),
    "XPKeywords": (None, 0x9C9E, "utf16"),
    "XPSubject": (None, 0x9C9F, "utf16"),
    "UserComment": (IFD.Exif, 0x9286, "charset"),
    "GPSProcessingMethod": (IFD.GPSInfo, 0x001B, "charset"),
    "GPSAreaInformation": (IFD.GPSInfo, 0x001C, "charset"),
}
IPTC_FIELDS = {
    "5": "Object name",
    "25": "Keywords",
    "80": "By-line",
    "105": "Headline",
    "116": "Copyright notice",
    "120": "Caption",
}

CONTAINERS = {
    "png_text": {
        "title": "PNG text chunk",
        "formats": ("png",),
        "fields": {},
        "note": "Any keyword of 1–79 Latin-1 characters. tEXt for Latin-1, iTXt otherwise, zTXt when compressed.",
    },
    "xmp": {
        "title": "XMP",
        "formats": ("png", "jpeg", "webp"),
        "fields": {name: f"XMP {name}" for name in XMP_FIELDS},
        "note": "One XMP packet per image.",
    },
    "exif": {
        "title": "EXIF",
        "formats": ("png", "jpeg", "webp"),
        "fields": {name: f"EXIF {name}" for name in EXIF_FIELDS},
        "note": "ImageDescription … Copyright are ASCII tags, written as UTF-8 like most editors do; XP* are UTF-16, UserComment and GPS text use the UNICODE character code.",
    },
    "jpeg_comment": {
        "title": "JPEG comment",
        "formats": ("jpeg",),
        "fields": {"comment": "JPEG comment"},
        "note": "A COM segment.",
    },
    "iptc": {
        "title": "IPTC",
        "formats": ("jpeg",),
        "fields": {number: f"IPTC 2:{number}" for number in IPTC_FIELDS},
        "note": "Application record in a Photoshop APP13 segment, UTF-8.",
    },
}


def field_titles():
    """Human titles for fields whose reader label is not self-explanatory."""
    return {
        "iptc": {number: f"2:{number} {name}" for number, name in IPTC_FIELDS.items()}
    }


def reader_label(layer):
    """The name `vipi.image_metadata` gives this layer's value."""
    if layer["container"] == "png_text":
        return f"PNG {layer['key']}"
    return CONTAINERS[layer["container"]]["fields"][layer["field"]]


def validate(layer):
    """Return the layer's normalized fields or raise ValueError."""
    container = layer.get("container")
    if container not in CONTAINERS:
        raise ValueError(f"Unknown metadata container: {container!r}.")
    value = layer.get("value")
    if not isinstance(value, str):
        raise ValueError("A metadata value must be text.")
    clean = {"container": container, "value": value}
    if container == "png_text":
        key = layer.get("key")
        # PNG specification 11.3.4: keyword of 1-79 Latin-1 characters.
        if not isinstance(key, str) or not 1 <= len(key) <= 79 or key == XMP_KEY:
            raise ValueError("A PNG text keyword needs 1–79 characters.")
        try:
            key.encode("latin-1")
        except UnicodeEncodeError:
            raise ValueError("A PNG text keyword must be Latin-1.") from None
        clean |= {
            "key": key,
            "compressed": layer.get("compressed") is True,
            "after_pixels": layer.get("after_pixels") is True,
        }
    else:
        field = layer.get("field")
        if field not in CONTAINERS[container]["fields"]:
            raise ValueError(f"Unknown {container} field: {field!r}.")
        clean["field"] = field
    return clean


def save(image, image_format, layers):
    """Encode `image` as `image_format` with the metadata `layers`."""
    by_container = {}
    for layer in layers:
        by_container.setdefault(layer["container"], []).append(layer)
    options = {}
    if image_format == "jpeg":
        options["quality"] = 95
    if image_format == "webp":
        # Lossless, so pixel-level layers survive; JPEG is lossy by design.
        options["lossless"] = True
        options["exact"] = True  # keep colour under transparent pixels
    if "exif" in by_container:
        # Bytes, because Pillow's PNG writer drops an Exif object whose
        # first IFD is empty (only UserComment or GPS fields set).
        options["exif"] = _exif(by_container["exif"]).tobytes()
    if "xmp" in by_container:
        packet = _xmp_packet(by_container["xmp"])
        if image_format != "png":
            options["xmp"] = packet
    if image_format == "png":
        info = PngImagePlugin.PngInfo()
        for layer in by_container.get("png_text", ()):
            if not layer["after_pixels"]:
                info.add_text(layer["key"], layer["value"], zip=layer["compressed"])
        if "xmp" in by_container:
            info.add_itxt(XMP_KEY, packet.decode())
        options["pnginfo"] = info
    buffer = BytesIO()
    image.save(
        buffer, {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[image_format], **options
    )
    data = buffer.getvalue()
    if image_format == "png":
        late = [
            layer for layer in by_container.get("png_text", ()) if layer["after_pixels"]
        ]
        if late:
            data = _png_insert_before_end(
                data, [_png_text_chunk(layer) for layer in late]
            )
    if image_format == "jpeg":
        segments = [
            _jpeg_segment(0xFE, layer["value"].encode())
            for layer in by_container.get("jpeg_comment", ())
        ]
        if "iptc" in by_container:
            segments.append(_jpeg_segment(0xED, _photoshop_iptc(by_container["iptc"])))
        if segments:
            data = _jpeg_insert_after_app(data, segments)
    return data


def _exif(layers):
    exif = Image.Exif()
    seen = set()
    for layer in layers:
        if layer["field"] in seen:
            raise ValueError(f"EXIF {layer['field']} is set by two layers.")
        seen.add(layer["field"])
        ifd, tag, encoding = EXIF_FIELDS[layer["field"]]
        value = layer["value"]
        if encoding == "ascii":
            value = value.encode()
        elif encoding == "utf16":
            value = value.encode("utf-16-le") + b"\x00\x00"
        elif encoding == "charset":
            # UTF-16 with a byte-order mark, so the reader needs no endian guess.
            value = EXIF_UNICODE + value.encode("utf-16")
        (exif.get_ifd(ifd) if ifd else exif)[tag] = value
    return exif


def _xmp_packet(layers):
    properties = []
    for layer in layers:
        name, value = layer["field"], escape(layer["value"])
        kind = XMP_FIELDS[name]
        if kind == "Alt":
            body = f'<rdf:Alt><rdf:li xml:lang="x-default">{value}</rdf:li></rdf:Alt>'
        elif kind:
            body = f"<rdf:{kind}><rdf:li>{value}</rdf:li></rdf:{kind}>"
        else:
            body = value
        properties.append(f"<{name}>{body}</{name}>")
    namespaces = " ".join(
        f'xmlns:{prefix}="{uri}"' for prefix, uri in XMP_NAMESPACES.items()
    )
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description rdf:about="" {namespaces}>{"".join(properties)}</rdf:Description>'
        '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode()


def _png_text_chunk(layer):
    # Same chunk choice as Pillow's PngInfo.add_text: tEXt/zTXt for Latin-1,
    # otherwise iTXt (flag, method, empty language and translated keyword).
    key, value = layer["key"].encode("latin-1"), layer["value"]
    compressed = layer["compressed"]
    try:
        text = value.encode("latin-1")
        kind = b"zTXt" if compressed else b"tEXt"
        body = key + (
            b"\x00\x00" + zlib.compress(text) if compressed else b"\x00" + text
        )
    except UnicodeEncodeError:
        text = zlib.compress(value.encode()) if compressed else value.encode()
        kind = b"iTXt"
        body = (
            key
            + b"\x00"
            + (b"\x01" if compressed else b"\x00")
            + b"\x00\x00\x00"
            + text
        )
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body))
    )


def _png_insert_before_end(data, chunks):
    end = data.rindex(b"IEND") - 4
    return data[:end] + b"".join(chunks) + data[end:]


def _jpeg_segment(marker, payload):
    if len(payload) > JPEG_SEGMENT_BYTES:
        raise ValueError(f"A JPEG segment holds at most {JPEG_SEGMENT_BYTES} bytes.")
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _photoshop_iptc(layers):
    datasets = IPTC_UTF8
    for layer in layers:
        value = layer["value"].encode()
        if len(value) > 0x7FFF:
            raise ValueError("An IPTC value holds at most 32767 bytes.")
        datasets += (
            bytes((0x1C, 2, int(layer["field"])))
            + struct.pack(">H", len(value))
            + value
        )
    if len(datasets) % 2:
        datasets += b"\x00"
    # 8BIM resource: type, ID, empty Pascal name padded to even length, size.
    resource = b"8BIM" + struct.pack(">H", IPTC_RESOURCE) + b"\x00\x00"
    return PHOTOSHOP + resource + struct.pack(">I", len(datasets)) + datasets


def _jpeg_insert_after_app(data, segments):
    """Insert segments after SOI and the leading APPn segments."""
    position = 2
    while data[position] == 0xFF and 0xE0 <= data[position + 1] <= 0xEF:
        position += 2 + struct.unpack(">H", data[position + 2 : position + 4])[0]
    return data[:position] + b"".join(segments) + data[position:]
