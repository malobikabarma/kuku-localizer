"""Seeded-error test: break an adaptation on purpose, re-run QA, and count what it caught.
Gives recall per error type and precision of the new flags. Code checks cost nothing; the
cliffhanger test needs one judge call."""
import random

import qa
import timing

# the misspellings Hindi scripts really contain, most common first: vowel length, nukta, diphthongs, a dropped matra
VOWEL_SWAPS = [("ी", "ि"), ("ू", "ु"), ("ि", "ी"), ("ु", "ू"), ("ज़", "ज"), ("ज", "ज़"), ("फ़", "फ"), ("ो", "ौ"),
               ("े", "ै"), ("ा", "")]
FILLER = {"hindi": "और मैं तुम्हें फिर से बताना चाहती हूँ कि", "default": "and I want to tell you once again that"}
FLAT = {"hindi": "ठीक है, चलो चलते हैं।", "default": "Okay, let's go."}


def _variant(word):
    for a, b in VOWEL_SWAPS:
        if a in word:
            return word.replace(a, b, 1)
    return None


def seed(ep, targets, entries, lang, n_names=3, n_timing=3, flatten_cliffhanger=True, rng_seed=7):
    rng = random.Random(rng_seed)
    mutated, truth = dict(targets), []
    clean_flags, _ = qa.code_checks(ep, targets, entries, lang)
    flagged = {(f["id"], f["type"]) for f in clean_flags}
    spoken = [l for l in ep.dialogue if targets.get(l.id)]
    last_id = spoken[-1].id if spoken else None

    # 1) name errors: misspell an approved name, or leave it in English
    name_words = [(w, e) for e in entries for t in e.targets for w in t.split() if len(w) >= 4]
    cands = [(l, w, e) for l in spoken for w, e in name_words if w in targets[l.id] and l.id != last_id]
    rng.shuffle(cands)
    used = set()
    for l, w, e in cands:
        if len([t for t in truth if t["kind"] == "name"]) >= n_names:
            break
        if l.id in used:
            continue
        v = _variant(w)
        if v and v != w:
            mutated[l.id] = mutated[l.id].replace(w, v, 1)
            truth.append({"id": l.id, "kind": "name", "expect": {"variant"}, "what": f"'{w}' → '{v}'"})
        else:
            mutated[l.id] = mutated[l.id].replace(w, e.english, 1)
            truth.append({"id": l.id, "kind": "name", "expect": {"latin_name", "variant"}, "what": f"'{w}' → '{e.english}'"})
        used.add(l.id)

    # 2) timing errors: pad a line that currently fits until it clearly overruns
    filler = FILLER.get(lang.lower(), FILLER["default"])
    fit_lines = [l for l in spoken if l.id not in used and l.id != last_id and (l.id, "timing") not in flagged]
    for l in rng.sample(fit_lines, min(n_timing, len(fit_lines))):
        text = mutated[l.id]
        while timing.check(text, l.duration)["usage"] < 1.4:
            text = f"{filler} {text}"
        mutated[l.id] = text
        truth.append({"id": l.id, "kind": "timing", "expect": {"timing"}, "what": "padded to ~140% of its window"})
        used.add(l.id)

    # 3) flatten the cliffhanger
    if flatten_cliffhanger and last_id:
        mutated[last_id] = FLAT.get(lang.lower(), FLAT["default"])
        truth.append({"id": last_id, "kind": "cliffhanger", "expect": {"cliffhanger", "natural"},
                      "what": f"last line replaced with '{mutated[last_id]}'"})
    return mutated, truth


def evaluate(ep, clean_targets, mutated, truth, entries, lang, run_judge=False):
    clean_flags, _ = qa.code_checks(ep, clean_targets, entries, lang)
    new_flags, _ = qa.code_checks(ep, mutated, entries, lang)
    judge_note = "Cliffhanger test skipped (AI judge off)."
    if run_judge:
        j = qa.judge(ep, mutated, lang)
        new_flags += qa.judge_flags(j)
        judge_note = "AI judge ran on the broken version."
    before = {(f["id"], f["type"]) for f in clean_flags}
    fresh = [f for f in new_flags if (f["id"], f["type"]) not in before]
    seeded_ids = {t["id"] for t in truth}

    rows, by_kind = [], {}
    for t in truth:
        if t["kind"] == "cliffhanger" and not run_judge:
            caught = None
        else:
            caught = any(f["id"] == t["id"] and f["type"] in t["expect"] for f in fresh)
        rows.append({"line": t["id"], "seeded error": t["kind"], "what changed": t["what"],
                     "caught": "—" if caught is None else ("✅ yes" if caught else "❌ no")})
        if caught is not None:
            k = by_kind.setdefault(t["kind"], [0, 0])
            k[0] += int(caught)
            k[1] += 1
    tp = sum(1 for f in fresh if f["id"] in seeded_ids)
    fp = [f for f in fresh if f["id"] not in seeded_ids]
    tested = [r for r in rows if r["caught"] != "—"]
    recall = sum(r["caught"].startswith("✅") for r in tested) / len(tested) if tested else 0.0
    precision = tp / (tp + len(fp)) if (tp + len(fp)) else 1.0
    return {"rows": rows, "recall": recall, "precision": precision,
            "recall_by_kind": {k: v[0] / v[1] for k, v in by_kind.items()},
            "false_positives": fp, "note": judge_note}
