# Kuku Localizer

A localization editor uploads English microdrama screenplays and gets back a natural spoken adaptation
(Hindi by default) plus a QA report that says which lines to review: lines that won't fit the original timing,
hooks and cliffhangers that lost their punch, and names that drift between episodes.

Plain translation is a commodity. The value here is the QA layer, and most of it is code you can test.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then paste your API key into .env
streamlit run app.py
```

Press **Load demo** in the sidebar to see a finished episode without any API key.

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository (the `.gitignore` keeps `data/`, `outputs/` and secrets out).
2. On share.streamlit.io, create an app from the repo with `app.py` as the main file.
3. In **App settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example` with your own key.
   Set `APP_PASSWORD` if the link will be shared.

Hugging Face Spaces works too: choose the Streamlit SDK and add the same values as Space secrets.

## Switch model or language

- Model: change `API_BASE`, `API_KEY`, `MODEL_NAME`. Any OpenAI-compatible endpoint works (Gemini, OpenAI, Groq,
  OpenRouter, a local vLLM or Ollama server). Every call goes through `call_llm()` in `llm.py`.
- Language: pick it in the sidebar, or set `TARGET_LANGUAGE`. Syllable timing supports every major Indic script.
- The provider URL is deliberately not editable in the UI, so a visitor can't redirect your key to another server.

## What the app does

| Tab | What it's for |
|---|---|
| **Studio** | One episode: adapt, see hook and cliffhanger verdicts, a timing chart, and an editable review table. Edits are re-checked by the same code. |
| **Series bible** | The series glossary (the human checkpoint) and voice casting: maps every speaker label to a character across episodes and lists continuity problems. |
| **QA lab** | Plants mistakes on purpose (misspelled names, padded lines, a flattened cliffhanger) and measures recall and precision of the QA. |
| **Season dashboard** | Adapts every episode, charts timing fit and flags per episode, totals cost, downloads a season bundle. |
| **How it works** | The method, the metric definitions and the limits. |

Exports per episode: Excel dubbing sheet (character, delivery, emotion, timing, flags, editor status),
SRT subtitles, QA report and side-by-side in Markdown, JSON, or everything in one zip.

## Pipeline

1. **Parse** (`screenplay.py`, no AI): scenes, speakers, emotions, O.S./V.O., start and end times.
   Unfamiliar formats get one AI call that rewrites them into the standard format, and the app says so.
2. **Glossary and casting** (`glossary.py`, `series.py`): AI drafts names and terms from the first episodes;
   a person approves them. Speaker labels are mapped to characters per episode.
3. **Adapt** (`adapt.py`): scene by scene, with the glossary, the previous scene's summary, the action lines,
   and a word and syllable budget for every line derived from its time window.
4. **QA** (`qa.py`): code checks timing, glossary spellings (including near-miss variants such as
   जुलियाना for जूलियाना), names left in English, lines not in the target script, and aap/tum switches.
   Failing lines are rewritten once, and a rewrite is kept only if it isn't longer.
   One AI judge call checks the hook, the cliffhanger, and lines that sound translated.
5. **Review and export** (`app.py`, `report.py`).

## Evaluate on the input pack

Keep the pack in `data/` (git-ignored) and run:

```bash
python run_batch.py data/*.txt --lang Hindi --seed-errors --out outputs/
```

This drafts a glossary (`outputs/glossary_draft.json`: review it, then rerun with `--glossary`),
adapts every episode, prints fit before and after the rewrite pass, cost per episode, and writes
`outputs/qa_lab.csv` with the seeded-error results. Then score the Hindi yourself per episode
(natural / acceptable / bad) and record the failures you find.

Findings from parsing the 10-episode pack (no model needed):

- 312 spoken lines, parsed with zero warnings.
- At 6 syllables per second, 99.7% of the English source lines fit their own windows, so the threshold
  does not flag normal speech.
- Speaker labels are inconsistent, which matters for dubbing: the hero appears as THE BEARDED STRANGER,
  MYSTERIOUS BEARDED MAN, SCARRED BEARDED MAN and ALEXANDER; BLOND NOBLEMAN is Juliana's father in
  Episode 2 but a different man in Episode 9; THE FORMER GROOM is Gerald in Episodes 1–2 but speaks like a
  servant in Episode 9. The voice-casting tab exists to catch this.

## Tests

```bash
API_BASE=mock python -m pytest -q
```

`API_BASE=mock` swaps in a fake model, so the tests and a full click-through of the app run offline.

## Limits

- Timing is a heuristic (syllables or words per second), not audio duration. Calibrate it with a stopwatch.
- Quality depends on the model. Slang, idioms and cultural references are the weak spot; a native reviewer stays in the loop.
- Name-variant detection catches vowel-length, nukta and nasal-mark confusions exactly, and fuzzy matches only for
  names of 6+ characters. A dropped vowel sign in a short name (कका for काका) is missed on purpose: looser matching
  flags real words such as मरा ("died") as misspellings of मीरा.
- Only Hindi has been checked by a reader. Other languages run, but claim nothing until someone reviews them.
- Settings changed in the sidebar apply to the running server process; on a shared deployment, concurrent users
  can affect each other's model and timing settings.
- Nothing is stored server-side. Closing the tab clears the session, so download your work.

## Files

```
app.py            Streamlit UI
ui.py             theme and HTML components
config.py         settings from env / .env / Streamlit secrets
llm.py            call_llm(): one swappable model call, usage and cost tracking, mock backend
screenplay.py     parser and file readers (txt, md, docx, pdf)
timing.py         word and Indic syllable counting, fit checks
glossary.py       glossary extraction, editing, import/export
adapt.py          adaptation and rewrite prompts
qa.py             code checks and the AI judge
pipeline.py       end-to-end run for one episode
series.py         voice casting and continuity
evaluation.py     seeded-error QA lab
report.py         Excel, SRT, Markdown, JSON, zip
run_batch.py      command-line season run for the evaluation write-up
sample/           an original demo script with a hand-written Hindi adaptation (not from the client pack)
tests/            unit tests and an app click-through
```
