# Known bugs

Open, reproducible issues that aren't blocking whatever feature they were
found alongside, so they're tracked here instead of fixed inline. Not a
full issue tracker — just enough to not lose these again. Move an entry to
its own commit message (or just delete it) once it's actually fixed.

## Account deletion fails client-side ("Failed to fetch")

**Found:** 2026-09-13, while verifying the Pleco export feature (unrelated
to that change — reproduced against the pre-existing account-deletion flow
on a fresh test account).

`api.deleteAccount()` (`frontend/src/lib/api.ts`) sends `DELETE /auth/me`
with a JSON body (`{ password }`). Clicking "Delete my account" on the
Account page fails with a plain `TypeError: Failed to fetch` in the
browser — the request never completes (a manual `fetch(...)` call to the
same endpoint from the console reproduces the same failure). Symptoms
suggest a CORS preflight or fetch-with-body-on-DELETE issue specific to
this request shape, though not yet root-caused.

**Impact:** account deletion is currently unusable from the UI.

**Next step:** reproduce with the Network tab open (not just
`read_console_messages`) to see whether the preflight `OPTIONS` request
itself fails or succeeds and the actual `DELETE` fails after — that
determines whether this is a CORS config gap (`main.py`'s
`CORSMiddleware`) or something about sending a body on `DELETE`
specifically.

## Repeated-sequence context lookup shows more occurrences than the reported count

**Found:** 2026-09-15, while reviewing repeated-sequence results after the
max_token_length/containment fixes.

Tokenizer-sourced words (`source` = `token`/`repeated_sequence`) never get
real per-occurrence `AnalysisResult.positions` — only DAG-sourced words do
(see that column's own docstring, `models.py`). So `GET /analyze/{id}/
context/{word}` falls back to a live, case-insensitive substring search
over the whole body (`get_word_context`, `router.py`), which finds *every*
literal occurrence of the string — including ones tokenizer.py's
containment logic deliberately excluded from the reported `count` (an
occurrence fully nested inside a longer, separately-accepted match, or
inside a dictionary word — see `tokenize()`'s own docstring). A word like
`"e m"` can show `count: 2` in the results table while its context view
lists 4 occurrences: the other 2 are real text, just claimed by something
else during counting.

**Impact:** confusing, but not actually wrong — every occurrence shown in
context is a genuine match in the source text, just filtered differently
than `count`. Not blocking anything; noted for later rather than fixed now
(explicit call to defer, not an oversight).

**Next step:** decide the desired behavior before touching this - options
discussed: make context-lookup containment-aware so it only shows the same
occurrences `count` reflects; keep showing every literal occurrence but
visually distinguish which ones were "claimed" by something else; or just
relabel `count` in the UI (e.g. "distinct occurrences") so the difference
reads as intentional instead of a bug.

## Schema drift: `analysis_results`/`word_visibility` DB state vs. models.py

**Found:** 2026-09-13, via `alembic revision --autogenerate` while adding
the `user_preferences` table for the Pleco export feature. Autogenerate's
diff included two unrelated changes, which were manually stripped out of
that migration (see `backend/migrations/versions/
7412ba91e81d_create_user_preferences_table.py`'s own comment) rather than
silently bundled in:

- `analysis_results.analysis_id` is declared `index=True` in
  `models.py` (`backend/app/modules/known_words/models.py`), but the
  actual DB has no such index (only the compound
  `ix_analysis_results_analysis_word` unique index).
- `word_visibility.created_at`/`.updated_at` are `nullable=False` in
  `models.py`, but the live DB columns are nullable.

**Impact:** none observed yet (Postgres will happily scan without the
missing index at current data volumes; the nullable columns always get a
value via `server_default=func.now()` in practice), but it's a latent trap —
the next unrelated `alembic revision --autogenerate` will pick up both
changes again and can get bundled into whatever migration is being written
at the time if nobody notices.

**Next step:** one small, dedicated migration that adds the missing index
and tightens both columns to `NOT NULL` (after confirming no existing row
actually has a NULL in either column).
