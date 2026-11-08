"""Series glossary: approved target-language spellings for names, places and recurring terms.
Built once per show by AI, then edited by a human. Every adapted line is checked against it."""
import json
from dataclasses import asdict, dataclass, field

import llm
import screenplay as sp

KINDS = ["character", "place", "term"]


@dataclass
class Entry:
    kind: str
    english: str
    target: str = ""
    aliases: list = field(default_factory=list)   # other English forms: "LADY JULIANA", "Miss Ashcroft"
    note: str = ""

    @property
    def targets(self):
        """A target cell may list accepted alternatives separated by '|'."""
        return [t.strip() for t in (self.target or "").split("|") if t.strip()]

    @property
    def english_forms(self):
        forms = [self.english] + list(self.aliases)
        return [f for f in dict.fromkeys(f.strip() for f in forms) if f]


SYSTEM = """You build a localization glossary for a {lang} dub of an English microdrama series.
From the screenplay excerpts, list:
- every character (canonical English name, plus aliases: every speaker label and every way the dialogue names them,
  e.g. "LADY JULIANA", "Miss Ashcroft", "THE FORMER GROOM"). If the real name is unknown, use the descriptive label.
- named places, and recurring objects or terms that must be rendered the same way every time (heirlooms, herbs, titles).
For each, give the {lang} spelling a native audience would expect in natural spoken dialogue (use the native script),
and a short note: who they are, relationship to the lead, and how they address others (e.g. aap vs tum in Hindi).
Return JSON: {{"entries": [{{"kind": "character|place|term", "english": "...", "target": "...", "aliases": ["..."], "note": "..."}}]}}"""


def _excerpt(episodes, limit_chars: int = 30000) -> str:
    chunks = []
    for ep in episodes:
        chunks.append(f"=== {ep.meta.get('episode_number', ep.name)} ===\nLogline: {ep.meta.get('episode_logline', '')}")
        for l in ep.lines:
            if l.kind == "dialogue":
                chunks.append(f"{l.speaker}: {l.text}")
            elif l.kind == "action":
                chunks.append(f"[action] {l.text}")
    text = "\n".join(chunks)
    return text[:limit_chars]


def extract_glossary(episodes, lang: str):
    """episodes: list of screenplay.Episode (use the first 2-3 episodes of a show)."""
    if isinstance(episodes, sp.Episode):
        episodes = [episodes]
    speakers = sorted({l.speaker for ep in episodes for l in sp.dialogue(ep.lines)})
    payload = {"speakers": speakers, "excerpt": _excerpt(episodes)}
    data = llm.call_json(SYSTEM.format(lang=lang),
                         "INPUT_JSON: " + json.dumps(payload, ensure_ascii=False), task="glossary", temperature=0.2)
    entries = data.get("entries", []) if isinstance(data, dict) else data
    out = []
    for e in entries or []:
        if not isinstance(e, dict) or not str(e.get("english", "")).strip():
            continue
        kind = str(e.get("kind", "term")).lower()
        aliases = e.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",")]
        out.append(Entry(kind=kind if kind in KINDS else "term", english=str(e["english"]).strip(),
                         target=str(e.get("target", "")).strip(), aliases=[str(a).strip() for a in aliases if str(a).strip()],
                         note=str(e.get("note", "")).strip()))
    return out


def merge(old, new):
    """Keep human edits in `old`; add genuinely new entries from `new`."""
    known = {f.lower() for e in old for f in e.english_forms}
    merged = list(old)
    for e in new:
        if not any(f.lower() in known for f in e.english_forms):
            merged.append(e)
            known.update(f.lower() for f in e.english_forms)
    return merged


# ------------------------------------------------------------------ table <-> entries
COLUMNS = ["kind", "english", "target", "aliases", "note"]


def to_rows(entries):
    return [{"kind": e.kind, "english": e.english, "target": e.target, "aliases": ", ".join(e.aliases), "note": e.note}
            for e in entries]


def from_rows(rows):
    out = []
    for r in rows:
        english = str(r.get("english") or "").strip()
        if not english or english.lower() == "nan":
            continue
        aliases = [a.strip() for a in str(r.get("aliases") or "").split(",") if a.strip() and a.strip().lower() != "nan"]
        target = str(r.get("target") or "").strip()
        out.append(Entry(kind=str(r.get("kind") or "term"), english=english,
                         target="" if target.lower() == "nan" else target, aliases=aliases,
                         note=str(r.get("note") or "").replace("nan", "").strip()))
    return out


def to_json(entries) -> str:
    return json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2)


def from_json(text: str):
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("entries", [])
    return [Entry(**{k: v for k, v in d.items() if k in Entry.__dataclass_fields__}) for d in data]


def for_prompt(entries) -> list:
    return [{"english": e.english, "aliases": e.aliases, "use": e.target, "note": e.note} for e in entries if e.target]
