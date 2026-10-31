"""Restore missing whitespace between distinct native word boxes only."""

from vipi.ocr.merge import line_candidates, bounds


def restore(line):
    words = line["words"]
    text = line["text"]
    if len(words) < 2 or any(w.get("level") != "word" for w in words):
        return text
    if "".join("".join(w["text"].split()) for w in words) != "".join(text.split()):
        return text
    positions = [i for i, c in enumerate(text) if not c.isspace()]
    ends = []
    count = 0
    for word in words:
        count += len("".join(word["text"].split()))
        ends.append(count)
    inserts = []
    for i, end in enumerate(ends[:-1]):
        if end <= 0 or end >= len(positions):
            continue
        after, before = positions[end - 1], positions[end]
        if before != after + 1:
            continue
        a, b = bounds(words[i]["input_polygon"]), bounds(words[i + 1]["input_polygon"])
        # A visible gap and a following alphanumeric character support a word
        # boundary. Preserve every original non-space character verbatim.
        if (
            a[2] < b[0]
            and text[before].isalnum()
            and len(words[i]["text"]) >= 2
            and words[i]["text"][0] in "'`‘\"“"
            and words[i]["text"][-1] in "'`’\"”"
        ):
            inserts.append(before)
    for offset in reversed(inserts):
        text = text[:offset] + " " + text[offset:]
    return text


def adjust(step, groups):
    originals = line_candidates([step])
    result = []
    for group in groups:
        g = group.copy()
        indices = g["source_indices"]
        if g["type"] == "native_line" and len(indices) == 1:
            g["text"] = restore(originals[indices[0]])
        elif g["type"] == "ruled_row":
            g["text"] = " | ".join(restore(originals[i]) for i in indices)
        result.append(g)
    return result
