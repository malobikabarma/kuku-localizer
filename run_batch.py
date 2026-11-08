"""Command-line batch run for the evaluation write-up (no UI).

    python run_batch.py data/*.txt --lang Hindi --glossary-from 3 --out outputs/

Writes per-episode reports, a season bundle, and a QA-lab table (seeded errors) to the output folder.
Keep `data/` and `outputs/` out of git: the input pack is confidential."""
import argparse
import json
from pathlib import Path

import pandas as pd

import evaluation as ev
import glossary as gl
import llm
import pipeline
import report
import screenplay as sp
import series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--lang", default="Hindi")
    ap.add_argument("--glossary", help="approved glossary JSON (skips AI extraction)")
    ap.add_argument("--glossary-from", type=int, default=3, help="episodes the AI reads to draft a glossary")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--seed-errors", action="store_true", help="also run the QA lab on every episode")
    ap.add_argument("--out", default="outputs")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    eps = sorted((sp.parse_with_fallback(sp.read_file_text(f, Path(f).read_bytes()), Path(f).stem) for f in a.files),
                 key=lambda e: e.number)
    print(f"Read {len(eps)} episodes, {sum(len(e.dialogue) for e in eps)} spoken lines.")

    if a.glossary:
        entries = gl.from_json(Path(a.glossary).read_text(encoding="utf-8"))
    else:
        entries = gl.extract_glossary(eps[:a.glossary_from], a.lang)
        (out / "glossary_draft.json").write_text(gl.to_json(entries), encoding="utf-8")
        print(f"Drafted {len(entries)} glossary entries -> {out / 'glossary_draft.json'} (review it!)")

    cast_rows = series.speaker_table(eps, entries)
    cast = series.cast_map(cast_rows)
    results, lab = {}, []
    for e in eps:
        try:
            res = pipeline.run_episode(e, a.lang, entries, cast.get(e.number, {}), run_judge=not a.no_judge,
                                       progress=lambda f, m: None)
        except llm.LLMError as err:
            print(f"  {e.name}: FAILED {err}")
            continue
        results[e.name] = res
        m = res["meta"]
        print(f"  Ep {e.number}: fit {m['fit_before']:.0%} -> {m['fit_after']:.0%}, {len(res['qa']['flags'])} flags, "
              f"{m['model_calls']} calls, ${m['estimated_cost_usd']:.4f}")
        if a.seed_errors:
            mutated, truth = ev.seed(e, res["targets"], entries, a.lang)
            r = ev.evaluate(e, res["targets"], mutated, truth, entries, a.lang, run_judge=not a.no_judge)
            lab += [{"episode": e.number, **row} for row in r["rows"]]
            lab += [{"episode": e.number, "line": f["id"], "seeded error": "none (false positive)",
                     "what changed": f["reason"], "caught": "n/a"} for f in r["false_positives"]]

    (out / "season_bundle.zip").write_bytes(report.bundle_zip(results, gl.to_json(entries), cast_rows))
    if lab:
        pd.DataFrame(lab).to_csv(out / "qa_lab.csv", index=False)
    print(f"Done. Outputs in {out}/")


if __name__ == "__main__":
    main()
