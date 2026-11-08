"""Dubbing-fit heuristics. A line 'fits' when its estimated spoken length fits the original time window.

Syllables are counted per akshara for Indic scripts (Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil,
Telugu, Kannada, Malayalam all share the same Unicode layout), and per vowel group for Latin text.
This is a heuristic, not real audio duration. Calibrate MAX_SYLLABLES_PER_SEC by reading lines aloud."""
import math
import re

from config import settings

_LATIN_VOWELS = re.compile(r"[aeiouy]+", re.I)


def count_words(text: str) -> int:
    # split on whitespace: \w misses Indic vowel signs, so a regex word count breaks Hindi words apart
    return sum(1 for tok in (text or "").split() if any(c.isalpha() for c in tok))


def _indic_offset(ch: str):
    cp = ord(ch)
    if 0x0900 <= cp <= 0x0D7F:
        return cp - (cp & ~0x7F)
    return None


SCHWA_BLOCKS = {0x0900, 0x0980, 0x0A00, 0x0A80, 0x0B00}   # scripts where a word-final consonant drops its vowel


def _indic_word_syllables(word: str) -> int:
    n, chars = 0, list(word)
    for i, ch in enumerate(chars):
        off = _indic_offset(ch)
        if off is None:
            continue
        nxt = _indic_offset(chars[i + 1]) if i + 1 < len(chars) else None
        nxt2 = _indic_offset(chars[i + 2]) if i + 2 < len(chars) else None
        if 0x04 <= off <= 0x14 or off in (0x60, 0x61):            # independent vowel
            n += 1
        elif 0x15 <= off <= 0x39 or 0x58 <= off <= 0x5F:           # consonant
            if nxt == 0x4D or (nxt == 0x3C and nxt2 == 0x4D):        # + virama: joins the next syllable
                continue
            rest = [o for o in (_indic_offset(c) for c in chars[i + 1:]) if o is not None and o != 0x3C]
            word_final = not rest
            if word_final and n > 0 and (ord(ch) & ~0x7F) in SCHWA_BLOCKS:
                continue                                              # Hindi schwa deletion: राम = 1 syllable
            n += 1
    return n


def count_syllables(text: str) -> int:
    total = 0
    for tok in (text or "").split():
        if any(_indic_offset(c) is not None for c in tok):
            total += _indic_word_syllables(tok)
            tok = "".join(c for c in tok if _indic_offset(c) is None)
        for word in re.findall(r"[A-Za-z']+", tok):
            w = word.lower().strip("'")
            if not w:
                continue
            n = len(_LATIN_VOWELS.findall(w))
            if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
                n -= 1
            total += max(1, n)
    return total


def units(text: str, unit: str | None = None) -> int:
    unit = unit or settings.timing_unit
    return count_syllables(text) if unit == "syllables" else count_words(text)


def needed_seconds(text: str, unit: str | None = None, rate: float | None = None) -> float:
    rate = rate or (settings.max_syllables_per_sec if (unit or settings.timing_unit) == "syllables" else settings.max_words_per_sec)
    return units(text, unit) / rate


def budget(duration: float, unit: str | None = None, rate: float | None = None) -> int:
    """Max units that fit the window (including the grace allowance). Never below 1."""
    unit = unit or settings.timing_unit
    rate = rate or (settings.max_syllables_per_sec if unit == "syllables" else settings.max_words_per_sec)
    return max(1, math.floor((max(duration, 0.1) + settings.timing_grace_sec) * rate))


def word_budget(duration: float) -> int:
    return max(1, math.floor((max(duration, 0.1) + settings.timing_grace_sec) * settings.max_words_per_sec))


def check(text: str, duration: float) -> dict:
    """Returns the numbers the UI and QA report need for one line."""
    n = units(text)
    b = budget(duration)
    need = needed_seconds(text)
    return {"units": n, "budget": b, "needed_sec": round(need, 2), "window_sec": round(duration, 2),
            "usage": round(need / (max(duration, 0.1) + settings.timing_grace_sec), 2), "fits": n <= b}
