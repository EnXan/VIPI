"""Pixel steganography that VIPI's PNG readers extract.

- OpenStego legacy (ADR 0088): header and payload in the low bit of every
  RGB sample, in file order.
- OpenStego RandomLSB v2 with the default seed (ADR 0089): the same Java
  random position sequence the reader follows, written instead of read.
- Declared PNG LSB layouts in zsteg notation (ADR 0090): the reader's sample
  order and bit assembly, inverted.

All three need a static 8-bit RGB PNG; the writers mirror VIPI's readers, so
the external tools (OpenStego, zsteg) remain the independent check.
"""

import math

import numpy as np
from PIL import Image

from vipi.openstego import HEADER, MARKER
from vipi.openstego_random_lsb import RandomLsbReader
from vipi.png_lsb import PREVIEW_BYTES, validate_layout

KINDS = {
    "openstego": "OpenStego (legacy)",
    "openstego_random_lsb": "OpenStego RandomLSB",
    "png_lsb": "PNG LSB (zsteg layout)",
}
# OpenStego v2 stores an 8-byte encryption algorithm field; unencrypted
# payloads leave it empty, and VIPI skips it.
ALGORITHM = b"\x00" * 8


def validate(layer):
    kind = layer.get("stego")
    if kind not in KINDS:
        raise ValueError(f"Choose one of: {', '.join(KINDS)}.")
    text = layer.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A steganography layer needs text.")
    clean = {"stego": kind, "text": text}
    if kind == "png_lsb":
        clean["layout"] = validate_layout(layer.get("layout"))
        if len(text.encode()) + 1 > PREVIEW_BYTES:
            raise ValueError(
                f"zsteg and VIPI read the first {PREVIEW_BYTES} bytes of a layout; shorten the text."
            )
    else:
        name = layer.get("filename") or "message.txt"
        clean["filename"] = str(name)
    if kind == "openstego_random_lsb":
        depth = layer.get("depth", 1)
        if depth not in range(1, 9):
            raise ValueError("RandomLSB bit depth is 1 to 8.")
        clean["depth"] = depth
    return clean


def embed(image, layer):
    """Write the layer into an RGB image and return the new image."""
    if layer["stego"] == "openstego":
        return _legacy(image, layer)
    if layer["stego"] == "openstego_random_lsb":
        return _random_lsb(image, layer)
    return _png_lsb(image, layer)


def _legacy(image, layer):
    payload, name = layer["text"].encode(), layer["filename"].encode()
    data = MARKER + HEADER.pack(1, len(payload), 1, len(name), 0, 0) + name + payload
    bits = np.unpackbits(np.frombuffer(data, np.uint8))
    samples = np.array(image, dtype=np.uint8).reshape(-1)
    if len(bits) > len(samples):
        raise ValueError(
            f"OpenStego needs {len(bits)} samples; the image has {len(samples)}."
        )
    samples[: len(bits)] = (samples[: len(bits)] & 0xFE) | bits
    return Image.fromarray(samples.reshape(image.height, image.width, 3))


class _RandomLsbWriter(RandomLsbReader):
    """Follow the reader's position sequence and set the bits instead."""

    def write(self, data):
        for byte in data:
            for shift in range(7, -1, -1):
                self._write_bit((byte >> shift) & 1)

    def _write_bit(self, value):
        while True:
            x = self._draw(self.width)
            y = self._draw(self.height)
            channel = 2 - self._draw(3)
            bit = self._draw(self.depth)
            sample = (y * self.width + x) * 3 + channel
            if self._claim(sample, bit):
                pixel = list(self.pixels[x, y])
                pixel[channel] = (pixel[channel] & ~(1 << bit)) | (value << bit)
                self.pixels[x, y] = tuple(pixel)
                return


def _random_lsb(image, layer):
    payload, name = layer["text"].encode(), layer["filename"].encode()
    capacity = image.width * image.height * 3
    header = MARKER + HEADER.pack(2, len(payload), layer["depth"], len(name), 0, 0)
    header_bits = (len(header) + len(ALGORITHM) + len(name)) * 8
    if (
        header_bits + len(payload) * 8 > capacity * layer["depth"]
        or header_bits > capacity
    ):
        raise ValueError("The image is too small for this RandomLSB payload.")
    image = image.copy()
    writer = _RandomLsbWriter(image)
    writer.write(header + ALGORITHM + name)
    writer.start_payload(layer["depth"])
    writer.write(payload)
    return image


def _png_lsb(image, layer):
    width, channels, bit_order, traversal = layer["layout"].split(",")
    depth = int(width[1:])
    data = layer["text"].encode() + b"\x00"  # ends the printable run
    bits = np.unpackbits(
        np.frombuffer(data, np.uint8),
        bitorder="big" if bit_order == "lsb" else "little",
    )
    per_pixel = depth * len(channels)
    count = math.ceil(len(bits) / per_pixel)
    if count > image.width * image.height:
        raise ValueError("The image is too small for this layout and text.")
    bits = np.concatenate([bits, np.zeros(count * per_pixel - len(bits), np.uint8)])
    pixels = np.array(image, dtype=np.uint8)
    flat = (
        pixels.reshape(-1, 3)
        if traversal == "xy"
        else pixels.transpose(1, 0, 2).reshape(-1, 3)
    )
    chosen = ["rgb".index(channel) for channel in channels]
    # The reader takes the low `depth` bits of each sample from high to low.
    values = bits.reshape(count, len(chosen), depth)
    weights = (1 << np.arange(depth - 1, -1, -1)).astype(np.uint8)
    low = (values * weights).sum(axis=2).astype(np.uint8)
    keep = np.uint8((0xFF << depth) & 0xFF)
    flat[:count, chosen] = (flat[:count, chosen] & keep) | low
    if traversal == "yx":
        pixels = flat.reshape(image.width, image.height, 3).transpose(1, 0, 2)
    return Image.fromarray(
        np.ascontiguousarray(pixels.reshape(image.height, image.width, 3))
    )
