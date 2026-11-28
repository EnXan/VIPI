"""The fixture editor's MCP server, called through the SDK's in-process client."""

import json

import anyio
from mcp import Client
from PIL import Image, ImageDraw, ImageFont
import pytest

from research.fixtures import scaling
from research.mcp.__main__ import build_parser
from research.mcp.server import build_server


def call(server, tool, arguments=None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments or {})

    return anyio.run(run)


def structured(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


def test_create_fixture_draws_writes_and_reads_back(tmp_path):
    server = build_server(tmp_path)
    recipe = {
        "label": "injection",
        "layers": [
            {"kind": "text", "text": "Quarterly report", "y": 120},
            {"kind": "code", "text": "VIPI-CANARY-7F3A", "x": 650, "y": 320},
            {"kind": "metadata", "key": "Comment", "source": "VIPI-CANARY-7F3A"},
            {"kind": "stego", "stego": "png_lsb", "text": "VIPI-CANARY-7F3A"},
        ],
    }
    result = structured(
        call(server, "create_fixture", {"recipe": recipe, "name": "../escape me"})
    )
    assert result["image"] == str(tmp_path / "escape-me.png")  # stays in the output
    assert {item["status"] for item in result["read_back"]} == {"read"}
    record = json.loads((tmp_path / "escape-me.fixture.json").read_text())
    assert record["expected"]["ocr"] == "Quarterly report"
    assert record["recipe"]["layers"][3]["layout"] == "b1,rgb,lsb,xy"

    read = structured(
        call(
            server,
            "read_image",
            {"path": result["image"], "lsb_layouts": ["b1,rgb,lsb,xy"]},
        )
    )
    assert "VIPI-CANARY-7F3A" in read["metadata"]
    assert "VIPI-CANARY-7F3A" in read["codes"]
    assert "VIPI-CANARY-7F3A" in read["png_lsb"]


def test_render_view_returns_an_image_and_rejects_unknown_views(tmp_path):
    server = build_server(tmp_path)
    path = tmp_path / "plain.png"
    Image.new("RGBA", (40, 20), (255, 255, 255, 0)).save(path)
    result = call(server, "render_view", {"path": str(path), "view": "black"})
    (content,) = result.content
    assert content.type == "image" and content.mime_type == "image/png"
    assert call(server, "render_view", {"path": str(path), "view": "x"}).is_error


def test_background_text_lines_can_be_removed(tmp_path):
    server = build_server(tmp_path)
    screenshot = Image.new("RGB", (600, 200), (245, 246, 248))
    font = ImageFont.truetype(str(scaling.FONT), 26)
    ImageDraw.Draw(screenshot).text((40, 80), "Old text", fill=(20, 20, 20), font=font)
    path = tmp_path / "shot.png"
    screenshot.save(path)
    found = structured(call(server, "find_text_lines", {"path": str(path)}))
    if not found["lines"]:
        pytest.skip(found.get("hint", "no tiny OCR model here"))
    marks = [{"polygon": line, "pad": 3} for line in found["lines"]]
    result = structured(
        call(
            server,
            "create_fixture",
            {
                "recipe": {
                    "label": "benign",
                    "layers": [{"kind": "heal", "strokes": marks}],
                },
                "background_image": str(path),
            },
        )
    )
    with Image.open(result["image"]) as image:
        pixels = image.convert("RGB")
    assert pixels.size == (600, 200)  # the canvas takes the image's size
    assert {pixels.getpixel((x, 93)) for x in range(40, 140)} == {(245, 246, 248)}


def test_cloud_scans_need_the_opt_in(tmp_path):
    server = build_server(tmp_path)
    path = tmp_path / "plain.png"
    Image.new("RGB", (20, 20), "white").save(path)
    result = call(
        server, "scan_image", {"path": str(path), "configuration": "cloud-google"}
    )
    assert result.is_error and "--allow-cloud" in result.content[0].text
    assert call(server, "read_image", {"path": str(tmp_path / "missing.png")}).is_error


def test_command_options():
    args = build_parser().parse_args(["--output", "out", "--allow-cloud"])
    assert str(args.output) == "out" and args.allow_cloud
