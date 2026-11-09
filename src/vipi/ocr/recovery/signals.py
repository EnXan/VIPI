"""Local OCR-quality evidence and experimental priority policies.

Dataset references are evaluation labels, never inputs to these functions.
The default parameters are development hypotheses, not calibrated thresholds.
"""

from dataclasses import asdict, dataclass
from functools import cache
from importlib.util import find_spec
import re
import time
import unicodedata

from wordfreq import available_languages, zipf_frequency


@dataclass(frozen=True)
class Signal:
    name: str
    group: str
    priority: int
    state: str  # triggered, clear, unavailable
    evidence: dict


@dataclass(frozen=True)
class Parameters:
    short_characters: int = 40
    low_confidence: float = 0.8
    low_confidence_fraction: float = 0.3
    unknown_fraction: float = 0.5
    minimum_words: int = 3


@cache
def _known_word(word):
    scripts = {unicodedata.name(character, "").split(" ", 1)[0] for character in word}
    if scripts & {"CJK", "HIRAGANA", "KATAKANA", "HANGUL"}:
        if find_spec("jieba") is None or find_spec("MeCab") is None:
            return None
    # Start with common languages for speed; retaining the rest avoids treating
    # the first four as the whole set of languages the library can represent.
    available = set(available_languages())
    languages = [x for x in ("en", "de", "fr", "es") if x in available]
    languages += sorted(available - set(languages))
    for language in languages:
        try:
            if zipf_frequency(word, language) > 0:
                return True
        except (ImportError, ModuleNotFoundError):
            # Optional tokenizers are not installed for some scripts. An
            # unknown word remains a weak signal, never a security verdict.
            continue
    return False


def evidence(text, regions, groups, params=Parameters()):
    """Extract evidence without references or decisions from another model."""
    count = sum(not c.isspace() for c in text)
    yield Signal(
        "empty_text",
        "coverage",
        1,
        "triggered" if count == 0 else "clear",
        {"characters": count},
    )
    yield Signal(
        "short_text",
        "coverage",
        2,
        "triggered" if 0 < count < params.short_characters else "clear",
        {"characters": count, "threshold": params.short_characters},
    )

    scores = [r.get("confidence") for r in regions]
    scores = [
        float(v)
        for v in scores
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1
    ]
    if scores:
        low = sum(v < params.low_confidence for v in scores)
        ratio = low / len(scores)
        yield Signal(
            "low_confidence",
            "recognition",
            3,
            "triggered" if ratio >= params.low_confidence_fraction else "clear",
            {
                "low": low,
                "available": len(scores),
                "regions": len(regions),
                "fraction": ratio,
                "cutoff": params.low_confidence,
            },
        )
    else:
        yield Signal(
            "low_confidence", "recognition", 3, "unavailable", {"regions": len(regions)}
        )

    # Per-group and full-page evidence are both retained. Unicode alphabetic
    # tokens only; numeric identifiers and mixed alphanumeric codes are omitted.
    texts = [("page", text)] + [
        (f"group-{i + 1}", g.get("text", "")) for i, g in enumerate(groups)
    ]
    observations = []
    unavailable_words = 0
    for identifier, value in texts:
        words = [
            w
            for w in re.findall(r"[^\W_]+", value, re.UNICODE)
            if w.isalpha() and len(w) > 1
        ]
        if len(words) < params.minimum_words:
            continue
        findings = [_known_word(w.casefold()) for w in words]
        unavailable_words += sum(found is None for found in findings)
        checked = [found for found in findings if found is not None]
        if len(checked) < params.minimum_words:
            continue
        unknown = sum(found is False for found in checked)
        observations.append(
            {
                "region": identifier,
                "words": len(checked),
                "unknown": unknown,
                "fraction": unknown / len(checked),
            }
        )
    if observations:
        strongest = max(observations, key=lambda item: item["fraction"])
        yield Signal(
            "unknown_words",
            "linguistic",
            3,
            "triggered"
            if strongest["fraction"] >= params.unknown_fraction
            else "unavailable"
            if unavailable_words
            else "clear",
            {
                "strongest": strongest,
                "observations": observations,
                "languages": len(available_languages()),
                "unavailable_words": unavailable_words,
                "caveat": "word-frequency coverage is not universal; identifiers and rare valid words can be unknown",
            },
        )
    else:
        yield Signal(
            "unknown_words",
            "linguistic",
            3,
            "unavailable",
            {
                "reason": "insufficient supported alphabetic words",
                "unavailable_words": unavailable_words,
            },
        )


def route(text, regions, groups, strategy, params=Parameters()):
    """Return a routing hypothesis and auditable signal evidence.

    priority_cascade stops computing after the first triggered signal;
    any_signal computes all signals; corroborated requires both weak signals,
    while coverage signals still trigger independently.
    """
    if strategy not in {"priority_cascade", "any_signal", "corroborated"}:
        raise ValueError("Unknown signal strategy.")
    started = time.perf_counter()
    observations = []
    for signal in evidence(text, regions, groups, params):
        observations.append(signal)
        if strategy == "priority_cascade" and signal.state == "triggered":
            break
    triggered = [s for s in observations if s.state == "triggered"]
    unavailable = [s.name for s in observations if s.state == "unavailable"]
    if strategy == "corroborated":
        flagged = (
            any(s.group == "coverage" for s in triggered)
            or len([s for s in triggered if s.priority == 3]) >= 2
        )
    else:
        flagged = bool(triggered)
    return {
        "strategy": strategy,
        "route": "inspect" if flagged else "unresolved" if unavailable else "no_signal",
        "signals": [asdict(s) for s in observations],
        "unavailable": unavailable,
        "elapsed_seconds": time.perf_counter() - started,
    }
