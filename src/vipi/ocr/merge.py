"""Choose observed OCR readings and assemble page text in reading order."""

from bisect import bisect_right

from .merge_geometry import (
    bounds,
    candidate_match as candidate_match,
    group_locations,
    levenshtein,
    line_candidates,
    line_polygon,
    location_match,
    rectangle,
    similarity,
)

ASSEMBLY_VERSION = 6
TERMINAL_PUNCTUATION = ".,;:!?"


def evidence(candidate):
    """Keep the recognition evidence needed to explain one reading choice."""
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
        if (
            text == chosen["text"]
            or text.rstrip(TERMINAL_PUNCTUATION) != chosen["text"]
        ):
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
    """Choose a recognized line while retaining supported alternatives."""
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


def additions_to_line(chosen, candidates, other_words=()):
    """Add corroborated words that extend, but do not alter, a chosen line."""
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
                if any(
                    location_match(word["input_polygon"], other["input_polygon"])
                    and similarity(word["text"], other["text"]) >= 0.75
                    for other in other_words
                ):
                    continue
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


def whitespace_groups(items, axis):
    """Separate boxes only where a whitespace gap crosses the whole block."""
    groups, end = [], None
    for item in sorted(items, key=lambda item: bounds(item["input_polygon"])[axis]):
        box = bounds(item["input_polygon"])
        if end is None or box[axis] >= end:
            groups.append([])
        groups[-1].append(item)
        end = max(end, box[axis + 2]) if end is not None else box[axis + 2]
    return groups


def reading_rows(items):
    """Group text regions into rows using their vertical centers."""
    rows = []
    for item in sorted(
        items,
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
    return [
        sorted(row["items"], key=lambda item: bounds(item["input_polygon"])[0])
        for row in sorted(rows, key=lambda row: row["center"])
    ]


def reading_layout(items):
    """Read separate horizontal bands, then columns within connected bands."""
    rows = reading_rows(items)
    if len(rows) <= 1:
        return rows, []
    for axis in (1, 0):
        groups = whitespace_groups(items, axis)
        if len(groups) > 1:
            # A single label beside a paragraph is not evidence of parallel
            # paragraph flow. Keep such labels and aligned tables in row order.
            if axis == 0 and any(len(reading_rows(group)) <= 1 for group in groups):
                return rows, []
            layouts = [reading_layout(group) for group in groups]
            return (
                [row for rows, _ in layouts for row in rows],
                ([groups] if axis == 0 else [])
                + [columns for _, splits in layouts for columns in splits],
            )
    return rows, []


def split_columns(candidates):
    """Keep native word boundaries when another reading bridges known columns."""
    first_step = min((item["step_id"] for item in candidates), default=None)
    primary = [item for item in candidates if item["step_id"] == first_step]
    _, splits = reading_layout(primary)
    gutters = []
    for columns in splits:
        boxes = [bounds(line["input_polygon"]) for column in columns for line in column]
        top, bottom = min(box[1] for box in boxes), max(box[3] for box in boxes)
        for left, right in zip(columns, columns[1:]):
            edge = max(bounds(line["input_polygon"])[2] for line in left)
            start = min(bounds(line["input_polygon"])[0] for line in right)
            gutters.append((top, bottom, (edge + start) / 2))
    for candidate in candidates:
        words = candidate["words"]
        if any(word.get("level") != "word" for word in words):
            yield candidate
            continue
        word_boxes = [bounds(word["input_polygon"]) for word in words]
        box = bounds(candidate["input_polygon"])
        center = (box[1] + box[3]) / 2
        cuts = sorted(
            {
                cut
                for top, bottom, cut in gutters
                if top <= center <= bottom
                and box[0] < cut < box[2]
                and all(not left < cut < right for left, _, right, _ in word_boxes)
            }
        )
        if not cuts:
            yield candidate
            continue
        parts = {}
        for word, word_box in zip(words, word_boxes):
            column = bisect_right(cuts, (word_box[0] + word_box[2]) / 2)
            parts.setdefault(column, []).append(word)
        if len(parts) == 1:
            yield candidate
            continue
        for _, native_words in sorted(parts.items()):
            weight = sum(len(word["text"]) for word in native_words)
            yield {
                **candidate,
                "text": " ".join(word["text"] for word in native_words),
                "words": native_words,
                "polygon": line_polygon(word["polygon"] for word in native_words),
                "input_polygon": line_polygon(
                    word["input_polygon"] for word in native_words
                ),
                "confidence": sum(
                    len(word["text"]) * max(0, word["confidence"])
                    for word in native_words
                )
                / weight,
            }


def assemble(steps: list[dict]) -> tuple[str, list[dict]]:
    """Select observed OCR readings and assemble them in page reading order."""
    occurrences = []
    groups = group_locations(split_columns(line_candidates(steps)))
    selected = [choose_reading(candidates) for candidates in groups]
    _, splits = reading_layout([chosen for chosen, _ in selected])
    neighboring_words = {id(chosen): [] for chosen, _ in selected}
    for columns in splits:
        for column in columns:
            words = [
                word
                for other in columns
                if other is not column
                for line in other
                for word in line["words"]
            ]
            for chosen in column:
                neighboring_words[id(chosen)].extend(words)
    for candidates, (chosen, alternatives) in zip(groups, selected):
        additions = additions_to_line(chosen, candidates, neighboring_words[id(chosen)])
        chosen_box = bounds(chosen["input_polygon"])
        left_words = [
            word
            for word in additions
            if bounds(word["input_polygon"])[2] <= chosen_box[0]
        ]
        right_words = [
            word
            for word in additions
            if bounds(word["input_polygon"])[0] >= chosen_box[2]
        ]
        text = " ".join(
            [
                *(word["text"] for word in left_words),
                chosen["text"],
                *(word["text"] for word in right_words),
            ]
        )
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
    ordered, lines = [], []
    rows, _ = reading_layout(occurrences)
    for items in rows:
        ordered.extend(items)
        lines.append(" ".join(item["text"] for item in items))
    return "\n".join(lines), ordered
