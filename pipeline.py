"""End-to-end for one episode: adapt scene by scene -> code QA -> rewrite flagged lines -> judge -> result dict.
The result dict is what the UI, the reports and the CLI all consume."""
import time

import adapt
import llm
import qa
import screenplay as sp
import timing
from config import settings

FIXABLE = {"timing", "latin_name", "variant", "script", "missing"}


def _noop(frac, msg):
    pass


def build_result(ep, targets, entries, lang, cast=None, judge_result=None, first_draft=None, meta_extra=None):
    """Runs the code checks on `targets` and assembles the result. No model calls."""
    cast = cast or {}
    first_draft = first_draft or dict(targets)
    flags, stats = qa.code_checks(ep, targets, entries, lang, cast)
    j = judge_result or {"ran": False, "reason": "Not run."}
    judged = j.get("judged_targets", {})
    # keep AI flags only for lines that have not changed since the judge saw them
    ai_flags = [f for f in qa.judge_flags(j) if judged.get(f["id"], targets.get(f["id"])) == targets.get(f["id"])]
    flags = qa.sort_flags(flags + ai_flags, ep)
    rows = []
    for l in ep.lines:
        is_d = l.kind == "dialogue"
        st = stats.get(l.id, {})
        rows.append({"id": l.id, "scene": l.scene, "start": l.start, "end": l.end, "duration": round(l.duration, 2),
                     "speaker": l.speaker, "character": cast.get(l.speaker, l.speaker.title()) if is_d else "",
                     "emotion": l.emotion, "delivery": l.delivery, "kind": l.kind, "english": l.text,
                     "target": targets.get(l.id, "") if is_d else "", "first_draft": first_draft.get(l.id, "") if is_d else "",
                     "units": st.get("units"), "budget": st.get("budget"), "usage": st.get("usage"),
                     "fits": st.get("fits")})
    meta = {"episode": ep.meta.get("episode_number", ep.name), "logline": ep.meta.get("episode_logline", ""),
            "language": lang, "model": settings.model_name, "timing_unit": settings.timing_unit,
            "max_rate": settings.max_rate, "dialogue_lines": len(ep.dialogue),
            "fit_before": qa.fit_rate(ep, first_draft), "fit_after": qa.fit_rate(ep, targets),
            "source_fit": sum(timing.check(l.text, l.duration)["fits"] for l in ep.dialogue) / max(1, len(ep.dialogue)),
            "errors": [], "model_calls": 0, "tokens_in": 0, "tokens_out": 0, "estimated_cost_usd": 0.0}
    meta.update(meta_extra or {})
    return {"name": ep.name, "lang": lang, "targets": dict(targets), "first_draft": dict(first_draft),
            "rows": rows, "qa": {"flags": flags, "judge": j}, "meta": meta}


def run_episode(ep: sp.Episode, lang: str, entries, cast=None, progress=_noop, rewrite: bool = True,
                run_judge: bool = True):
    t0 = time.time()
    llm.usage.reset()
    errors, targets, summary = [], {}, ""
    scenes = sorted({l.scene for l in ep.dialogue})
    steps = len(scenes) + int(rewrite) + int(run_judge)
    for i, scene in enumerate(scenes):
        progress(i / steps, f"Adapting scene {scene} of {len(scenes)}…")
        try:
            out, summary = adapt.adapt_scene(ep, scene, entries, lang, summary, cast)
            targets.update(out)
        except llm.LLMError as e:
            errors.append(f"Scene {scene}: {e}")
    if not targets:
        raise llm.LLMError("No lines were adapted. " + (errors[0] if errors else ""))
    first_draft = dict(targets)

    rewritten = 0
    if rewrite:
        progress(len(scenes) / steps, "Fixing lines that run long or break the glossary…")
        flags, _ = qa.code_checks(ep, targets, entries, lang, cast)
        rewritten = fix_lines(ep, targets, entries, lang, [f for f in flags if f["type"] in FIXABLE], errors)

    j = {"ran": False, "reason": "Switched off."}
    if run_judge:
        progress((steps - 1) / steps, "Judging the hook and the cliffhanger…")
        try:
            j = qa.judge(ep, targets, lang)
            j["judged_targets"] = dict(targets)
        except llm.LLMError as e:
            j = {"ran": False, "reason": str(e)}
            errors.append(f"Judge: {e}")
    progress(1.0, "Done")
    extra = {**llm.usage.snapshot(), "errors": errors, "elapsed_sec": round(time.time() - t0, 1),
             "lines_rewritten": rewritten, "scenes": len(scenes)}
    return build_result(ep, targets, entries, lang, cast, j, first_draft, extra)


def fix_lines(ep, targets, entries, lang, flags, errors=None, batch: int = 25) -> int:
    """Rewrites flagged lines in place. Keeps a rewrite only if it is not worse. Returns how many changed."""
    by_id = {}
    for f in flags:
        by_id.setdefault(f["id"], []).append(f"{f['type']}: {f['reason']}")
    lines = {l.id: l for l in ep.dialogue}
    items = [{"line": lines[i], "current": targets.get(i, ""), "reasons": r} for i, r in by_id.items() if i in lines]
    changed = 0
    for k in range(0, len(items), batch):
        try:
            new = adapt.revise_lines(items[k:k + batch], entries, lang, ep)
        except llm.LLMError as e:
            if errors is not None:
                errors.append(f"Rewrite: {e}")
            continue
        for lid, text in new.items():
            if lid not in lines or not text:
                continue
            old = targets.get(lid, "")
            dur = lines[lid].duration
            new_fit, old_fit = timing.check(text, dur), timing.check(old, dur) if old else None
            if old_fit is None or new_fit["fits"] or new_fit["units"] <= old_fit["units"]:
                if text != old:
                    targets[lid] = text
                    changed += 1
    return changed


def apply_judge_suggestions(result, ep, entries, cast=None):
    """Applies the judge's suggested lines (only where they fit the timing). Returns (result, n_applied)."""
    j = result["qa"]["judge"]
    targets = dict(result["targets"])
    lines = {l.id: l for l in ep.dialogue}
    proposals = {str(u["id"]): u.get("suggestion", "") for u in j.get("unnatural_lines", [])}
    if j.get("ran") and not j.get("hook_preserved") and j.get("hook_fix"):
        proposals[j["hook_ids"][0]] = j["hook_fix"]
    if j.get("ran") and not j.get("cliffhanger_preserved") and j.get("cliffhanger_fix"):
        proposals[j["cliffhanger_ids"][-1]] = j["cliffhanger_fix"]
    n = 0
    for lid, text in proposals.items():
        if lid in lines and text and timing.check(text, lines[lid].duration)["fits"]:
            targets[lid] = text.strip()
            n += 1
    new = build_result(ep, targets, entries, result["lang"], cast, j, result["first_draft"],
                       {k: v for k, v in result["meta"].items() if k not in ("fit_before", "fit_after")})
    return new, n
