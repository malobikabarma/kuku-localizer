"""Look and feel. One memorable element (the episode cover shelf); everything else stays quiet."""
import html

import streamlit as st

COVERS = [("#FF7A1A", "#FF4F70"), ("#FFC145", "#FF7A1A"), ("#7A3CFF", "#FF4F70"), ("#FF4F70", "#8B1E4F"),
          ("#FF9A3D", "#B4235A"), ("#3B2A8F", "#FF7A1A")]

CSS = """
<style>
:root{
  --ink:#15111C; --panel:#201A29; --panel-2:#2A2235; --line:#3A3046;
  --text:#F5EFF7; --muted:#A99FB8; --kuku:#FF7A1A; --saffron:#FFC145; --rose:#FF4F70; --mint:#3DD9A0;
}
.block-container{padding-top:3.2rem; max-width:1380px;}
h1,h2,h3{letter-spacing:-0.01em;}
a{color:var(--saffron);}
/* hero */
.kl-hero{display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin:0 0 18px 0; flex-wrap:wrap;}
.kl-hero h1{font-family:'Baloo 2',sans-serif; font-weight:800; font-size:clamp(2.1rem,4vw,3.3rem); line-height:1.02; margin:0; padding:0;}
.kl-hero p{color:var(--muted); margin:6px 0 0 0; font-size:1.02rem;}
.kl-route{display:inline-flex; align-items:center; gap:10px; background:var(--panel); border:1px solid var(--line);
  border-radius:999px; padding:6px 14px; font-weight:600;}
.kl-route b{color:var(--kuku);}
/* shelf */
.kl-tile{border-radius:16px; overflow:hidden; background:var(--panel); border:1px solid var(--line); margin-bottom:6px;}
.kl-tile.sel{outline:2px solid var(--kuku); outline-offset:2px;}
.kl-cover{height:104px; position:relative; padding:10px 12px;}
.kl-cover .ep{font-family:'Baloo 2',sans-serif; font-size:.82rem; font-weight:600; color:rgba(255,255,255,.85);}
.kl-cover .num{position:absolute; left:10px; bottom:-14px; font-family:'Baloo 2',sans-serif; font-weight:800;
  font-size:4.1rem; line-height:1; color:rgba(255,255,255,.95); text-shadow:0 2px 18px rgba(0,0,0,.25);}
.kl-cover .dur{position:absolute; right:10px; top:10px; font-size:.78rem; background:rgba(21,17,28,.45);
  padding:2px 8px; border-radius:999px; color:#fff;}
.kl-body{padding:12px 12px 10px 12px;}
.kl-body .log{font-size:.83rem; color:var(--muted); line-height:1.35; height:2.7em; overflow:hidden;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;}
.kl-chip{display:inline-block; font-size:.76rem; padding:2px 9px; border-radius:999px; margin-top:8px;
  border:1px solid var(--line); color:var(--muted);}
.kl-chip.done{border-color:rgba(61,217,160,.5); color:var(--mint);}
.kl-chip.warn{border-color:rgba(255,193,69,.5); color:var(--saffron);}
/* episode header */
.kl-ephead{display:flex; gap:18px; align-items:flex-start; margin:4px 0 10px 0;}
.kl-ephead .badge{flex:0 0 auto; width:74px; height:74px; border-radius:18px; display:flex; align-items:center;
  justify-content:center; font-family:'Baloo 2',sans-serif; font-weight:800; font-size:2.2rem; color:#fff;}
.kl-ephead h2{font-family:'Baloo 2',sans-serif; margin:0; font-size:1.7rem; line-height:1.1;}
.kl-ephead .log{color:var(--text); margin:4px 0 2px 0; max-width:75ch;}
.kl-ephead .cont{color:var(--muted); font-size:.88rem; max-width:80ch;}
.kl-facts{display:flex; gap:22px; flex-wrap:wrap; margin-top:8px; color:var(--muted); font-size:.9rem;}
.kl-facts b{color:var(--text); font-weight:600;}
/* stepper (a real sequence, so numbered) */
.kl-steps{display:flex; gap:0; margin:12px 0 18px 0; flex-wrap:wrap;}
.kl-step{display:flex; align-items:center; gap:8px; padding:6px 14px 6px 0; color:var(--muted); font-size:.92rem;}
.kl-step .dot{width:26px; height:26px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-weight:700; font-size:.82rem; border:1.5px solid var(--line);}
.kl-step.done{color:var(--text);} .kl-step.done .dot{background:var(--kuku); border-color:var(--kuku); color:#1a1009;}
.kl-step.now{color:var(--text);} .kl-step.now .dot{border-color:var(--kuku); color:var(--kuku);}
.kl-step .bar{width:28px; height:2px; background:var(--line); margin-left:6px;}
/* stats */
.kl-stats{display:flex; flex-wrap:wrap; gap:10px; margin:6px 0 14px 0;}
.kl-stat{background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:12px 16px; min-width:150px; flex:1;}
.kl-stat .v{font-family:'Baloo 2',sans-serif; font-weight:700; font-size:1.75rem; line-height:1.1;}
.kl-stat .l{color:var(--muted); font-size:.84rem;}
.kl-stat .d{font-size:.8rem; margin-left:6px; color:var(--mint);}
.kl-stat.good .v{color:var(--mint);} .kl-stat.bad .v{color:var(--rose);} .kl-stat.hot .v{color:var(--kuku);}
/* verdict cards */
.kl-card{background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--mint); border-radius:14px;
  padding:14px 16px; height:100%;}
.kl-card.bad{border-left-color:var(--rose);} .kl-card.na{border-left-color:var(--line);}
.kl-card h4{margin:0 0 4px 0; font-family:'Baloo 2',sans-serif; font-size:1.15rem; display:flex; gap:10px; align-items:center;}
.kl-card .why{color:var(--muted); font-size:.88rem; margin:2px 0 10px 0;}
.kl-pair{border-top:1px solid var(--line); padding:8px 0;}
.kl-pair .en{color:var(--muted); font-size:.86rem;}
.kl-pair .tg{font-size:1.08rem; font-weight:500;}
.kl-pair .who{font-size:.76rem; color:var(--saffron);}
.kl-pill{display:inline-block; font-size:.74rem; font-weight:600; padding:2px 10px; border-radius:999px;}
.kl-pill.ok{background:rgba(61,217,160,.14); color:var(--mint);}
.kl-pill.high,.kl-pill.no{background:rgba(255,79,112,.15); color:var(--rose);}
.kl-pill.medium{background:rgba(255,193,69,.15); color:var(--saffron);}
.kl-pill.low{background:rgba(169,159,184,.15); color:var(--muted);}
.kl-issue{background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px 14px; margin-bottom:8px;}
.kl-issue .s{color:var(--muted); font-size:.86rem; margin-top:2px;}
.kl-empty{border:1.5px dashed var(--line); border-radius:18px; padding:28px; text-align:left; color:var(--muted);}
.kl-empty h3{color:var(--text); font-family:'Baloo 2',sans-serif; margin:0 0 6px 0;}
.kl-brand{font-family:'Baloo 2',sans-serif; font-weight:800; font-size:1.6rem; line-height:1; margin:0 0 2px 0;}
.kl-brand span{color:var(--kuku);}
.kl-sub{color:var(--muted); font-size:.85rem; margin-bottom:10px;}
.kl-demo{background:rgba(255,193,69,.10); border:1px solid rgba(255,193,69,.35); color:var(--saffron);
  border-radius:12px; padding:8px 14px; font-size:.9rem; margin-bottom:12px;}
.st-key-shelf .stButton button{border-radius:10px; font-size:.85rem; padding:.2rem .6rem; min-height:2rem;}
div[data-testid="stTabs"] button p{font-size:1rem; font-weight:600;}
@media (prefers-reduced-motion: reduce){*{transition:none!important; animation:none!important;}}
</style>
"""


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def cover(n: int):
    a, b = COVERS[(max(n, 1) - 1) % len(COVERS)]
    return f"background:linear-gradient(135deg,{a} 0%,{b} 100%);"


def md(h: str):
    st.markdown(h, unsafe_allow_html=True)


def sidebar_brand():
    md('<div class="kl-brand">kuku <span>localizer</span></div>'
       '<div class="kl-sub">Dub-ready adaptations for microdrama, with QA an editor can trust.</div>')


def hero(title, n_eps, lang, minutes, subtitle=None):
    sub = subtitle or f'{n_eps} episode{"s" if n_eps != 1 else ""} loaded, {minutes:.1f} minutes of story'
    md(f'<div class="kl-hero"><div><h1>{esc(title)}</h1>'
       f'<p>{esc(sub)}</p></div>'
       f'<div class="kl-route">English <b>➜</b> {esc(lang)}</div></div>')


def tile(ep, result, selected: bool):
    n = ep.number or 0
    mins = ep.duration
    if result:
        high = sum(f["severity"] == "high" for f in result["qa"]["flags"])
        chip = (f'<span class="kl-chip {"warn" if high else "done"}">{result["meta"]["fit_after"]:.0%} fit, '
                f'{len(result["qa"]["flags"])} flags</span>')
    else:
        chip = '<span class="kl-chip">Not adapted yet</span>'
    log = ep.meta.get("episode_logline", "") or "No logline in the script."
    md(f'<div class="kl-tile {"sel" if selected else ""}"><div class="kl-cover" style="{cover(n)}">'
       f'<div class="ep">Episode</div><div class="dur">{int(mins // 60)}:{int(mins % 60):02d}</div>'
       f'<div class="num">{n:02d}</div></div><div class="kl-body"><div class="log">{esc(log)}</div>{chip}</div></div>')


def episode_header(ep):
    n = ep.number or 0
    md(f'<div class="kl-ephead"><div class="badge" style="{cover(n)}">{n:02d}</div><div>'
       f'<h2>{esc(ep.meta.get("episode_number", ep.name))}</h2>'
       f'<div class="log">{esc(ep.meta.get("episode_logline", ""))}</div>'
       f'<div class="cont">{esc(ep.meta.get("continuity_notes", ""))}</div>'
       f'<div class="kl-facts"><span><b>{len(ep.dialogue)}</b> spoken lines</span>'
       f'<span><b>{len(ep.lines) - len(ep.dialogue)}</b> camera, action and sound cues</span>'
       f'<span><b>{len(ep.scenes) or 1}</b> scene{"s" if len(ep.scenes) != 1 else ""}</span>'
       f'<span><b>{int(ep.duration // 60)}:{int(ep.duration % 60):02d}</b> runtime</span>'
       f'<span><b>{len({l.speaker for l in ep.dialogue})}</b> speakers</span></div></div></div>')


def stepper(steps):
    """steps: list of (label, state) where state in done|now|todo."""
    parts = []
    for i, (label, state) in enumerate(steps, 1):
        bar = '<span class="bar"></span>' if i < len(steps) else ""
        dot = "✓" if state == "done" else str(i)
        parts.append(f'<div class="kl-step {state}"><span class="dot">{dot}</span>{esc(label)}{bar}</div>')
    md(f'<div class="kl-steps">{"".join(parts)}</div>')


def stats(items):
    """items: list of dicts {v, l, tone?, d?}"""
    out = []
    for it in items:
        d = f'<span class="d">{esc(it["d"])}</span>' if it.get("d") else ""
        out.append(f'<div class="kl-stat {it.get("tone", "")}"><div class="v">{esc(it["v"])}{d}</div>'
                   f'<div class="l">{esc(it["l"])}</div></div>')
    md(f'<div class="kl-stats">{"".join(out)}</div>')


def verdict_card(title, ok, reason, pairs, lang):
    """pairs: list of (speaker, english, target)."""
    cls = "na" if ok is None else ("" if ok else "bad")
    pill = ('<span class="kl-pill low">Not judged</span>' if ok is None else
            '<span class="kl-pill ok">Kept its punch</span>' if ok else '<span class="kl-pill no">Weakened</span>')
    rows = "".join(f'<div class="kl-pair"><div class="who">{esc(s.title())}</div><div class="tg">{esc(t) or "…"}</div>'
                   f'<div class="en">{esc(e)}</div></div>' for s, e, t in pairs)
    md(f'<div class="kl-card {cls}"><h4>{esc(title)} {pill}</h4><div class="why">{esc(reason)}</div>{rows}</div>')


def issue(sev, text, suggestion=""):
    md(f'<div class="kl-issue"><span class="kl-pill {esc(sev)}">{esc(sev)}</span> {esc(text)}'
       f'{f"<div class=s>{esc(suggestion)}</div>" if suggestion else ""}</div>')


def empty(title, body):
    md(f'<div class="kl-empty"><h3>{esc(title)}</h3>{body}</div>')


def demo_banner():
    md('<div class="kl-demo">You are looking at the built-in demo: an original script with a hand-written Hindi '
       'adaptation and two planted mistakes. Code checks run live; the AI verdict is stored. Upload your own '
       'episodes to run the real pipeline.</div>')
