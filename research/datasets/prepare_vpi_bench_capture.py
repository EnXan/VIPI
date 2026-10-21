#!/usr/bin/env python3
"""Build a deterministic capture plan for VPI-Bench's published test pages."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research/datasets/data/external/VPI-Bench/vpi-bench"
OUTPUT = ROOT / "research/datasets/data/external/VPI-Bench/capture_plan.json"
PLATFORMS = {
    "/web/webplatform/": "amazon",
    "/web/webplatform1/": "booking",
    "/web/email/": "email",
    "/web/messenger/": "messenger",
}
EXCLUDED_PATHS = {"/web/webplatform2/"}  # BBC screenshots are intentionally out of OCR scope.


class VisibleTextParser(HTMLParser):
    """Extract HTML text while retaining paragraph and line breaks."""

    BLOCK_TAGS = {"address", "article", "br", "div", "li", "p", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def visible_text(markup: str) -> str:
    parser = VisibleTextParser()
    parser.feed(markup)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def main() -> None:
    by_url: dict[str, list[str]] = defaultdict(list)
    for path in sorted((SOURCE / "testcases/main_benchmark").rglob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        by_url[case["url"]].append(path.relative_to(ROOT).as_posix())

    plan = []
    for url, testcases in sorted(by_url.items()):
        parsed = urlparse(url)
        if parsed.netloc == "cua-framework.github.io" and parsed.path in EXCLUDED_PATHS:
            continue
        if parsed.netloc != "cua-framework.github.io" or parsed.path not in PLATFORMS:
            raise ValueError(f"Unexpected VPI-Bench URL: {url}")
        params = parse_qs(parsed.query)
        platform = PLATFORMS[parsed.path]
        source_id = params["id"][0]
        load_id = params.get("load", [None])[0]
        config_path = SOURCE / "web_platforms" / platform / f"{source_id}.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))

        if platform in {"amazon", "booking", "bbc"}:
            target_text = config["description"]
            marker = target_text[:50]
        elif platform == "email":
            selected = next(email for email in config["emails"] if str(email["id"]) == load_id)
            target_text = visible_text(selected["content"])
            paragraphs = [part.strip() for part in target_text.splitlines()]
            marker = max(paragraphs, key=len)[:60]
        else:
            selected = next(chat for chat in config["chats"] if str(chat["id"]) == load_id)
            target_text = "\n".join(message["message"] for message in selected["history"])
            marker = selected["history"][0]["message"][:50]

        case_ids = [
            json.loads((ROOT / testcase).read_text(encoding="utf-8"))["id"]
            for testcase in by_url[url]
        ]
        filename = f"{platform}_{source_id}"
        if load_id:
            filename = f"{platform}_{source_id}_load_{load_id}"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", filename):
            raise ValueError(f"Unsafe screenshot filename: {filename}")
        background_image = config.get("backgroundImage")
        background_path = config_path.parent / background_image if background_image else None
        plan.append(
            {
                "url": url,
                "platform": platform,
                "config": config_path.relative_to(ROOT).as_posix(),
                "testcase_ids": case_ids,
                "testcases": testcases,
                "screenshot": f"research/datasets/data/external/VPI-Bench/screenshots/{filename}.jpg",
                "expected_marker": marker,
                "source_target_text": target_text,
                "background_image": background_image,
                "background_image_exists_locally": (
                    background_path.is_file() if background_path else None
                ),
            }
        )

    screenshots = [item["screenshot"] for item in plan]
    if len(screenshots) != len(set(screenshots)):
        raise ValueError("Screenshot filename collision")
    OUTPUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Planned {len(plan)} unique screenshots for {sum(len(item['testcase_ids']) for item in plan)} active testcases: {OUTPUT}")


if __name__ == "__main__":
    main()
