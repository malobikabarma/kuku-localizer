"""QA layer. Most checks are plain code (repeatable, free, testable). One LLM judge call per episode
checks whether the hook and the cliffhanger survived, and points out lines that read like literal translation."""
import json
import re
from difflib import SequenceMatcher

import llm
import screenplay as sp
import timing
from config import settings

SEVERITY = {"missing": "high", "latin_name": "high", "variant": "high", "hook": "high", "cliffhanger": "high",
            "timing": "medium", "script": "medium", "name_dropped": "low", "register": "low", "natural": "low"}
LABELS = {"missing": "Missing line", "latin_name": "Name left in English", "variant": "Name spelled differently",
          "hook": "Hook weakened", "cliffhanger": "Cliffhanger weakened", "timing": "Too long for timing",
          "script": "Not in target script", "name_dropped": "Name dropped", "register": "Aap/tum switch",
          "natural": "Sounds literal"}
LATIN_TARGETS = {"english", "spanish", "french", "portuguese", "german", "indonesian", "hinglish", "italian", "swahili"}
_PUNCT = "।॥,.!?…\"'“”‘’—–-:;()[]"

REGISTER = {"aap": {"आप", "आपको", "आपका", "आपकी", "आपके", "आपने", "आपसे"},
            "tum": {"तुम", "तुम्हें", "तुम्हारा", "तुम्हारी", "तुम्हारे", "तुमने", "तुमसे", "तुमको"},
            "tu": {"तू", "तुझे", "तेरा", "तेरी", "तेरे", "तूने", "तुझसे"}}


def flag(line_id, kind, reason, source="code"):
    return {"id": line_id, "type": kind, "label": LABELS.get(kind, kind), "severity": SEVERITY.get(kind, "low"),
            "reason": reason, "source": source}


def _tokens(text):
    return [t.strip(_PUNCT) for t in (text or "").split() if t.strip(_PUNCT)]


def _latin_share(text):
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if c.isascii()) / len(letters) if letters else 0.0


def _mentions(text, form):
    return re.search(r"(?<![A-Za-z])" + re.escape(form) + r"(?![A-Za-z])", text, flags=re.I) is not None


# ------------------------------------------------------------------ code checks
def check_timing(ep, targets):
    flags, stats = [], {}
    rate = settings.max_rate
    unit = "syl" if settings.timing_unit == "syllables" else "words"
    for l in ep.dialogue:
        t = targets.get(l.id, "")
        if not t:
            continue
        c = timing.check(t, l.duration)
        stats[l.id] = c
        if not c["fits"]:
            over = c["needed_sec"] / max(l.duration, 0.1) - 1
            flags.append(flag(l.id, "timing", f"{c['units']} {unit} needs ~{c['needed_sec']:.1f}s at {rate:g} {unit}/s; "
                                              f"window is {l.duration:.1f}s (+{over:.0%}). Budget: {c['budget']} {unit}."))
    return flags, stats


def check_missing_and_script(ep, targets, lang):
    flags = []
    non_latin = lang.strip().lower() not in LATIN_TARGETS
    for l in ep.dialogue:
        t = (targets.get(l.id) or "").strip()
        if not t:
            flags.append(flag(l.id, "missing", "No adaptation was produced for this line."))
            continue
        if t.lower() == l.text.lower() and len(l.text.split()) > 1:
            flags.append(flag(l.id, "missing", "The line is identical to the English: it was not adapted."))
        elif non_latin and _latin_share(t) > 0.4:
            flags.append(flag(l.id, "script", f"{_latin_share(t):.0%} of the letters are Latin; expected {lang} script."))
    return flags


_NORM = str.maketrans({"ी": "ि", "ू": "ु", "ै": "े", "ौ": "ो", "ई": "इ", "ऊ": "उ", "ऐ": "ए", "औ": "ओ",
                       "़": None, "ं": None, "ँ": None})


def _norm(word: str) -> str:
    """Folds the spellings Hindi writers most often confuse: vowel length, nukta, nasal marks."""
    return word.translate(_NORM)


def _is_variant(tok: str, word: str) -> bool:
    if tok == word or len(word) < 3 or tok[:1] != word[:1] or tok.startswith(word) or word.startswith(tok):
        return False      # identical, too short, or an inflection like पिता / पिताजी
    if _norm(tok) == _norm(word):
        return True       # जुलियाना vs जूलियाना, मिरा vs मीरा, रौहन vs रोहन
    # fuzzy match only for long names: for short ones it would hit real words (मरा "died" vs मीरा)
    return len(word) >= 6 and SequenceMatcher(None, _norm(tok), _norm(word)).ratio() >= 0.8


def check_names(ep, targets, entries, lang):
    """Glossary consistency: names present, spelled exactly as approved, never left in English."""
    flags = []
    non_latin = lang.strip().lower() not in LATIN_TARGETS
    approved_words = {w for e in entries for t in e.targets for w in _tokens(t)}
    for l in ep.dialogue:
        t = targets.get(l.id, "")
        if not t:
            continue
        # 1) spelling variants of approved names (e.g. जुलियाना vs जूलियाना)
        varied = set()
        for tok in dict.fromkeys(_tokens(t)):
            if tok in approved_words:
                continue
            match = next(((e, w) for e in entries for target in e.targets for w in _tokens(target) if _is_variant(tok, w)), None)
            if match:
                e, w = match
                varied.add(e.english)
                flags.append(flag(l.id, "variant", f"'{tok}' looks like a misspelling of the approved '{w}' ({e.english})."))
        # 2) names mentioned in English must appear in the approved spelling
        for e in entries:
            if not e.targets or e.english in varied:
                continue
            hit = next((f for f in e.english_forms if _mentions(l.text, f)), None)
            if hit and not any(x in t for x in e.targets):
                if non_latin and _mentions(t, hit):
                    flags.append(flag(l.id, "latin_name", f"'{hit}' is still in English. Use '{e.targets[0]}'."))
                elif e.kind == "character":
                    flags.append(flag(l.id, "name_dropped", f"English says '{hit}' but '{e.targets[0]}' is not in the line. "
                                                            "Fine if dropped on purpose for timing."))
    return flags


def check_register(ep, targets, lang, cast=None):
    """Hindi only: a speaker switching between aap and tum inside one scene is often an error."""
    if lang.strip().lower() != "hindi":
        return []
    cast = cast or {}
    by_key = {}
    for l in ep.dialogue:
        toks = set(_tokens(targets.get(l.id, "")))
        for reg, forms in REGISTER.items():
            if toks & forms:
                by_key.setdefault((l.scene, cast.get(l.speaker, l.speaker)), []).append((l.id, reg))
    flags = []
    for (scene, who), uses in by_key.items():
        regs = {r for _, r in uses}
        if len(regs) > 1:
            counts = {r: sum(1 for _, x in uses if x == r) for r in regs}
            main = max(counts, key=counts.get)
            for lid, r in uses:
                if r != main:
                    flags.append(flag(lid, "register", f"{who.title()} mostly uses '{main}' in this scene but '{r}' here. "
                                                       "Check who is being addressed."))
    return flags


def code_checks(ep, targets, entries, lang, cast=None):
    timing_flags, stats = check_timing(ep, targets)
    flags = (check_missing_and_script(ep, targets, lang) + check_names(ep, targets, entries, lang)
             + timing_flags + check_register(ep, targets, lang, cast))
    return flags, stats


def fit_rate(ep, targets):
    spoken = [l for l in ep.dialogue if targets.get(l.id)]
    if not spoken:
        return 0.0
    return sum(timing.check(targets[l.id], l.duration)["fits"] for l in spoken) / len(spoken)


# ------------------------------------------------------------------ LLM judge
JUDGE_SYSTEM = """You review a {lang} dub of one English microdrama episode. Microdramas live or die on two moments:
the HOOK (opening lines that grab the viewer) and the CLIFFHANGER (closing lines that make them watch the next episode).
1. Does the {lang} hook keep the shock, intrigue or emotional punch of the English hook?
2. Does the {lang} cliffhanger keep the unresolved tension, reveal or threat of the English one?
3. List up to 8 lines anywhere in the episode that sound like literal translation, use an idiom wrongly, use the wrong
   level of respect (e.g. aap/tum), or would sound unnatural from an actor. Give a better line for each.
Be strict but fair. If it works, say so.
Return JSON: {{"hook_preserved": true/false, "hook_reason": "...", "hook_fix": "better line or empty",
"cliffhanger_preserved": true/false, "cliffhanger_reason": "...", "cliffhanger_fix": "better line or empty",
"unnatural_lines": [{{"id": "L001", "reason": "...", "suggestion": "..."}}]}}"""


def judge(ep, targets, lang, n_edge: int = 3):
    spoken = [l for l in ep.dialogue if targets.get(l.id)]
    if len(spoken) < 2:
        return {"ran": False, "reason": "Not enough adapted lines to judge."}
    pair = lambda l: {"id": l.id, "speaker": l.speaker, "emotion": l.emotion, "english": l.text, "target": targets[l.id]}
    payload = {"logline": ep.meta.get("episode_logline", ""),
               "hook": [pair(l) for l in spoken[:n_edge]],
               "cliffhanger": [pair(l) for l in spoken[-n_edge:]],
               "last_actions": [l.text for l in ep.lines if l.kind in ("action", "camera", "sfx")][-3:],
               "all_lines": [pair(l) for l in spoken]}
    data = llm.call_json(JUDGE_SYSTEM.format(lang=lang), "INPUT_JSON: " + json.dumps(payload, ensure_ascii=False),
                         task="judge", temperature=0.0)
    if not isinstance(data, dict):
        return {"ran": False, "reason": "The judge returned an unexpected format."}
    return {"ran": True,
            "hook_preserved": bool(data.get("hook_preserved", True)), "hook_reason": str(data.get("hook_reason", "")),
            "hook_fix": str(data.get("hook_fix", "") or ""),
            "cliffhanger_preserved": bool(data.get("cliffhanger_preserved", True)),
            "cliffhanger_reason": str(data.get("cliffhanger_reason", "")),
            "cliffhanger_fix": str(data.get("cliffhanger_fix", "") or ""),
            "unnatural_lines": [u for u in data.get("unnatural_lines", []) if isinstance(u, dict) and u.get("id")],
            "hook_ids": [l.id for l in spoken[:n_edge]], "cliffhanger_ids": [l.id for l in spoken[-n_edge:]]}


def judge_flags(j):
    if not j.get("ran"):
        return []
    flags = []
    if not j["hook_preserved"]:
        fix = f" Try: {j['hook_fix']}" if j.get("hook_fix") else ""
        flags.append(flag(j["hook_ids"][0], "hook", j["hook_reason"] + fix, "ai"))
    if not j["cliffhanger_preserved"]:
        fix = f" Try: {j['cliffhanger_fix']}" if j.get("cliffhanger_fix") else ""
        flags.append(flag(j["cliffhanger_ids"][-1], "cliffhanger", j["cliffhanger_reason"] + fix, "ai"))
    for u in j.get("unnatural_lines", []):
        tip = f" Try: {u['suggestion']}" if u.get("suggestion") else ""
        flags.append(flag(str(u["id"]), "natural", str(u.get("reason", "")) + tip, "ai"))
    return flags


def sort_flags(flags, ep):
    order = {l.id: i for i, l in enumerate(ep.lines)}
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(flags, key=lambda f: (order.get(f["id"], 1e9), rank.get(f["severity"], 3)))
