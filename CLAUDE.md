# mandarin-tools — Project Context & Handoff

This document summarizes work done on mandarin-tools in a prior Claude.ai chat
session, for context in a new Claude Code session working directly on the repo.

## Project overview

mandarin-tools is a Mandarin language-learning web app. Core features: paste
Chinese text, segment it into words, filter/score results based on per-user
vocabulary familiarity, and use that to gauge passage difficulty.

**Stack:**
- Backend: FastAPI + Python, SQLAlchemy 2.0, Alembic migrations, `uv` for
  package/env management
- Database: PostgreSQL 17 (created with `LC_COLLATE='C'`, `LC_CTYPE='C'`,
  `TEMPLATE=template0` for correct Chinese UTF-8 handling on Windows)
- Frontend: SvelteKit + TypeScript + Tailwind CSS v4, SSR disabled globally
  (localStorage-based auth)
- Auth: JWT with pwdlib + argon2
- Repo: `github.com/wantsomechocolate/mandarin-tools` (public)

Code layout follows a modular-monolith pattern: `backend/app/modules/`
contains feature modules (currently `known_words`, `auth`). Segmentation code
lives *inside* `known_words` rather than as its own module — deferred
splitting it out until a second consumer of segmentation actually appears
(e.g. a future reading-difficulty scorer or flashcard tool).

## Segmentation: DAG + DP over the existing trie

The original segmenter was a longest-matching trie walk
(`known_words/segmentor.py`, `trie.py`, `trie_loader.py`) plus a tokenizer
for flagging repeated unknown character sequences (`tokenizer.py`).

We replaced it with a jieba-inspired approach in
`known_words/dag_segmentor.py` + `segmenter_loader.py`:
- Build a DAG of every dictionary-backed word boundary from each position,
  not just the longest match
- Right-to-left dynamic programming over the DAG, using `log(word_frequency)`
  as edge weight, to find the *globally* best-scoring segmentation — this
  fixes cases longest-matching gets wrong (e.g. 研究生命起源 correctly splits
  as 研究/生命/起源, not 研究生/命/起源)
- Deliberately **skipped jieba's HMM/Viterbi new-word-discovery layer**: for
  this app, an unresolved character sequence is useful signal (something to
  flag for the user), not a failure to paper over the way it is for a
  general-purpose segmenter. The existing tokenizer's unknown-sequence
  detection serves that role instead, more transparently than an HMM guess
  would.
- Also skipped: keyword extraction, POS tagging, traditional Chinese support
  (deferred — see below), search-mode re-slicing. None of these affect
  segmentation quality for this app's use case.

**Per-user custom dictionary (`UserWord` overlay):** `UserOverlay` in
`dag_segmentor.py` is a small per-request trie+frequency table built fresh
from a user's `UserWord` rows (`segmenter_loader.build_user_overlay`). It's
checked alongside the global trie during DAG construction, with a frequency
high enough to reliably win in the DP (`Segmenter.dominance_floor()`). The
shared global `Segmenter` is never mutated — this was a deliberate design
choice to avoid per-request race conditions on shared state.

**Combined production analysis (`service.analyze_text_combined`):** DAG+DP
is the source of truth. The original longest-matching segmenter still runs
alongside it purely as a safety net for dictionary coverage gaps (a word
missing from `dictionary_words` entirely has no DP path, but
longest-matching's overlapping-match scan sometimes stumbles onto pieces of
it). Any word longest-matching finds that DAG missed is included tagged
`source="longest_match_only"` — DAG's own picks are never overridden. This
surfaces dictionary gaps for review rather than hiding them or silently
trusting the weaker algorithm.

**Traditional Chinese (deferred, not built):** established as a *data*
problem, not an algorithm problem — the DAG+DP logic is script-agnostic, so
traditional support is really "build a second trie from traditional-Chinese
frequency data" (candidate approaches: OpenCC conversion of the existing
simplified dictionary, or a native traditional corpus). Schema is meant to
stay loosely typed enough (no hardcoded simplified-only assumptions) that
this is additive later rather than a rewrite. Also flagged as an open product
question: whether simplified/traditional word pairs should share a user's
familiarity score or be tracked independently.

## Word categorization: three distinct, deliberately separate concepts

Working through real test cases (segmenting 三只小猪 / Three Little Pigs)
surfaced a need for a category between "known vocabulary" and "garbage,"
which led to this model:

1. **`KnownWord`** — familiarity score (1-5) for real vocabulary the user is
   studying/has studied.
2. **`GarbageWord`** — numbers, punctuation, junk. Excluded from analysis
   results *before they're ever persisted* (see `service.filter_results`,
   called from the `/analyze` endpoint before `AnalysisResult` rows are
   saved). One-way: once garbage, permanently invisible, no revisit path.
3. **`Fragment`** (new) — real Chinese content that isn't worth studying
   (e.g. 的房子, 猪的, 哥猪和 — segmentation artifacts that span word
   boundaries) but *is* worth annotating and occasionally revisiting.
   Critically: **has no relationship to `DictionaryWord` or `UserWord` at
   all** — marking something a fragment must never feed the trie/frequency
   table or the per-user segmentation overlay, or it would reinforce the
   exact segmentation error being flagged. Unlike garbage, fragments are
   *not* excluded before persistence — they stay in the normal
   `analysis_results`, and hiding them is a client-side toggle
   (`hideFragments`, default on, with a "Show fragments (N)" checkbox),
   mirroring how `longest_match_only` supplemental words are handled. This
   makes fragment-marking fully reversible and inspectable, unlike garbage.

If a word is both a `UserWord` and a `Fragment` at once (contradictory — a
fragment shouldn't also be reinforced in the dictionary), the UI shows an
explicit warning in the word-detail panel rather than silently resolving it.

**`UserWord` also gained rich fields:** `pronunciation` (renamed from an
earlier `pinyin` — see migration note below), `meaning`, `notes`. Adding any
of these via the word-detail panel auto-creates the `UserWord` row via an
upsert endpoint (`PUT /known-words/user-words/{word}`) — no separate "add"
step needed, since filling in a definition already implies "this is a word I
care about."

## Word-detail panel: early steps toward a Pleco-style multi-source view

Long-term goal (explicitly deferred, not built): instead of merging all data
sources into one uniform schema, display each source's info under its own
heading, in whatever shape that source provides it — closer to how Pleco
handles multiple dictionaries. Currently only two real sources exist (HSK
entries/forms, corpus frequency) plus the new user-entered data, so the
generalized multi-source data model isn't worth building yet — better to
design it once a second/third *real* data source's actual shape is known
rather than guess. In the meantime, the current `WordDetail` response has
`user_word` and `fragment` as separate nested objects (not merged into the
flat HSK/frequency fields), and the frontend panel labels these as visually
distinct sections ("Dictionary" / "Your entry" / "Fragment") — a cheap step
that doesn't require the full abstraction but leaves a visual seam to extend
later.

## Known naming history (context, not action needed)

A `UserWord.pinyin` field was originally added, then renamed to
`pronunciation` by hand-editing the not-yet-applied migration before running
it — so the live database only ever had `pronunciation`, never `pinyin`.
(An earlier round of confusion in the prior chat incorrectly diagnosed this
as a migration-history mismatch requiring a repair migration — it wasn't;
that repair migration was generated but should be deleted/ignored if it's
still present in `migrations/versions/`, since it describes a rename that
never needs to happen.) The actual bug that occurred was unrelated to
migration timing: a full-file regeneration of `models.py` during later work
was done from a stale local copy that still said `pinyin`, silently
clobbering the hand-made rename. **Lesson for this Code session:** since
Code works directly on the live checkout, this entire class of drift
(stale local copy vs. actual repo state) shouldn't recur — there's no
fetch/patch round trip anymore.

## Testing

- `backend/tests/known_words/test_dag_segmentor.py` — synthetic-dictionary
  unit tests, no DB required (`uv run pytest tests/known_words/ -v`). Covers
  DAG-vs-longest-match disagreement cases, overlay behavior/non-mutation,
  and the combined-analysis supplemental-tagging behavior.
- `backend/scripts/compare_segmenters.py` — CLI script to compare both
  segmenters against the real dictionary/Postgres data on sample or custom
  text (`uv run python scripts/compare_segmenters.py --text "..."`).
- `POST /known-words/compare-segmentation` — non-persisting API endpoint for
  side-by-side comparison from the frontend/Swagger UI.

## Open items / natural next steps

- No UI action yet to promote a `longest_match_only` supplemental word
  directly into `UserWord` from the results table (currently: view it, then
  use the existing "+ Add word" button separately).
- `GarbageWord` categorization (numbers/punctuation/misc subtypes) was
  floated but deliberately not built — a separate need from `Fragment`, not
  yet necessary.
- Traditional Chinese support (see above) — not started.
- The generalized multi-source `WordDetail` data model (Pleco-style) — not
  started, deferred until a second/third real data source is in hand.
- Deployment: planned single Hetzner VPS, FastAPI + SvelteKit behind Caddy,
  self-hosted Postgres — not yet started.