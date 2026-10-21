"""Select observed readings per location; retain competing readings separately."""

from functools import lru_cache

ASSEMBLY_VERSION = 4
TERMINAL_PUNCTUATION = ".,;:!?"


def bounds(polygon):
    xs, ys = zip(*polygon)
    return min(xs), min(ys), max(xs), max(ys)


def rectangle(polygons):
    boxes = [bounds(polygon) for polygon in polygons]
    x, y = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, bottom = max(box[2] for box in boxes), max(box[3] for box in boxes)
    return [[x, y], [right, y], [right, bottom], [x, bottom]]


@lru_cache(maxsize=4096)
def levenshtein(first: str, second: str) -> int:
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for i, left in enumerate(first, 1):
        current = [i]
        for j, right in enumerate(second, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right))
            )
        previous = current
    return previous[-1]


def similarity(first: str, second: str) -> float:
    first, second = first.casefold(), second.casefold()
    return 1 - levenshtein(first, second) / max(1, len(first), len(second))


def location_match(first, second):
    a, b = bounds(first), bounds(second)
    ah, bh = max(1, a[3] - a[1]), max(1, b[3] - b[1])
    centers = abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)
    if centers > min(ah, bh) * 0.65:
        return 0
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    fraction = overlap / max(1, min(a[2] - a[0], b[2] - b[0]))
    return fraction if fraction >= 0.5 else 0


def line_candidates(steps):
    candidates = []
    for step in steps:
        groups = {}
        for i, word in enumerate(step["regions"]):
            if not word["text"].strip():
                continue
            line_id = word.get("line_id")
            key = ("line", line_id) if line_id is not None else ("region", i)
            groups.setdefault(key, []).append(word)
        raw_lines = [line for line in step.get("text", "").splitlines() if line.strip()]
        for i, words in enumerate(groups.values()):
            text = (
                raw_lines[i]
                if len(raw_lines) == len(groups)
                else " ".join(word["text"] for word in words)
            )
            weight = sum(len(word["text"]) for word in words)
            confidence = (
                sum(len(word["text"]) * max(0, word["confidence"]) for word in words)
                / weight
            )
            candidates.append(
                {
                    "text": " ".join(text.split()),
                    "words": words,
                    "polygon": rectangle(word["polygon"] for word in words),
                    "input_polygon": rectangle(word["input_polygon"] for word in words),
                    "confidence": confidence,
                    "step_id": step["id"],
                    "view_id": step.get("view_id", step["id"]),
                    "vote_id": step.get(
                        "raster_sha256", step.get("view_id", step["id"])
                    ),
                    "ordinal": i,
                }
            )
    return candidates


def group_locations(candidates):
    groups = []
    # A reliable observation anchors each location. Bounds never expand
    # transitively, so oversized boxes cannot bridge neighboring lines/columns.
    for candidate in sorted(
        candidates,
        key=lambda item: (-item["confidence"], item["step_id"], item["ordinal"]),
    ):
        matches = [
            (location_match(candidate["input_polygon"], group[0]["input_polygon"]), i)
            for i, group in enumerate(groups)
        ]
        score, index = max(matches, default=(0, 0))
        if score:
            groups[index].append(candidate)
        else:
            # A coarse OCR box may cover several established lines. Keep that
            # reading as evidence instead of emitting a third overlapping line.
            box = bounds(candidate["input_polygon"])
            covered = []
            for i, group in enumerate(groups):
                anchor = bounds(group[0]["input_polygon"])
                horizontal = max(0, min(box[2], anchor[2]) - max(box[0], anchor[0]))
                vertical = max(0, min(box[3], anchor[3]) - max(box[1], anchor[1]))
                if (
                    horizontal >= min(box[2] - box[0], anchor[2] - anchor[0]) * 0.5
                    and vertical >= (anchor[3] - anchor[1]) * 0.7
                ):
                    covered.append(
                        (abs((box[1] + box[3]) - (anchor[1] + anchor[3])), i)
                    )
            if len(covered) > 1:
                groups[min(covered)[1]].append(candidate)
            else:
                groups.append([candidate])
    return groups


def evidence(candidate):
    return {
        key: candidate[key]
        for key in (
            "step_id",
            "view_id",
            "text",
            "polygon",
            "input_polygon",
            "confidence",
        )
    }


def retain_terminal_punctuation(chosen, candidates):
    """Prefer a credible observed ending over omission, without editing a string.

    Only complete readings with the same body qualify. Confidence comes from
    the affected native word, so an unrelated uncertain word cannot erase an
    otherwise confident ending. An existing punctuation choice is left intact.
    """
    if not chosen.get("words") or chosen["text"].endswith(tuple(TERMINAL_PUNCTUATION)):
        return chosen
    anchor = chosen["words"][-1]
    if anchor.get("level") != "word":
        return chosen
    options = []
    for candidate in candidates:
        text = candidate["text"]
        if text == chosen["text"] or text.rstrip(TERMINAL_PUNCTUATION) != chosen["text"]:
            continue
        word = candidate["words"][-1]
        if (
            word.get("level") == "word"
            and word["text"].rstrip(TERMINAL_PUNCTUATION) == anchor["text"]
            and location_match(word["input_polygon"], anchor["input_polygon"])
            and word["confidence"] >= anchor["confidence"] - 0.02
        ):
            options.append(candidate)
    return max(
        options,
        key=lambda item: (item["words"][-1]["confidence"], item["confidence"]),
        default=chosen,
    )


def choose_reading(candidates):
    readings = {}
    for candidate in candidates:
        readings.setdefault(candidate["text"], []).append(candidate)

    def score(text):
        views, exact = {}, {}
        for candidate in candidates:
            view = candidate.get("vote_id", candidate["view_id"])
            value = similarity(text, candidate["text"]) ** 2 * candidate["confidence"]
            views[view] = max(views.get(view, 0), value)
            if candidate["text"] == text:
                exact[view] = max(exact.get(view, 0), candidate["confidence"])
        return sum(views.values()), sum(exact.values()), len(exact)

    # Identical rasters contribute at most one vote. A selected string must
    # have been recognized: no dictionary, invented spelling or reference.
    chosen_text = max(readings, key=score)
    chosen = min(
        readings[chosen_text],
        key=lambda item: (-item["confidence"], item["step_id"], item["ordinal"]),
    )
    chosen = retain_terminal_punctuation(chosen, candidates)
    chosen_text = chosen["text"]
    alternatives = []
    for text, observations in readings.items():
        if text == chosen_text:
            continue
        alternatives.append(
            {
                "text": text,
                "support": len(
                    {item.get("vote_id", item["view_id"]) for item in observations}
                ),
                "confidence": max(item["confidence"] for item in observations),
                "edit_distance": levenshtein(chosen_text, text),
                "step_ids": sorted({item["step_id"] for item in observations}),
            }
        )
    alternatives.sort(
        key=lambda item: (-item["support"], -item["confidence"], item["text"])
    )
    return chosen, alternatives


def additions_to_line(chosen, candidates):
    selected_box = bounds(chosen["input_polygon"])
    additions = []
    for candidate in candidates:
        anchored = any(
            location_match(word["input_polygon"], anchor["input_polygon"])
            and similarity(word["text"], anchor["text"]) >= 0.75
            for word in candidate["words"]
            for anchor in chosen["words"]
        )
        if not anchored:
            continue
        for i, word in enumerate(candidate["words"]):
            if word.get("level") != "word":
                continue
            box = bounds(word["input_polygon"])
            # Extend a partially recognized line without splicing replacements
            # or arbitrary fragments inside an already covered text span.
            if box[2] <= selected_box[0] or box[0] >= selected_box[2]:
                additions.append(
                    {
                        **word,
                        "text": " ".join(word["text"].split()),
                        "step_id": candidate["step_id"],
                        "view_id": candidate["view_id"],
                        "vote_id": candidate.get("vote_id", candidate["view_id"]),
                        "ordinal": i,
                    }
                )
    selected = [choose_reading(group)[0] for group in group_locations(additions)]
    return sorted(selected, key=lambda word: bounds(word["input_polygon"])[0])


def assemble(steps: list[dict]) -> tuple[str, list[dict]]:
    occurrences = []
    for candidates in group_locations(line_candidates(steps)):
        chosen, alternatives = choose_reading(candidates)
        additions = additions_to_line(chosen, candidates)
        left = [
            word["text"]
            for word in additions
            if bounds(word["input_polygon"])[2] <= bounds(chosen["input_polygon"])[0]
        ]
        right = [
            word["text"]
            for word in additions
            if bounds(word["input_polygon"])[0] >= bounds(chosen["input_polygon"])[2]
        ]
        text = " ".join([*left, chosen["text"], *right])
        left_words = [
            word
            for word in additions
            if bounds(word["input_polygon"])[2] <= bounds(chosen["input_polygon"])[0]
        ]
        right_words = [
            word
            for word in additions
            if bounds(word["input_polygon"])[0] >= bounds(chosen["input_polygon"])[2]
        ]
        occurrences.append(
            {
                "text": text,
                "level": "line",
                "input_polygon": rectangle(
                    [
                        chosen["input_polygon"],
                        *(word["input_polygon"] for word in additions),
                    ]
                ),
                "selected_step_id": chosen["step_id"],
                "words": [*left_words, *chosen["words"], *right_words],
                "support": len(
                    {
                        item.get("vote_id", item["view_id"])
                        for item in candidates
                        if item["text"] == chosen["text"]
                    }
                ),
                "evidence": [evidence(item) for item in candidates],
                "alternatives": [item for item in alternatives if item["text"] != text],
                "additions": [evidence(word) for word in additions],
            }
        )
    rows = []
    for item in sorted(
        occurrences,
        key=lambda item: (
            bounds(item["input_polygon"])[1],
            bounds(item["input_polygon"])[0],
            item["text"],
        ),
    ):
        box = bounds(item["input_polygon"])
        center, height = (box[1] + box[3]) / 2, max(1, box[3] - box[1])
        row = next(
            (
                row
                for row in rows
                if abs(row["center"] - center) <= min(row["height"], height) / 2
            ),
            None,
        )
        if row is None:
            rows.append({"center": center, "height": height, "items": [item]})
        else:
            row["items"].append(item)
    ordered, lines = [], []
    # Row insertion order follows top edges. A tall box in another column can
    # create a lower-baseline row before a short line above it is encountered.
    for row in sorted(rows, key=lambda row: row["center"]):
        items = sorted(row["items"], key=lambda item: bounds(item["input_polygon"])[0])
        ordered.extend(items)
        lines.append(" ".join(item["text"] for item in items))
    return "\n".join(lines), ordered
