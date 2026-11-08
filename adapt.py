"""Scene-by-scene adaptation (not literal translation) with per-line length budgets, plus a rewrite pass
that fixes only the lines QA flagged."""
import json

import glossary as gl
import llm
import screenplay as sp
import timing
from config import settings

LANG_NOTES = {
    "hindi": "Write everyday spoken Hindustani as heard in popular Hindi TV dramas and OTT shows, in Devanagari. "
             "Avoid shuddh/Sanskritised words (use 'शादी' not 'विवाह', 'माफ़ करना' not 'क्षमा करें') unless the character is "
             "formal on purpose. Common English loanwords people actually say are fine. Keep aap/tum/tu consistent with "
             "the relationship: elders, strangers and formal moments get 'आप'; intimates and insults get 'तुम'/'तू'.",
    "tamil": "Write natural spoken Tamil (not literary centamil), in Tamil script, as heard in Tamil TV serials.",
    "telugu": "Write natural spoken Telugu in Telugu script, as heard in Telugu TV serials.",
    "bengali": "Write natural spoken Bengali in Bengali script, as heard in Bengali TV serials.",
    "marathi": "Write natural spoken Marathi in Devanagari, as heard in Marathi TV serials.",
}

ADAPT_SYSTEM = """You are a senior dubbing writer adapting an English microdrama into {lang} for an audio/video platform
whose audience binges 2-minute episodes. Adapt, do not translate word for word: every line must sound like something
a {lang}-speaking actor would naturally say with the given emotion.
Rules:
1. Fit the time window. Each line has max_words and max_syllables; stay at or under them. Shorter is better than rushed.
2. Use the glossary spellings exactly for names and terms. Never invent new names.
3. Keep the dramatic function of each line: insults must sting, reveals must land, questions stay questions.
4. Lines that start or end with "..." are one sentence split across shots. Keep the split so each half is speakable
   in its own window and the two halves read as one sentence in {lang} word order.
5. O.S. means off-screen and V.O. means voice-over; lip sync matters less there but timing still applies.
6. No stage directions, quotes, transliteration or notes inside the lines.
{lang_note}
Return JSON: {{"lines": [{{"id": "L001", "target": "..."}}], "summary": "2 sentences: what happened in this scene and the emotional state at its end"}}"""

REWRITE_SYSTEM = """You fix individual lines of a {lang} dub of an English microdrama. Each line comes with the reason it
was flagged. Rewrite only what is needed:
- 'timing': make it shorter so it fits max_words/max_syllables, keeping meaning, emotion and any names.
- 'name' / 'variant': use the glossary spelling exactly.
- 'script' / 'missing': write the line fully in {lang} (native script).
- 'hook' / 'cliffhanger' / 'natural': make it land with the same punch as the English, in natural spoken {lang}.
Never make a line longer than its budget.
{lang_note}
Return JSON: {{"lines": [{{"id": "L001", "target": "..."}}]}}"""


def lang_note(lang: str) -> str:
    return LANG_NOTES.get(lang.strip().lower(), f"Write natural spoken {lang} in its native script.")


def line_spec(l: sp.Line, speaker_name: str | None = None) -> dict:
    return {"id": l.id, "speaker": speaker_name or l.speaker, "emotion": l.emotion, "delivery": l.delivery or "on-screen",
            "english": l.text, "window_sec": round(l.duration, 2),
            "max_words": timing.word_budget(l.duration), "max_syllables": timing.budget(l.duration, "syllables",
                                                                                       settings.max_syllables_per_sec)}


def adapt_scene(ep: sp.Episode, scene: int, entries, lang: str, prev_summary: str = "", cast=None, chunk: int = 30):
    """Returns ({line_id: target}, summary)."""
    cast = cast or {}
    scene_lines = [l for l in ep.lines if l.scene == scene]
    spoken = [l for l in scene_lines if l.kind == "dialogue"]
    if not spoken:
        return {}, prev_summary
    actions = [f"[{sp.fmt_time(l.start)}] {l.text}" for l in scene_lines if l.kind == "action"][:25]
    out, summary = {}, prev_summary
    for i in range(0, len(spoken), chunk):
        part = spoken[i:i + chunk]
        payload = {
            "series_context": {"logline": ep.meta.get("episode_logline", ""),
                               "continuity": ep.meta.get("continuity_notes", ""),
                               "previous_scene_summary": prev_summary,
                               "scene_heading": ep.scenes.get(scene, ""),
                               "actions_in_scene": actions,
                               "already_adapted_in_this_scene": [{"id": k, "target": v} for k, v in list(out.items())[-6:]]},
            "glossary": gl.for_prompt(entries),
            "lines": [line_spec(l, cast.get(l.speaker)) for l in part],
        }
        data = llm.call_json(ADAPT_SYSTEM.format(lang=lang, lang_note=lang_note(lang)),
                             "INPUT_JSON: " + json.dumps(payload, ensure_ascii=False), task="adapt")
        for item in (data.get("lines", []) if isinstance(data, dict) else []):
            if isinstance(item, dict) and item.get("id"):
                out[str(item["id"])] = str(item.get("target", "")).strip().strip('"“”')
        summary = (data.get("summary") if isinstance(data, dict) else "") or summary
    return out, summary


def revise_lines(items, entries, lang: str, ep: sp.Episode | None = None):
    """items: list of dicts {line: sp.Line, current: str, reasons: [str]}. Returns {id: new_target}."""
    if not items:
        return {}
    payload = {"logline": ep.meta.get("episode_logline", "") if ep else "",
               "glossary": gl.for_prompt(entries),
               "lines": [{**line_spec(it["line"]), "current": it["current"], "flagged_for": it["reasons"]} for it in items]}
    data = llm.call_json(REWRITE_SYSTEM.format(lang=lang, lang_note=lang_note(lang)),
                         "INPUT_JSON: " + json.dumps(payload, ensure_ascii=False), task="rewrite", temperature=0.3)
    return {str(i["id"]): str(i.get("target", "")).strip().strip('"“”')
            for i in (data.get("lines", []) if isinstance(data, dict) else []) if isinstance(i, dict) and i.get("id")}
