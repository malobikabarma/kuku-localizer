"""Turns an episode screenplay into structured lines. Plain code, no AI, for the known format:

    SCENE 01
    Scene heading: INT. CATHEDRAL - DAY
    **LORD ASHCROFT (Stern, Commanding):**
    Start: (00:04.20) | End: (00:05.80)
    "Miss Ashcroft."

Unknown formats fall back to one AI call that rewrites the file into this format first."""
import io
import json
import re
from dataclasses import asdict, dataclass, field

import llm

NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sfx", "SFX": "sfx", "SOUND": "sfx",
                "MUSIC": "sfx", "TRANSITION": "camera", "NOTE": "action"}
DELIVERY_TAGS = {"O.S.": "O.S.", "OS": "O.S.", "OFF-SCREEN": "O.S.", "OFF SCREEN": "O.S.", "V.O.": "V.O.",
                 "VO": "V.O.", "CONT'D": "", "CONTINUES": "", "CONTINUED": ""}

TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?"
RE_SCENE = re.compile(r"^\s*SCENE\s+(\d+)\s*$", re.I)
RE_HEADING = re.compile(r"^\s*scene heading\s*:\s*(.+)$", re.I)
RE_SCENE_START = re.compile(r"^\s*scene start\s*:\s*(" + TIME + r")", re.I)
RE_SCENE_END = re.compile(r"^\s*scene end\s*:\s*(" + TIME + r")", re.I)
RE_BLOCK = re.compile(r"^\s*\*\*(.+?):?\*\*\s*:?\s*$")
RE_PLAIN_BLOCK = re.compile(r"^\s*([A-Z][A-Z0-9 .'’\-/&]{1,60}(?:\s*\([^)]*\))*)\s*:\s*$")
RE_TIMES = re.compile(r"start\s*:\s*\(?\s*(" + TIME + r")\s*\)?\s*\|?\s*end\s*:\s*\(?\s*(" + TIME + r")\s*\)?", re.I)
RE_META = re.compile(r"^\s*(EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES|EPISODE TITLE|SERIES)\s*:\s*(.*)$", re.I)
SKIP = re.compile(r"^\s*(actions and dialogue\s*:|---.*---|$)", re.I)


@dataclass
class Line:
    id: str
    scene: int
    start: float
    end: float
    speaker: str          # cleaned label, e.g. "LORD ASHCROFT"
    text: str
    kind: str             # dialogue | action | camera | sfx
    emotion: str = ""
    delivery: str = ""    # "", "O.S." or "V.O."

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Episode:
    name: str
    lines: list
    warnings: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    scenes: dict = field(default_factory=dict)     # scene number -> heading
    used_ai: bool = False

    @property
    def dialogue(self):
        return dialogue(self.lines)

    @property
    def number(self) -> int:
        m = re.search(r"(\d+)", str(self.meta.get("episode_number", "")) or self.name)
        return int(m.group(1)) if m else 0

    @property
    def duration(self) -> float:
        return max((l.end for l in self.lines), default=0.0)

    def to_dict(self) -> dict:
        return {"name": self.name, "meta": self.meta, "scenes": self.scenes, "warnings": self.warnings,
                "used_ai": self.used_ai, "lines": [asdict(l) for l in self.lines]}


# ------------------------------------------------------------------ helpers
def to_seconds(t: str) -> float:
    parts = t.replace(",", ".").split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return round(secs, 3)


def fmt_time(sec: float) -> str:
    sec = max(0.0, float(sec or 0))
    return f"{int(sec // 60):02d}:{sec % 60:05.2f}"


def dialogue(lines):
    return [l for l in lines if l.kind == "dialogue"]


def _clean_text(text: str) -> str:
    text = " ".join(text.split())
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1]
    return text.strip().strip("“”").strip()


def split_label(label: str):
    """'JULIANA (V.O.) (Reflective, Vulnerable)' -> ('JULIANA', 'V.O.', 'Reflective, Vulnerable')"""
    label = label.strip().rstrip(":").strip()
    name = re.split(r"\(", label, 1)[0].strip()
    delivery, emotions = "", []
    for group in re.findall(r"\(([^)]*)\)", label):
        for part in re.split(r"[/,]", group):
            token = part.strip()
            key = token.upper().replace("’", "'")
            if key in DELIVERY_TAGS:
                delivery = DELIVERY_TAGS[key] or delivery
            elif token:
                emotions.append(token)
    return " ".join(name.upper().split()), delivery, ", ".join(emotions)


# ------------------------------------------------------------------ parser
def parse(raw: str, name: str = "episode") -> Episode:
    raw = raw.replace("\ufeff", "").replace("\r\n", "\n")
    meta, scenes, lines, warnings = {}, {}, [], []
    scene, block, n = 0, None, 0

    def close(b):
        nonlocal n
        if not b:
            return
        speaker, delivery, emotion = split_label(b["label"])
        kind = NON_DIALOGUE.get(speaker, "dialogue")
        text = _clean_text(" ".join(b["text"]))
        if b["start"] is None:
            warnings.append(f"Scene {b['scene']}: block '{b['label']}' has no Start/End time, skipped.")
            return
        if kind == "dialogue" and not text:
            warnings.append(f"Scene {b['scene']}: '{speaker}' at {fmt_time(b['start'])} has no spoken text, skipped.")
            return
        if b["end"] <= b["start"]:
            warnings.append(f"Scene {b['scene']}: '{speaker}' at {fmt_time(b['start'])} ends before it starts.")
        n += 1
        lines.append(Line(id=f"L{n:03d}", scene=b["scene"] or 1, start=b["start"], end=b["end"], speaker=speaker,
                          text=text, kind=kind, emotion=emotion if kind == "dialogue" else "",
                          delivery=delivery if kind == "dialogue" else ""))

    for row in raw.split("\n"):
        if m := RE_META.match(row):
            key = m.group(1).lower().replace(" ", "_")
            meta[key] = m.group(2).strip()
            continue
        if m := RE_SCENE.match(row):
            close(block); block = None
            scene = int(m.group(1))
            scenes.setdefault(scene, "")
            continue
        if m := RE_HEADING.match(row):
            scenes[scene or 1] = m.group(1).strip()
            continue
        if RE_SCENE_START.match(row) or RE_SCENE_END.match(row):
            continue
        if SKIP.match(row):
            continue
        m = RE_BLOCK.match(row) or (RE_PLAIN_BLOCK.match(row) if not RE_TIMES.search(row) else None)
        if m:
            close(block)
            block = {"label": m.group(1), "scene": scene or 1, "start": None, "end": None, "text": []}
            continue
        if block is not None and (t := RE_TIMES.search(row)):
            block["start"], block["end"] = to_seconds(t.group(1)), to_seconds(t.group(2))
            continue
        if block is not None:
            block["text"].append(row.strip())
    close(block)
    lines.sort(key=lambda l: (l.scene, l.start))
    if "episode_number" not in meta:
        m = re.search(r"episode[-_ ]?0*(\d+)", name, re.I)
        if m:
            meta["episode_number"] = f"Episode {m.group(1)}"
    return Episode(name=name, lines=lines, warnings=warnings, meta=meta, scenes=scenes)


REFORMAT_SYSTEM = """You convert screenplays into a strict plain-text format. Do not translate, shorten or invent dialogue.
Output format, repeated for every scene:
SCENE 01
Scene heading: <heading>
**<SPEAKER NAME IN CAPS> (<emotion>):**
Start: (MM:SS.ss) | End: (MM:SS.ss)
"<exact spoken line>"
Use **ACTION:** blocks for action. If the source has no timestamps, estimate them at 2.5 spoken words per second,
running continuously from 00:00.00. Return only the converted screenplay."""


def parse_with_fallback(raw: str, name: str = "episode", allow_ai: bool = True) -> Episode:
    ep = parse(raw, name)
    if len(ep.dialogue) >= 2 or not raw.strip() or not allow_ai:
        if len(ep.dialogue) < 2 and raw.strip():
            ep.warnings.insert(0, "Very few spoken lines were found. The format may be unfamiliar.")
        return ep
    converted = llm.call_llm(REFORMAT_SYSTEM, "INPUT_JSON: " + json.dumps({"text": raw[:60000]}, ensure_ascii=False),
                             task="reformat", temperature=0.0)
    ep2 = parse(converted, name)
    ep2.meta = {**ep2.meta, **ep.meta}
    ep2.used_ai = True
    ep2.warnings.insert(0, "The format was unfamiliar, so AI rewrote it into the standard format. Check the lines and times.")
    return ep2 if len(ep2.dialogue) > len(ep.dialogue) else ep


# ------------------------------------------------------------------ file readers
def read_file_text(filename: str, data: bytes) -> str:
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "docx":
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    if ext == "pdf":
        from pypdf import PdfReader
        return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
