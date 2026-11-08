"""Kuku Localizer: adaptation + QA for microdrama episodes.   Run locally:  streamlit run app.py

Flow: upload episodes -> approve the series glossary and voice casting -> adapt + QA -> review flagged lines -> export.
Nothing is stored on the server: results live in your browser session until you download them."""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import evaluation as ev
import glossary as gl
import llm
import pipeline
import qa
import report
import screenplay as sp
import series
import timing
import ui
from config import settings

st.set_page_config(page_title="Kuku Localizer", page_icon="🎧", layout="wide", initial_sidebar_state="expanded")
ui.inject_css()

LANGS = ["Hindi", "Tamil", "Telugu", "Bengali", "Marathi", "Kannada", "Malayalam", "Gujarati", "Other…"]
STATUSES = ["pending", "accepted", "edited", "needs rewrite"]
HERE = Path(__file__).parent


def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


for k, v in {"episodes": {}, "results": {}, "reviews": {}, "file_keys": set(), "selected": None, "editor_ver": 0,
             "gloss_base": [], "gloss_ver": 0, "gloss_current": None, "cast_base": None, "cast_ver": 0,
             "cast_current": None, "ai_issues": [], "artists": {}, "eval": None, "demo": False}.items():
    ss(k, v)
S = st.session_state
ss("show_title_v", "Untitled show")
ss("model_v", settings.model_name)
if "_pending_title" in S:                      # widget keys can only be set before the widget is drawn
    S.show_title_v = S.pop("_pending_title")

# ------------------------------------------------------------------ password gate
if settings.app_password and not S.get("authed"):
    ui.sidebar_brand()
    pw = st.text_input("Password", type="password")
    if pw == settings.app_password:
        S.authed = True
        st.rerun()
    st.info("Enter the password to open the studio.")
    st.stop()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    ui.sidebar_brand()
    st.text_input("Show title", key="show_title_v")
    choice = st.selectbox("Dub into", LANGS, index=LANGS.index(settings.target_language)
                          if settings.target_language in LANGS else 0)
    lang = st.text_input("Language name", "Odia") if choice == "Other…" else choice
    with st.expander("Model and timing"):
        settings.model_name = st.text_input("Model", key="model_v",
                                            help="Any model your OpenAI-compatible provider serves. The provider and key "
                                                 "are set in Secrets, not here, so the key can't be redirected.")
        settings.timing_unit = st.radio("Measure lines in", ["syllables", "words"], horizontal=True,
                                        index=0 if settings.timing_unit == "syllables" else 1)
        if settings.timing_unit == "syllables":
            settings.max_syllables_per_sec = st.number_input("Max syllables per second", 3.0, 10.0,
                                                             float(settings.max_syllables_per_sec), 0.25)
        else:
            settings.max_words_per_sec = st.number_input("Max words per second", 1.0, 6.0,
                                                         float(settings.max_words_per_sec), 0.1)
        settings.timing_grace_sec = st.number_input("Breath allowance (seconds)", 0.0, 1.0,
                                                    float(settings.timing_grace_sec), 0.05)
        st.caption("Heuristic, not audio. At 6 syllables/s, 99.7% of the English source lines fit their own windows. "
                   "Calibrate by reading ten lines aloud with a stopwatch.")
    if llm.is_mock():
        st.warning("Mock model (API_BASE=mock): output is fake, for testing only.")
    elif settings.api_key:
        st.success(f"Model connected: {settings.model_name}", icon="✅")
    else:
        st.error("No API key. Add API_KEY in Secrets to adapt new episodes. The demo works without one.", icon="🔑")

    st.subheader("Episodes")
    uploads = st.file_uploader("Upload screenplays", type=["txt", "md", "docx", "pdf"], accept_multiple_files=True,
                               help="Upload one episode or the whole season at once.")
    c1, c2 = st.columns(2)
    load_demo = c1.button("Load demo", width="stretch")
    if c2.button("Clear all", width="stretch"):
        keep = {"authed": S.get("authed")}
        S.clear()
        S.update({k: v for k, v in keep.items() if v})
        st.rerun()
    st.caption("Don't upload confidential scripts to a deployment you don't control.")

# ------------------------------------------------------------------ ingest
for f in uploads or []:
    key = (f.name, f.size)
    if key in S.file_keys:
        continue
    raw = sp.read_file_text(f.name, f.getvalue())
    stem = Path(f.name).stem
    try:
        ep = sp.parse_with_fallback(raw, stem, allow_ai=llm.is_configured())
    except llm.LLMError as e:
        ep = sp.parse(raw, stem)
        ep.warnings.insert(0, f"The AI format fix failed: {e}")
    S.episodes[ep.name] = ep
    S.file_keys.add(key)
    S.selected = S.selected or ep.name
    S.demo = False


def build_demo():
    data = json.loads((HERE / "sample" / "sample_adaptation_hi.json").read_text(encoding="utf-8"))
    ep = sp.parse((HERE / "sample" / "sample_episode.txt").read_text(encoding="utf-8"), "demo_episode")
    by_en = data["targets_by_english"]
    targets = {l.id: by_en.get(l.text, "") for l in ep.dialogue}
    j = dict(data["judge"])
    id_of = {l.text: l.id for l in ep.dialogue}
    spoken = ep.dialogue
    j.update({"ran": True, "hook_ids": [l.id for l in spoken[:3]], "cliffhanger_ids": [l.id for l in spoken[-3:]],
              "unnatural_lines": [{"id": id_of[u["english"]], "reason": u["reason"], "suggestion": u["suggestion"]}
                                  for u in j.pop("unnatural_lines_by_english", []) if u["english"] in id_of],
              "judged_targets": dict(targets)})
    entries = [gl.Entry(**e) for e in data["glossary"]]
    res = pipeline.build_result(ep, targets, entries, "Hindi", {}, j, dict(targets),
                                {"demo": True, "model": "stored demo", "lines_rewritten": 0})
    S.episodes = {ep.name: ep}
    S.results = {ep.name: res}
    S.reviews = {}
    S.gloss_base, S.gloss_current = gl.to_rows(entries), None
    S.gloss_ver += 1
    S.cast_base, S.cast_current, S.ai_issues = None, None, []
    S.selected, S.demo = ep.name, True
    S["_pending_title"] = "Night Shift (demo)"


if load_demo:
    build_demo()
    st.rerun()

episodes = dict(sorted(S.episodes.items(), key=lambda kv: (kv[1].number, kv[0])))
if S.selected not in episodes:
    S.selected = next(iter(episodes), None)

# ------------------------------------------------------------------ empty state
if not episodes:
    ui.hero("Dub a whole season in an afternoon", 0, lang, 0, subtitle="English microdrama in, dub-ready scripts out")
    ui.empty("Start with a script",
             "<p>Upload one or more episode screenplays in the sidebar, or press <b>Load demo</b> to open a finished "
             "Hindi adaptation with its QA report.</p><p>What you get for each episode: a natural spoken adaptation that "
             "fits the original timing, a check that the hook and the cliffhanger still land, name and spelling "
             "consistency against your series glossary, a voice-casting map across episodes, and dubbing-ready exports "
             "(Excel sheet, SRT, Markdown reports).</p>")
    st.stop()

ui.hero(S.show_title_v, len(episodes), lang, sum(e.duration for e in episodes.values()) / 60)

# ------------------------------------------------------------------ the shelf
with st.container(key="shelf"):
    names = list(episodes)
    per_row = 5
    for i in range(0, len(names), per_row):
        cols = st.columns(per_row)
        for col, name in zip(cols, names[i:i + per_row]):
            with col:
                ui.tile(episodes[name], S.results.get(name), name == S.selected)
                if st.button("Open" if name != S.selected else "Open ✓", key=f"open_{name}", width="stretch",
                             type="primary" if name == S.selected else "secondary"):
                    S.selected = name
                    st.rerun()

tab_studio, tab_series, tab_lab, tab_batch, tab_how = st.tabs(
    ["🎬 Studio", "📚 Series bible", "🧪 QA lab", "📊 Season dashboard", "ℹ️ How it works"])


# ------------------------------------------------------------------ shared helpers
def entries_now():
    rows = S.gloss_current if S.gloss_current is not None else S.gloss_base
    return gl.from_rows(rows)


def cast_for(ep):
    rows = S.cast_current if S.cast_current is not None else (S.cast_base or [])
    return series.cast_map(rows).get(ep.number, {}) if rows else {}


def need_model():
    if not llm.is_configured():
        st.error("This step calls the model. Add API_KEY (and API_BASE / MODEL_NAME) in Secrets or .env first.")
        return False
    return True


def run_one(ep, rewrite=True, judge=True, bar=None):
    def prog(frac, msg):
        if bar is not None:
            bar.progress(min(max(frac, 0.0), 1.0), text=f"{ep.meta.get('episode_number', ep.name)}: {msg}")
    res = pipeline.run_episode(ep, lang, entries_now(), cast_for(ep), prog, rewrite=rewrite, run_judge=judge)
    S.results[ep.name] = res
    S.reviews[ep.name] = {}
    S.editor_ver += 1
    return res


def rebuild(ep, res, targets, judge=None):
    meta_keep = {k: v for k, v in res["meta"].items() if k not in ("fit_before", "fit_after", "source_fit",
                                                                  "dialogue_lines", "timing_unit", "max_rate")}
    new = pipeline.build_result(ep, targets, entries_now(), res["lang"], cast_for(ep), judge or res["qa"]["judge"],
                                res["first_draft"], meta_keep)
    S.results[ep.name] = new
    S.editor_ver += 1
    return new


# ================================================================== SERIES BIBLE (rendered first so the
# glossary and casting edits are fresh when the studio runs)
with tab_series:
    st.subheader("Series glossary")
    st.caption("Approved spellings for names, places and recurring terms. Every adapted line is checked against "
               "this list. This is the human checkpoint: fix the spellings before adapting the season.")
    g1, g2, g3 = st.columns([2, 2, 3])
    n_read = g1.number_input("Episodes to read", 1, max(1, len(episodes)), min(3, len(episodes)),
                             help="The first few episodes usually introduce every main character.")
    if g2.button("Build glossary with AI", type="primary", width="stretch") and need_model():
        try:
            with st.spinner("Reading names and terms…"):
                found = gl.extract_glossary(list(episodes.values())[:n_read], lang)
            S.gloss_base = gl.to_rows(gl.merge(entries_now(), found))
            S.gloss_current, S.gloss_ver = None, S.gloss_ver + 1
            st.rerun()
        except llm.LLMError as e:
            st.error(str(e))
    imp = g3.file_uploader("Import a glossary (.json)", type=["json"], key="gloss_imp", label_visibility="collapsed")
    if imp is not None and S.get("gloss_imported") != (imp.name, imp.size):
        try:
            S.gloss_base = gl.to_rows(gl.merge(entries_now(), gl.from_json(imp.getvalue().decode("utf-8"))))
            S.gloss_current, S.gloss_ver, S.gloss_imported = None, S.gloss_ver + 1, (imp.name, imp.size)
            st.rerun()
        except Exception as e:  # noqa
            st.error(f"That file isn't a glossary export: {e}")
    edited = st.data_editor(pd.DataFrame(S.gloss_base, columns=gl.COLUMNS), num_rows="dynamic", hide_index=True,
                            width="stretch", key=f"gloss_ed_{S.gloss_ver}",
                            column_config={"kind": st.column_config.SelectboxColumn("Kind", options=gl.KINDS, width="small"),
                                           "english": st.column_config.TextColumn("English", width="medium"),
                                           "target": st.column_config.TextColumn(f"{lang} spelling", width="medium",
                                                                                 help="Use | to allow alternatives: पिताजी|पापा"),
                                           "aliases": st.column_config.TextColumn("Also called", width="large",
                                                                                  help="Comma-separated: speaker labels and other forms"),
                                           "note": st.column_config.TextColumn("Note for writers", width="large")})
    S.gloss_current = edited.to_dict("records")
    if not S.gloss_current:
        st.info("No glossary yet. Without one, name checks have nothing to compare against.")
    st.download_button("Export glossary (.json)", gl.to_json(entries_now()), "series_glossary.json",
                       disabled=not S.gloss_current)

    st.divider()
    st.subheader("Voice casting across episodes")
    st.caption("Scripts label the same person differently, and sometimes reuse a label for two people. Cast by "
               "character, not by label, so one voice artist records one character all season.")
    have = {int(r["episode"]) for r in (S.cast_base or [])}
    missing_eps = [e for e in episodes.values() if e.number not in have]
    if S.cast_base is None or missing_eps:
        S.cast_base = (S.cast_base or []) + series.speaker_table(missing_eps if S.cast_base else episodes.values(),
                                                                 entries_now())
        S.cast_current, S.cast_ver = None, S.cast_ver + 1
    c1, c2, _ = st.columns([2, 3, 3])
    if c1.button("Re-match with glossary", width="stretch"):
        S.cast_base = series.speaker_table(episodes.values(), entries_now())
        S.cast_current, S.cast_ver = None, S.cast_ver + 1
        st.rerun()
    if c2.button("Resolve labels and check continuity with AI", type="primary", width="stretch") and need_model():
        try:
            with st.spinner("Reading every episode's speakers…"):
                cast, issues = series.ai_cast(episodes.values(), entries_now())
            S.cast_base = series.apply_ai_cast(series.speaker_table(episodes.values(), entries_now()), cast)
            S.ai_issues, S.cast_current, S.cast_ver = issues, None, S.cast_ver + 1
            st.rerun()
        except llm.LLMError as e:
            st.error(str(e))
    cast_df = st.data_editor(pd.DataFrame(S.cast_base), hide_index=True, width="stretch",
                             key=f"cast_ed_{S.cast_ver}",
                             disabled=["episode", "label", "lines", "seconds", "sample"],
                             column_config={"episode": st.column_config.NumberColumn("Ep", width="small"),
                                            "label": "Label in script", "lines": st.column_config.NumberColumn("Lines", width="small"),
                                            "seconds": st.column_config.NumberColumn("Seconds", width="small"),
                                            "sample": st.column_config.TextColumn("First line", width="large"),
                                            "character": st.column_config.TextColumn("Character (edit me)", width="medium"),
                                            "note": st.column_config.TextColumn("Note", width="medium")})
    S.cast_current = cast_df.to_dict("records")
    issues = series.code_issues(S.cast_current) + [
        {"severity": i.get("severity", "medium"), "issue": f"Ep {', '.join(str(e) for e in i.get('episodes', []))}: {i.get('issue', '')}",
         "suggestion": i.get("suggestion", "")} for i in S.ai_issues if isinstance(i, dict)]
    st.markdown(f"**Continuity findings ({len(issues)})**")
    if not issues:
        st.caption("Nothing found yet. Run the AI check to compare loglines, labels and sample lines across episodes.")
    for i in sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3)):
        ui.issue(i["severity"], i["issue"], i.get("suggestion", ""))
    st.markdown("**Voice artists**")
    vs = series.voice_summary(S.cast_current, S.artists)
    vdf = st.data_editor(pd.DataFrame(vs), hide_index=True, width="stretch", key="voices_ed",
                         disabled=["character", "episodes", "labels", "lines", "minutes"],
                         column_config={"voice_artist": st.column_config.TextColumn("Voice artist (edit me)")})
    S.artists = {r["character"]: r["voice_artist"] for r in vdf.to_dict("records") if r.get("voice_artist")}
    st.download_button("Export casting sheet (.csv)", pd.DataFrame(vs).to_csv(index=False), "voice_casting.csv")


# ================================================================== STUDIO
with tab_studio:
    ep = episodes[S.selected]
    res = S.results.get(ep.name)
    review = S.reviews.setdefault(ep.name, {})
    if res and res["meta"].get("demo"):
        ui.demo_banner()
    ui.episode_header(ep)
    n_reviewed = sum(1 for v in review.values() if v in ("accepted", "edited"))
    ui.stepper([("Read script", "done"),
                ("Approve glossary", "done" if S.gloss_current else "now"),
                ("Adapt and QA", "done" if res else ("now" if S.gloss_current else "todo")),
                ("Review lines", "done" if res and n_reviewed >= len(ep.dialogue) else ("now" if res else "todo")),
                ("Export", "now" if res else "todo")])
    if ep.warnings:
        with st.expander(f"{len(ep.warnings)} parsing notes"):
            for w in ep.warnings:
                st.write("•", w)
    with st.expander("Parsed screenplay"):
        st.dataframe(pd.DataFrame([{"Line": l.id, "Scene": l.scene, "Time": f"{sp.fmt_time(l.start)}–{sp.fmt_time(l.end)}",
                                    "Type": l.kind, "Speaker": l.speaker, "Delivery": l.delivery, "Emotion": l.emotion,
                                    "Text": l.text} for l in ep.lines]), hide_index=True, width="stretch", height=320)

    a1, a2, a3 = st.columns([2, 2, 3])
    do_rewrite = a1.toggle("Auto-fix long lines", True, help="One extra call rewrites only lines that overrun or break the glossary.")
    do_judge = a2.toggle("Judge hook and cliffhanger", True, help="One extra call. An AI opinion, shown as a suggestion.")
    label = "Adapt again" if res else f"Adapt into {lang} and run QA"
    if a3.button(label, type="primary", width="stretch", disabled=S.demo and not llm.is_configured()):
        if need_model():
            if not S.gloss_current:
                st.warning("Adapting without a glossary: names may vary between episodes.")
            bar = st.progress(0.0, text="Starting…")
            try:
                res = run_one(ep, do_rewrite, do_judge, bar)
                bar.empty()
                st.rerun()
            except llm.LLMError as e:
                bar.empty()
                st.error(str(e))

    if not res:
        ui.empty("Ready when you are", f"<p>Press <b>Adapt into {ui.esc(lang)} and run QA</b>. Each scene is adapted with "
                                      "the glossary, the previous scene's summary and a time budget for every line. "
                                      "Then code checks timing and names, and an AI judge reads the hook and the cliffhanger.</p>")
    else:
        m, flags, rows, rlang = res["meta"], res["qa"]["flags"], res["rows"], res["lang"]
        if rlang != lang:
            st.warning(f"These results are in {rlang}. Press **Adapt again** to make a {lang} version.")
        high = sum(f["severity"] == "high" for f in flags)
        accepted = sum(1 for v in review.values() if v == "accepted")
        ui.stats([
            {"v": f"{m['fit_after']:.0%}", "l": "lines fit their timing", "tone": "good" if m["fit_after"] >= .9 else "hot",
             "d": f"{m['fit_after'] - m['fit_before']:+.0%} after auto-fix" if m["fit_after"] != m["fit_before"] else ""},
            {"v": len(flags), "l": f"flags to review ({high} high)", "tone": "bad" if high else ""},
            {"v": f"{accepted}/{m['dialogue_lines']}", "l": "lines accepted by editor"},
            {"v": m.get("lines_rewritten", 0), "l": "lines auto-fixed"},
            {"v": m.get("model_calls", 0), "l": "model calls"},
            {"v": f"${m.get('estimated_cost_usd', 0):.4f}", "l": "estimated cost"}])
        for err in m.get("errors", []):
            st.error(err)

        # hook + cliffhanger
        j = res["qa"]["judge"]
        spoken = [r for r in rows if r["kind"] == "dialogue"]
        pairs = lambda rs: [(r["character"] or r["speaker"], r["english"], r["target"]) for r in rs]
        h1, h2 = st.columns(2)
        with h1:
            ui.verdict_card("Hook: the first seconds", j.get("hook_preserved") if j.get("ran") else None,
                            j.get("hook_reason") or j.get("reason", ""), pairs(spoken[:3]), rlang)
        with h2:
            ui.verdict_card("Cliffhanger: the last seconds", j.get("cliffhanger_preserved") if j.get("ran") else None,
                            j.get("cliffhanger_reason") or j.get("reason", ""), pairs(spoken[-3:]), rlang)
        st.caption("The verdicts are an AI judgement and can be wrong. Treat them as a second opinion.")

        # timing chart
        st.markdown("#### Timing: how much of each line's window the dub uses")
        view = st.segmented_control("Version", ["Final", "First draft"], default="Final", key=f"tv_{ep.name}")
        src = res["targets"] if view != "First draft" else res["first_draft"]
        chart_rows = []
        for r in spoken:
            t = src.get(r["id"], "")
            if t:
                c = timing.check(t, r["duration"])
                chart_rows.append({"line": r["id"], "used": round(c["usage"] * 100), "fits": "fits" if c["fits"] else "too long",
                                   "who": r["character"], "text": t, "window": r["duration"]})
        if chart_rows:
            cd = pd.DataFrame(chart_rows)
            bars = alt.Chart(cd).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("line:N", sort=None, title=None, axis=alt.Axis(labels=len(cd) <= 40, labelAngle=-60)),
                y=alt.Y("used:Q", title="% of window"),
                color=alt.Color("fits:N", scale=alt.Scale(domain=["fits", "too long"], range=["#3DD9A0", "#FF4F70"]),
                                legend=alt.Legend(title=None, orient="top")),
                tooltip=["line", "who", "text", alt.Tooltip("window:Q", title="window (s)"), alt.Tooltip("used:Q", title="% used")])
            limit = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(color="#FFC145", strokeDash=[5, 4]).encode(y="y:Q")
            st.altair_chart((bars + limit).properties(height=230).configure_view(stroke=None)
                            .configure_axis(labelColor="#A99FB8", titleColor="#A99FB8", gridColor="#2A2235", domainColor="#3A3046")
                            .configure_legend(labelColor="#F5EFF7"), width="stretch", theme=None)

        # review table
        st.markdown("#### Review lines")
        by_line = report.flags_by_line(flags)
        show = st.segmented_control("Show", ["Flagged", "High severity", "Pending", "All lines"],
                                    default="Flagged" if flags else "All lines", key=f"flt_{ep.name}")
        table = []
        for r in spoken:
            fl = by_line.get(r["id"], [])
            table.append({"ID": r["id"], "Character": r["character"], "English": r["english"], rlang: r["target"],
                          "Flags": "\n".join(f"{f['label']} ({f['severity']}): {f['reason']}" for f in fl),
                          "Status": review.get(r["id"], "pending"),
                          "Time": f"{sp.fmt_time(r['start'])}–{sp.fmt_time(r['end'])}", "Emotion": r["emotion"],
                          "_sev": {f["severity"] for f in fl}})
        tdf = pd.DataFrame(table)
        if show == "Flagged":
            tdf = tdf[tdf["Flags"] != ""]
        elif show == "High severity":
            tdf = tdf[tdf["_sev"].apply(lambda s: "high" in s)]
        elif show == "Pending":
            tdf = tdf[tdf["Status"] == "pending"]
        tdf = tdf.drop(columns=["_sev"])
        if tdf.empty:
            st.success("Nothing in this view. Switch to **All lines** to see everything.")
        else:
            ed = st.data_editor(tdf, hide_index=True, width="stretch", key=f"rev_{ep.name}_{S.editor_ver}",
                                disabled=["ID", "Time", "Character", "Emotion", "English", "Flags"],
                                height=min(560, 38 + 35 * len(tdf)),
                                column_config={"ID": st.column_config.TextColumn(width="small"),
                                               "English": st.column_config.TextColumn(width="medium"),
                                               rlang: st.column_config.TextColumn(f"{rlang} (edit me)", width="large"),
                                               "Flags": st.column_config.TextColumn(width="medium"),
                                               "Status": st.column_config.SelectboxColumn(options=STATUSES, width="small")})
            b1, b2, b3, b4 = st.columns(4)
            if b1.button("Save edits and re-check", type="primary", width="stretch"):
                targets = dict(res["targets"])
                for row in ed.to_dict("records"):
                    lid, new_t = row["ID"], str(row[rlang] or "").strip()
                    if new_t != targets.get(lid, ""):
                        targets[lid] = new_t
                        review[lid] = "edited"
                    else:
                        review[lid] = row["Status"]
                rebuild(ep, res, targets)
                st.rerun()
            if b2.button("Accept all unflagged", width="stretch"):
                for r in spoken:
                    if r["id"] not in by_line and review.get(r["id"], "pending") == "pending":
                        review[r["id"]] = "accepted"
                S.editor_ver += 1
                st.rerun()
            if b3.button("Fix flagged lines with AI", width="stretch", disabled=not flags):
                if need_model():
                    targets = dict(res["targets"])
                    picked = [f for f in flags if f["type"] in pipeline.FIXABLE | {"natural", "hook", "cliffhanger"}
                              or review.get(f["id"]) == "needs rewrite"]
                    picked += [qa.flag(lid, "natural", "Editor asked for a rewrite.") for lid, s in review.items()
                               if s == "needs rewrite" and lid not in by_line]
                    try:
                        with st.spinner("Rewriting flagged lines…"):
                            n = pipeline.fix_lines(ep, targets, entries_now(), rlang, picked)
                        rebuild(ep, res, targets)
                        st.toast(f"Rewrote {n} lines. Check them before accepting.")
                        st.rerun()
                    except llm.LLMError as e:
                        st.error(str(e))
            has_sugg = bool(j.get("unnatural_lines") or j.get("hook_fix") or j.get("cliffhanger_fix"))
            if b4.button("Apply AI judge suggestions", width="stretch", disabled=not has_sugg):
                new, n = pipeline.apply_judge_suggestions(res, ep, entries_now(), cast_for(ep))
                S.results[ep.name] = new
                S.editor_ver += 1
                st.toast(f"Applied {n} suggestions that fit the timing.")
                st.rerun()
        acc = sum(1 for v in review.values() if v == "accepted")
        edt = sum(1 for v in review.values() if v == "edited")
        st.caption(f"Editor acceptance so far: {acc} accepted as-is, {edt} edited, "
                   f"{len(spoken) - acc - edt} still pending. The target is 70% accepted without edits.")

        # exports
        st.markdown("#### Export")
        base = ep.name
        e1, e2, e3 = st.columns(3)
        e1.download_button("Excel dubbing sheet", report.dubbing_xlsx(res, review), f"{base}_dubbing_sheet.xlsx",
                           width="stretch", type="primary", help="Character, delivery, emotion, timing, flags, status")
        e2.download_button("SRT subtitles", report.srt(res), f"{base}_{rlang.lower()}.srt", width="stretch")
        e3.download_button("QA report (Markdown)", report.qa_report_md(res, review), f"{base}_qa_report.md", width="stretch")
        e4, e5, e6 = st.columns(3)
        e4.download_button("Side by side (Markdown)", report.side_by_side_md(res, review), f"{base}_side_by_side.md",
                           width="stretch")
        e5.download_button("Adaptation (JSON)", json.dumps(res["rows"], ensure_ascii=False, indent=2),
                           f"{base}_adaptation.json", width="stretch")
        e6.download_button("Download all (.zip)", report.bundle_zip({base: res}, gl.to_json(entries_now()), S.cast_current,
                                                                     {base: review}), f"{base}_bundle.zip", width="stretch")


# ================================================================== QA LAB
with tab_lab:
    st.subheader("Does the QA actually catch mistakes?")
    st.caption("Break an adaptation on purpose: misspell names, pad lines past their window, flatten the cliffhanger. "
               "Then run the same QA and count what it caught. Recall = share of planted mistakes caught. "
               "Precision = share of new flags that point at a planted mistake.")
    done = [n for n in episodes if n in S.results]
    if not done:
        ui.empty("Adapt an episode first", "<p>The lab breaks a finished adaptation, so it needs at least one.</p>")
    else:
        l1, l2, l3, l4 = st.columns([3, 1, 1, 2])
        pick = l1.multiselect("Episodes", done, default=[S.selected] if S.selected in done else done[:1],
                              format_func=lambda n: episodes[n].meta.get("episode_number", n))
        n_names = l2.number_input("Name errors", 0, 6, 3)
        n_timing = l3.number_input("Timing errors", 0, 6, 3)
        with l4:
            flat = st.toggle("Flatten the cliffhanger", True)
            use_judge = st.toggle("Use the AI judge (1 call each)", llm.is_configured(), disabled=not llm.is_configured())
        if st.button("Plant mistakes and run QA", type="primary", disabled=not pick):
            out_rows, fps, per_kind = [], [], {}
            try:
                with st.spinner("Breaking things on purpose…"):
                    for n in pick:
                        e, r = episodes[n], S.results[n]
                        mutated, truth = ev.seed(e, r["targets"], entries_now(), r["lang"], n_names, n_timing, flat)
                        out = ev.evaluate(e, r["targets"], mutated, truth, entries_now(), r["lang"], use_judge and flat)
                        for row in out["rows"]:
                            out_rows.append({"episode": e.number, **row})
                        fps += [{"episode": e.number, **f} for f in out["false_positives"]]
                S.eval = {"rows": out_rows, "fps": fps, "judge": use_judge and flat}
            except llm.LLMError as e:
                st.error(str(e))
        if S.eval:
            rows_ = S.eval["rows"]
            tested = [r for r in rows_ if r["caught"] != "—"]
            caught = sum(r["caught"].startswith("✅") for r in tested)
            tp = caught
            prec = tp / (tp + len(S.eval["fps"])) if (tp + len(S.eval["fps"])) else 1.0
            kinds = sorted({r["seeded error"] for r in tested})
            items = [{"v": f"{caught / len(tested):.0%}" if tested else "n/a", "l": "recall: planted mistakes caught",
                      "tone": "good"}, {"v": f"{prec:.0%}", "l": "precision of new flags"}]
            for k in kinds:
                kt = [r for r in tested if r["seeded error"] == k]
                items.append({"v": f"{sum(r['caught'].startswith('✅') for r in kt)}/{len(kt)}", "l": f"{k} errors caught"})
            ui.stats(items)
            st.dataframe(pd.DataFrame(rows_), hide_index=True, width="stretch")
            if not S.eval["judge"]:
                st.caption("The cliffhanger row shows — because the AI judge was off: code alone can't tell a strong ending from a flat one.")
            with st.expander(f"New flags on lines we didn't touch ({len(S.eval['fps'])})"):
                st.write(pd.DataFrame(S.eval["fps"]) if S.eval["fps"] else "None.")
            st.download_button("Download lab results (.csv)", pd.DataFrame(rows_).to_csv(index=False), "qa_lab_results.csv")


# ================================================================== SEASON DASHBOARD
with tab_batch:
    st.subheader("Season dashboard")
    todo = [n for n in episodes if n not in S.results or S.results[n]["lang"] != lang]
    d1, d2, d3 = st.columns([3, 2, 2])
    d1.write(f"**{len(episodes) - len(todo)}** of **{len(episodes)}** episodes adapted into {lang}.")
    redo = d2.toggle("Redo finished episodes too", False)
    n_go = len(episodes) if redo else len(todo)
    if d3.button(f"Adapt {n_go} episode{'s' if n_go != 1 else ''}" if n_go else "All episodes adapted",
                 type="primary", width="stretch", disabled=not (todo or redo)):
        if need_model():
            if not S.gloss_current:
                st.warning("No glossary approved: names may drift between episodes. Build one in Series bible first.")
            bar = st.progress(0.0, text="Starting…")
            targets_ = list(episodes) if redo else todo
            for k, n in enumerate(targets_):
                try:
                    run_one(episodes[n], True, True, bar)
                except llm.LLMError as e:
                    st.error(f"{episodes[n].meta.get('episode_number', n)}: {e}")
            bar.empty()
            st.rerun()
    done = [(n, S.results[n]) for n in episodes if n in S.results]
    if not done:
        ui.empty("No episodes adapted yet", "<p>Adapt the whole season here, or one episode at a time in the Studio.</p>")
    else:
        mins = sum(episodes[n].duration for n, _ in done) / 60
        cost = sum(r["meta"].get("estimated_cost_usd", 0) for _, r in done)
        lines_ = sum(r["meta"]["dialogue_lines"] for _, r in done)
        fit = sum(r["meta"]["fit_after"] * r["meta"]["dialogue_lines"] for _, r in done) / max(1, lines_)
        hooks = [r["qa"]["judge"] for _, r in done if r["qa"]["judge"].get("ran")]
        ui.stats([{"v": len(done), "l": "episodes adapted"}, {"v": f"{mins:.1f}", "l": "minutes of story"},
                  {"v": f"{fit:.0%}", "l": "lines fit timing", "tone": "good"},
                  {"v": sum(len(r["qa"]["flags"]) for _, r in done), "l": "flags to review"},
                  {"v": f"{sum(h['hook_preserved'] and h['cliffhanger_preserved'] for h in hooks)}/{len(hooks)}",
                   "l": "episodes with hook and cliffhanger intact"},
                  {"v": f"${cost:.3f}", "l": f"total cost (${cost / max(mins, .01):.4f}/min)"}])
        summ = pd.DataFrame([{"Episode": episodes[n].number, "Spoken lines": r["meta"]["dialogue_lines"],
                              "Fit before": r["meta"]["fit_before"], "Fit after": r["meta"]["fit_after"],
                              "Flags": len(r["qa"]["flags"]), "High": sum(f["severity"] == "high" for f in r["qa"]["flags"]),
                              "Hook": r["qa"]["judge"].get("hook_preserved", "—") if r["qa"]["judge"].get("ran") else "—",
                              "Cliffhanger": r["qa"]["judge"].get("cliffhanger_preserved", "—") if r["qa"]["judge"].get("ran") else "—",
                              "Calls": r["meta"].get("model_calls", 0), "Cost ($)": r["meta"].get("estimated_cost_usd", 0),
                              "Seconds": r["meta"].get("elapsed_sec", 0), "Language": r["lang"]} for n, r in done])
        c1, c2 = st.columns(2)
        fit_long = summ.melt(id_vars="Episode", value_vars=["Fit before", "Fit after"], var_name="pass", value_name="fit")
        axis = dict(labelColor="#A99FB8", titleColor="#A99FB8", gridColor="#2A2235", domainColor="#3A3046")
        c1.altair_chart(alt.Chart(fit_long).mark_bar().encode(
            x=alt.X("Episode:O"), xOffset=alt.XOffset("pass:N", sort=["Fit before", "Fit after"]), y=alt.Y("fit:Q", axis=alt.Axis(format="%"), title="lines that fit"),
            color=alt.Color("pass:N", scale=alt.Scale(domain=["Fit before", "Fit after"], range=["#FFC145", "#FF7A1A"]),
                            sort=["Fit before", "Fit after"], legend=alt.Legend(orient="top", title=None)),
            tooltip=["Episode", "pass", alt.Tooltip("fit:Q", format=".0%")]).properties(height=240, title="Timing fit by episode")
            .configure_axis(**axis).configure_view(stroke=None).configure_title(color="#F5EFF7", font="Baloo 2", fontSize=15)
            .configure_legend(labelColor="#F5EFF7"), width="stretch", theme=None)
        fl = pd.DataFrame([{"Episode": episodes[n].number, "type": f["label"]} for n, r in done for f in r["qa"]["flags"]])
        if not fl.empty:
            c2.altair_chart(alt.Chart(fl).mark_bar().encode(
                x="Episode:O", y=alt.Y("count():Q", title="flags"),
                color=alt.Color("type:N", scale=alt.Scale(scheme="plasma"), legend=alt.Legend(orient="right", title=None)),
                tooltip=["Episode", "type", "count()"]).properties(height=240, title="What QA flagged")
                .configure_axis(**axis).configure_view(stroke=None).configure_title(color="#F5EFF7", font="Baloo 2", fontSize=15)
                .configure_legend(labelColor="#F5EFF7"), width="stretch", theme=None)
        st.dataframe(summ, hide_index=True, width="stretch",
                     column_config={"Fit before": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                                    "Fit after": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                                    "Cost ($)": st.column_config.NumberColumn(format="$%.4f")})
        st.download_button("Download the season bundle (.zip)",
                           report.bundle_zip(dict(done), gl.to_json(entries_now()), S.cast_current, S.reviews),
                           f"{S.show_title_v.lower().replace(' ', '_')}_season_bundle.zip", type="primary")


# ================================================================== HOW IT WORKS
with tab_how:
    st.subheader("How it works")
    ui.stepper([("Read the screenplay", "done"), ("Approve glossary and casting", "done"), ("Adapt scene by scene", "done"),
                ("Auto-fix and QA", "done"), ("Editor review", "done"), ("Export for dubbing", "done")])
    st.markdown("""
**1. Read.** Plain code parses scenes, speakers, emotions, O.S./V.O. delivery and every line's start and end time.
Unfamiliar formats get one AI call that rewrites them into the standard format, and the app says so.

**2. Approve.** An AI pass over the first episodes drafts a series glossary (names, places, recurring objects) and
the app maps every speaker label to a character. A person approves both. This is the human checkpoint.

**3. Adapt.** Each scene goes to the model with the glossary, the previous scene's summary, the action lines, and a
budget for every line (max words and syllables from its time window). The prompt asks for natural spoken dialogue,
not literal translation.

**4. Auto-fix and QA.** Code measures every line against its window, checks glossary spellings (including near-miss
variants like जुलियाना for जूलियाना), catches lines left in English, and spots aap/tum switches. Lines that fail are
rewritten once; a rewrite is kept only if it isn't longer. One AI judge call checks that the hook and the cliffhanger
still land and points out lines that sound translated.

**5. Review.** The editor sees flagged lines first, edits in place, and every edit is re-checked by the same code.

**6. Export.** A dubbing sheet in Excel (character, delivery, emotion, timing, flags, status), SRT subtitles,
Markdown reports, JSON, and a season bundle.

**What the numbers mean**
- *Fit*: estimated spoken length ≤ window + a small breath allowance, at the chosen syllables or words per second.
  Syllables are counted per akshara for Indic scripts, with Hindi final-schwa deletion.
- *Recall / precision* (QA lab): planted mistakes caught / new flags that were real.
- *Cost*: tokens × the price you set in `PRICE_IN_PER_M` / `PRICE_OUT_PER_M`.

**Limits, stated plainly**
- Timing is a heuristic, not audio duration. Calibrate it with a stopwatch.
- Quality depends on the model. Slang, idioms and cultural references are the weak spot; a native reviewer stays in the loop.
- Only Hindi has been checked by a reader. Other languages run, but claim nothing until someone reviews them.
- Nothing is stored server-side. Closing the tab clears the session, so download your work.
""")
