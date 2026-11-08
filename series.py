"""Series bible: who is who across episodes. Screenplays often label the same person differently
(LADY JULIANA / JULIANA, THE BEARDED STRANGER / ALEXANDER) and sometimes reuse one label for two people.
For dubbing that matters: one character must keep one voice artist for the whole show."""
import json
from collections import defaultdict

import llm
import screenplay as sp


def speaker_table(episodes, entries=None):
    """One row per (episode, speaker label): stats + a suggested character from the glossary aliases."""
    entries = entries or []
    alias = {}
    for e in entries:
        if e.kind == "character":
            for f in e.english_forms:
                alias.setdefault(f.upper(), e.english)
    rows = []
    for ep in sorted(episodes, key=lambda x: x.number):
        stats = defaultdict(lambda: {"lines": 0, "seconds": 0.0, "sample": ""})
        for l in ep.dialogue:
            s = stats[l.speaker]
            s["lines"] += 1
            s["seconds"] += l.duration
            if not s["sample"]:
                s["sample"] = l.text
        for label, s in stats.items():
            rows.append({"episode": ep.number, "label": label, "lines": s["lines"], "seconds": round(s["seconds"], 1),
                         "sample": s["sample"][:90], "character": alias.get(label, label.title()), "note": ""})
    return rows


CONTINUITY_SYSTEM = """You are the script supervisor of a microdrama series. Screenplays label speakers inconsistently.
For every (episode, label) pair decide which real character is speaking, using loglines, continuity notes, sample lines
and the known character list. The same label can mean DIFFERENT people in different episodes, and different labels can
mean the SAME person. Then list continuity problems a dubbing team must know about: label collisions, a character
apparently in two places, relationships that contradict earlier episodes, names spelled differently.
Return JSON: {"cast": [{"episode": 1, "label": "...", "character": "...", "confidence": "high|low", "note": "..."}],
"issues": [{"episodes": [2, 9], "severity": "high|medium|low", "issue": "...", "suggestion": "..."}]}"""


def ai_cast(episodes, entries):
    payload = {"characters": [{"name": e.english, "aliases": e.aliases, "note": e.note} for e in entries if e.kind == "character"],
               "episodes": []}
    for ep in sorted(episodes, key=lambda x: x.number):
        labels = defaultdict(list)
        for l in ep.dialogue:
            if len(labels[l.speaker]) < 3:
                labels[l.speaker].append(l.text)
        payload["episodes"].append({"episode": ep.number, "logline": ep.meta.get("episode_logline", ""),
                                    "continuity": ep.meta.get("continuity_notes", ""),
                                    "labels": [{"label": k, "sample_lines": v} for k, v in labels.items()]})
    data = llm.call_json(CONTINUITY_SYSTEM, "INPUT_JSON: " + json.dumps(payload, ensure_ascii=False),
                         task="continuity", temperature=0.0)
    return (data.get("cast", []) if isinstance(data, dict) else []), (data.get("issues", []) if isinstance(data, dict) else [])


def apply_ai_cast(rows, cast):
    lookup = {(int(c.get("episode", 0) or 0), str(c.get("label", "")).upper()): c for c in cast if isinstance(c, dict)}
    for r in rows:
        c = lookup.get((int(r["episode"]), r["label"]))
        if c and c.get("character"):
            r["character"] = c["character"]
            r["note"] = (("⚠ low confidence. " if c.get("confidence") == "low" else "") + str(c.get("note", ""))).strip()
    return rows


def code_issues(rows):
    """Plain-code continuity findings from the (edited) casting table."""
    issues = []
    by_label, by_char = defaultdict(set), defaultdict(set)
    for r in rows:
        by_label[r["label"]].add((r["character"], r["episode"]))
        by_char[r["character"]].add(r["label"])
    for label, uses in by_label.items():
        chars = {c for c, _ in uses}
        if len(chars) > 1:
            detail = "; ".join(f"Ep {e}: {c}" for c, e in sorted(uses, key=lambda x: x[1]))
            issues.append({"severity": "high", "issue": f"Label '{label}' is used for different characters ({detail}).",
                           "suggestion": "Cast by character, not by label, or the wrong voice artist will record these lines."})
    for char, labels in by_char.items():
        if len(labels) > 1:
            issues.append({"severity": "low", "issue": f"{char} appears under {len(labels)} labels: {', '.join(sorted(labels))}.",
                           "suggestion": "Same voice artist for all of them. Consider normalising labels in the source."})
    return issues


def cast_map(rows):
    """{episode_number: {label: character}} from the casting table."""
    out = defaultdict(dict)
    for r in rows:
        out[int(r["episode"])][r["label"]] = r["character"]
    return dict(out)


def voice_summary(rows, artists=None):
    artists = artists or {}
    agg = defaultdict(lambda: {"episodes": set(), "labels": set(), "lines": 0, "seconds": 0.0})
    for r in rows:
        a = agg[r["character"]]
        a["episodes"].add(int(r["episode"]))
        a["labels"].add(r["label"])
        a["lines"] += r["lines"]
        a["seconds"] += r["seconds"]
    out = [{"character": c, "episodes": ", ".join(str(e) for e in sorted(a["episodes"])), "labels": ", ".join(sorted(a["labels"])),
            "lines": a["lines"], "minutes": round(a["seconds"] / 60, 2), "voice_artist": artists.get(c, "")}
           for c, a in agg.items()]
    return sorted(out, key=lambda x: -x["lines"])
