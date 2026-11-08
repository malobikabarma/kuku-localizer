"""Everything an editor or a dubbing studio downloads."""
import io
import json
import zipfile
from datetime import datetime

import pandas as pd

import screenplay as sp


def flags_by_line(flags):
    out = {}
    for f in flags:
        out.setdefault(f["id"], []).append(f)
    return out


def _status(row, review):
    return (review or {}).get(row["id"], "pending")


def dubbing_sheet(result, review=None) -> pd.DataFrame:
    by = flags_by_line(result["qa"]["flags"])
    rows = []
    for r in result["rows"]:
        if r["kind"] != "dialogue":
            continue
        rows.append({"Line": r["id"], "Scene": r["scene"], "Start": sp.fmt_time(r["start"]), "End": sp.fmt_time(r["end"]),
                     "Window (s)": r["duration"], "Character": r["character"], "Label in script": r["speaker"],
                     "Delivery": r["delivery"] or "on-screen", "Emotion": r["emotion"], "English": r["english"],
                     result["lang"]: r["target"], "Fits timing": "yes" if r["fits"] else "no",
                     "Flags": "; ".join(f"{f['label']}: {f['reason']}" for f in by.get(r["id"], [])),
                     "Editor status": _status(r, review)})
    return pd.DataFrame(rows)


def dubbing_xlsx(result, review=None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        dubbing_sheet(result, review).to_excel(xl, sheet_name="Dubbing sheet", index=False)
        pd.DataFrame(result["qa"]["flags"]).to_excel(xl, sheet_name="QA flags", index=False)
        pd.DataFrame([{k: v for k, v in result["meta"].items() if not isinstance(v, (list, dict))}]).T.reset_index() \
            .rename(columns={"index": "metric", 0: "value"}).to_excel(xl, sheet_name="Summary", index=False)
        ws = xl.sheets["Dubbing sheet"]
        for col, width in zip("ABCDEFGHIJKLMN", [7, 6, 9, 9, 9, 18, 22, 10, 18, 50, 50, 8, 60, 12]):
            ws.column_dimensions[col].width = width
    return buf.getvalue()


def srt(result, which: str = "target") -> str:
    def ts(sec):
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    out, n = [], 0
    for r in result["rows"]:
        text = r["target"] if which == "target" else r["english"]
        if r["kind"] != "dialogue" or not text:
            continue
        n += 1
        out.append(f"{n}\n{ts(r['start'])} --> {ts(r['end'])}\n{text}\n")
    return "\n".join(out)


def side_by_side_md(result, review=None) -> str:
    lang, by = result["lang"], flags_by_line(result["qa"]["flags"])
    md = [f"# {result['meta'].get('episode', result['name'])}: English → {lang}", "",
          f"| Line | Time | Character | English | {lang} | Flags |", "|---|---|---|---|---|---|"]
    esc = lambda s: str(s or "").replace("|", "\\|").replace("\n", " ")
    for r in result["rows"]:
        if r["kind"] != "dialogue":
            continue
        fl = "<br>".join(f"**{f['label']}**: {esc(f['reason'])}" for f in by.get(r["id"], []))
        md.append(f"| {r['id']} | {sp.fmt_time(r['start'])}–{sp.fmt_time(r['end'])} | {esc(r['character'])} | "
                  f"{esc(r['english'])} | {esc(r['target'])} | {fl} |")
    return "\n".join(md) + "\n"


def qa_report_md(result, review=None) -> str:
    m, q = result["meta"], result["qa"]
    j, flags, lang = q["judge"], q["flags"], result["lang"]
    counts = {}
    for f in flags:
        counts[f["label"]] = counts.get(f["label"], 0) + 1
    md = [f"# QA report: {m.get('episode', result['name'])} ({lang})", "",
          f"_Generated {datetime.now():%Y-%m-%d %H:%M} with model `{m.get('model')}`._", "",
          f"> {m.get('logline', '')}", "", "## Summary", "",
          f"- Spoken lines: **{m['dialogue_lines']}**",
          f"- Lines that fit timing: **{m['fit_before']:.0%} → {m['fit_after']:.0%}** after the rewrite pass "
          f"(English source: {m.get('source_fit', 0):.0%}; heuristic: {m['max_rate']:g} {m['timing_unit']}/s)",
          f"- Lines rewritten automatically: **{m.get('lines_rewritten', 0)}**",
          f"- Flags to review: **{len(flags)}** ({sum(f['severity'] == 'high' for f in flags)} high)",
          f"- Model calls: {m.get('model_calls', 0)}, tokens in/out: {m.get('tokens_in', 0)}/{m.get('tokens_out', 0)}, "
          f"est. cost ${m.get('estimated_cost_usd', 0):.4f}", ""]
    if review:
        acc = sum(1 for v in review.values() if v == "accepted")
        md += [f"- Editor review: {acc} accepted, {sum(1 for v in review.values() if v == 'edited')} edited", ""]
    md += ["## Hook and cliffhanger (AI judgement, can be wrong)", ""]
    if j.get("ran"):
        md += [f"- **Hook preserved:** {'yes' if j['hook_preserved'] else 'NO'} — {j['hook_reason']}",
               f"- **Cliffhanger preserved:** {'yes' if j['cliffhanger_preserved'] else 'NO'} — {j['cliffhanger_reason']}", ""]
    else:
        md += [f"Not run: {j.get('reason', '')}", ""]
    if counts:
        md += ["## Flags by type", "", *[f"- {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])], ""]
    md += ["## Lines to review", ""]
    rows = {r["id"]: r for r in result["rows"]}
    for f in flags:
        r = rows.get(f["id"], {})
        md += [f"### {f['id']}: {f['label']} ({f['severity']})", f"- EN: {r.get('english', '')}",
               f"- {lang}: {r.get('target', '')}", f"- Why: {f['reason']}", ""]
    if m.get("errors"):
        md += ["## Errors during the run", "", *[f"- {e}" for e in m["errors"]], ""]
    return "\n".join(md)


def bundle_zip(results: dict, glossary_json: str = "", casting: list | None = None, reviews: dict | None = None) -> bytes:
    buf = io.BytesIO()
    reviews = reviews or {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        summary = []
        for name, res in results.items():
            rv = reviews.get(name)
            z.writestr(f"{name}/{name}_adaptation.json", json.dumps(res["rows"], ensure_ascii=False, indent=2))
            z.writestr(f"{name}/{name}_side_by_side.md", side_by_side_md(res, rv))
            z.writestr(f"{name}/{name}_qa_report.md", qa_report_md(res, rv))
            z.writestr(f"{name}/{name}_{res['lang'].lower()}.srt", srt(res))
            z.writestr(f"{name}/{name}_dubbing_sheet.xlsx", dubbing_xlsx(res, rv))
            m = res["meta"]
            summary.append({"episode": m.get("episode"), "lines": m["dialogue_lines"], "fit_before": m["fit_before"],
                            "fit_after": m["fit_after"], "flags": len(res["qa"]["flags"]),
                            "hook_ok": res["qa"]["judge"].get("hook_preserved"),
                            "cliffhanger_ok": res["qa"]["judge"].get("cliffhanger_preserved"),
                            "model_calls": m.get("model_calls"), "cost_usd": m.get("estimated_cost_usd")})
        z.writestr("series_summary.csv", pd.DataFrame(summary).to_csv(index=False))
        if glossary_json:
            z.writestr("series_glossary.json", glossary_json)
        if casting:
            z.writestr("voice_casting.csv", pd.DataFrame(casting).to_csv(index=False))
    return buf.getvalue()
