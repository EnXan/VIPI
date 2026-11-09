"""Match OCR observations using their image-space geometry."""

from functools import lru_cache
from math import hypot


def bounds(polygon):
    """Return the axis-aligned bounds of a polygon."""
    xs, ys = zip(*polygon)
    return min(xs), min(ys), max(xs), max(ys)


def rectangle(polygons):
    """Return one axis-aligned polygon enclosing all supplied polygons."""
    boxes = [bounds(polygon) for polygon in polygons]
    x, y = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, bottom = max(box[2] for box in boxes), max(box[3] for box in boxes)
    return [[x, y], [right, y], [right, bottom], [x, bottom]]


def line_polygon(polygons):
    """Enclose native words without discarding their text-line orientation."""
    polygons = list(polygons)
    if len(polygons) > 1:
        first = [
            sum(point[axis] for point in polygons[0]) / len(polygons[0])
            for axis in (0, 1)
        ]
        last = [
            sum(point[axis] for point in polygons[-1]) / len(polygons[-1])
            for axis in (0, 1)
        ]
        dx, dy = last[0] - first[0], last[1] - first[1]
    else:
        dx = polygons[0][1][0] - polygons[0][0][0]
        dy = polygons[0][1][1] - polygons[0][0][1]
    length = hypot(dx, dy)
    if not length:
        return rectangle(polygons)
    ux, uy = dx / length, dy / length
    points = [(x * ux + y * uy, -x * uy + y * ux) for p in polygons for x, y in p]
    left, top = min(x for x, _ in points), min(y for _, y in points)
    right, bottom = max(x for x, _ in points), max(y for _, y in points)
    return [
        [x * ux - y * uy, x * uy + y * ux]
        for x, y in [(left, top), (right, top), (right, bottom), (left, bottom)]
    ]


@lru_cache(maxsize=4096)
def levenshtein(first: str, second: str) -> int:
    """Return the edit distance between two strings."""
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
    """Return normalized, case-insensitive text similarity."""
    first, second = first.casefold(), second.casefold()
    return 1 - levenshtein(first, second) / max(1, len(first), len(second))


def box_match(a, b, *, require_overlap=True):
    """Score whether two axis-aligned boxes describe the same text line."""
    ah, bh = max(1, a[3] - a[1]), max(1, b[3] - b[1])
    centers = abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)
    if centers > min(ah, bh) * 0.65:
        return 0
    if not require_overlap:
        return 1
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    fraction = overlap / max(1, min(a[2] - a[0], b[2] - b[0]))
    return fraction if fraction >= 0.5 else 0


def location_match(first, second, *, require_overlap=True):
    """Compare two polygons while allowing slanted or rotated text lines."""
    a, b = bounds(first), bounds(second)
    if require_overlap and (
        a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
    ):
        return 0
    if all(p[0][1] == p[1][1] for p in (first, second)):
        return box_match(a, b, require_overlap=require_overlap)
    scores = []
    for anchor in (first, second):
        dx, dy = anchor[1][0] - anchor[0][0], anchor[1][1] - anchor[0][1]
        length = hypot(dx, dy)
        if not length:
            return 0
        ux, uy = dx / length, dy / length
        a, b = [
            bounds([(x * ux + y * uy, -x * uy + y * ux) for x, y in polygon])
            for polygon in (first, second)
        ]
        score = box_match(a, b, require_overlap=require_overlap)
        if not score:
            return 0
        scores.append(score)
    return min(scores)


def line_candidates(steps):
    """Group native OCR regions into line candidates with source geometry."""
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
                    "polygon": line_polygon(word["polygon"] for word in words),
                    "input_polygon": line_polygon(
                        word["input_polygon"] for word in words
                    ),
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


def candidate_match(candidate, group):
    """Score whether an OCR line belongs with an existing location group."""
    anchor = group[0]["input_polygon"]
    score = location_match(candidate["input_polygon"], anchor)
    if score or not candidate.get("words"):
        return score
    if not location_match(candidate["input_polygon"], anchor, require_overlap=False):
        return 0
    # A complete observation can connect fragments of the same physical line.
    # Require an actual word at the same coordinates, not just a broad box.
    return int(
        any(
            word["text"] == other["text"]
            and location_match(word["input_polygon"], other["input_polygon"])
            for word in candidate.get("words", ())
            if word.get("level") == "word"
            for observation in group
            for other in observation.get("words", ())
            if other.get("level") == "word"
        )
    )


def group_locations(candidates):
    """Group readings that refer to the same physical line in the source image."""
    groups = []
    # Anchor bounds stay fixed. Additional fragments need matching native words
    # on the same baseline; paragraph gutters are handled before grouping.
    for candidate in sorted(
        candidates,
        key=lambda item: (-item["confidence"], item["step_id"], item["ordinal"]),
    ):
        matches = [
            (candidate_match(candidate, group), i) for i, group in enumerate(groups)
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
