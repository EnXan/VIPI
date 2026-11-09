"""Group catalog entries whose images or texts look nearly the same.

Grouping only orders the Label tab for review; it never changes the catalog.
Two entries are similar when their word sets overlap by at least
``TEXT_OVERLAP`` (Jaccard), or when their 256-bit difference hashes differ in at
most ``IMAGE_DISTANCE`` bits and their texts do not contradict that: one has no
text or they overlap by at least ``IMAGE_TEXT_OVERLAP``. These are the rules of
the near-duplicate cleanup; without the text check, plain text-on-white images
all look alike. Each entry joins the first group whose first entry it is
similar to, so templated texts do not chain into one huge group.
"""

import re

from PIL import Image

HASH_SIZE = 16
IMAGE_DISTANCE = 20
TEXT_OVERLAP = 0.8
IMAGE_TEXT_OVERLAP = 0.5
MIN_WORDS = 3


def image_hash(path):
    """Difference hash: compares neighbouring pixels of a 17x16 grey thumbnail."""
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((HASH_SIZE + 1, HASH_SIZE)).getdata())
    value = 0
    for row in range(HASH_SIZE):
        for column in range(HASH_SIZE):
            left = pixels[row * (HASH_SIZE + 1) + column]
            value = (value << 1) | (left > pixels[row * (HASH_SIZE + 1) + column + 1])
    return value


def words(entry):
    text = (entry.get("ocr_reference") or {}).get("text") or entry.get("payload") or ""
    return frozenset(re.findall(r"\w+", text.casefold()))


def overlap(words_a, words_b):
    union = words_a | words_b
    return len(words_a & words_b) / len(union) if union else 1.0


def similar(first, second):
    hash_a, words_a = first
    hash_b, words_b = second
    texts = len(words_a) >= MIN_WORDS and len(words_b) >= MIN_WORDS
    if texts and overlap(words_a, words_b) >= TEXT_OVERLAP:
        return True
    if hash_a is None or hash_b is None:
        return False
    if (hash_a ^ hash_b).bit_count() > IMAGE_DISTANCE:
        return False
    return not texts or overlap(words_a, words_b) >= IMAGE_TEXT_OVERLAP


def groups(features):
    """Group ids from ``{id: (image_hash or None, words)}``.

    Returns lists of ids, larger groups first; ties and single entries keep
    the input order.
    """
    found = []
    for identifier, feature in features.items():
        for members in found:
            if similar(features[members[0]], feature):
                members.append(identifier)
                break
        else:
            found.append([identifier])
    return sorted(found, key=len, reverse=True)


def text_templates(entries):
    """Group entries whose texts overlap by ``TEXT_OVERLAP``; texts only.

    Entries with fewer than ``MIN_WORDS`` words stay single. Returns lists of
    ids, larger groups first.
    """
    return groups(
        {
            entry["id"]: (
                None,
                words(entry) if len(words(entry)) >= MIN_WORDS else frozenset(),
            )
            for entry in entries
        }
    )
