# Roadmap / future work

Not-yet-built ideas and deliberately-deferred work, consolidated in one
place instead of scattered across `CLAUDE.md` and individual planning
conversations. Nothing here is scheduled — it's a backlog, not a
commitment. See [BUGS.md](BUGS.md) for known-broken behavior instead of
not-yet-built behavior.

## Export

- ~~**Additional export formats.**~~ Done (2026-09-14): `.xlsx` shipped
  alongside Pleco, one sheet per non-empty bucket (Main/Extra/Sequences),
  one column per enabled data source rather than Pleco's single joined
  field — see `frontend/src/lib/xlsxExport.ts`. Confirmed the original
  prediction below: it's purely a new frontend formatter
  (`buildXlsxBlob`) plus a format toggle in `ExportDialog.svelte`, no
  backend changes at all — `GET /known-words/analyze/{id}/export-data`
  and the shared per-word types/helpers (pulled out into
  `frontend/src/lib/exportData.ts` once pleco.ts had a second consumer)
  were already format-agnostic. Still open: a plain CSV or
  Anki-compatible export, if wanted later — same pattern, another new
  formatter module.
- **Per-export override of the account-level settings.** Today the Export
  dialog (`ExportDialog.svelte`) only offers "respect the current filter or
  not" — every other setting (pinyin, definition sources, user-word scopes)
  is account-level only, edited on the Account page. A one-off override
  without leaving the dialog was deliberately deferred, not ruled out.
- ~~**Include `UserWord.notes` in the export**~~ Done (2026-09-14): the
  export's "User" source is now unbounded and template-matched (every
  UserWord entry, across every text/analysis) and includes `notes`
  alongside pronunciation/meaning for both formats.
- **Split the export options by format (Pleco vs. everything else).**
  The 2026-09-14 rework made both formats share one settings/content model
  literally by design — every source (HSK/CC-CEDICT/User/Auto-Generated/
  Sample Sentences/Context/etc.) now renders the *same* underlying content
  in Pleco's single joined definition field as it does in .xlsx's own
  columns, per the user's explicit call to accept that for now rather than
  invent a reduced Pleco-specific set ahead of seeing it in practice. Revisit
  once a real Pleco card built this way has actually been opened in Pleco -
  if it reads as too much, this is the point where Pleco's own preference
  set (or definition-field content) would diverge from .xlsx's.

## Preferences

- **Migrate the remaining localStorage preferences to the backend.** The
  Pleco export feature introduced the first backend-persisted preference
  (`UserPreference`, `app.modules.preferences`) specifically to replace
  this app's earlier "preferences are always localStorage" convention.
  Theme (`theme.svelte.ts`), word-detail-panel section defaults
  (`sectionVisibilityPersistence.ts`), and context length
  (`contextPreferences.ts`) are still localStorage-only and should move
  onto the same mechanism (key-per-preference, e.g. `"theme"`,
  `"sectionDefaults"`, `"contextChars"`) as a focused follow-up.
- Once preferences are backend-persisted, the analysis-results page's own
  filter-bucket state (`analyze/[id]/+page.svelte`'s
  `mandarin_tools_analysis_filters` localStorage key) is a plausible
  further candidate, though it's per-browser working state more than an
  "account setting" — worth a deliberate decision, not an assumed yes.

## Segmentation / dictionary

- **Promote a `longest_match_only`/`extra_match` word directly into
  `UserWord` from the results table.** Currently requires viewing the word
  then using the separate "+ Add word" action — a one-click promotion
  would remove that extra step.
- **`GarbageWord` categorization** (numbers / punctuation / misc subtypes)
  — floated during the `UserWord.affects_dag` work, deliberately not
  built; a separate concern from `affects_dag`, not yet needed.
- **Traditional Chinese support** — established as a data problem, not an
  algorithm problem (the DAG+DP segmenter is script-agnostic); needs a
  second trie built from traditional-Chinese frequency data (OpenCC
  conversion of the existing simplified dictionary, or a native
  traditional corpus). Open product question alongside it: should a
  simplified/traditional word pair share one familiarity score, or be
  tracked independently?
- **Pinyin-based sorting/collation.** The results table's Word column
  deliberately sorts by plain codepoint, not `localeCompare('zh')`, because
  ICU's Chinese collation sorts by pinyin and that's real, separate design
  work (tone handling, multi-reading characters) rather than a one-line
  swap.
- **Generalized multi-source `WordDetail` data model** (Pleco-style: show
  each data source under its own heading, in its own shape, rather than
  merging everything into one uniform schema). Deferred until a second/
  third real data source (beyond HSK/CC-CEDICT) is actually in hand — not
  worth designing against a guess.

## Deployment

- Single Hetzner VPS: FastAPI + SvelteKit behind Caddy, self-hosted
  Postgres. Not started.

## Housekeeping

- See [BUGS.md](BUGS.md)'s schema-drift entry — a small dedicated
  migration to add the missing `analysis_results.analysis_id` index and
  tighten `word_visibility.created_at`/`.updated_at` to `NOT NULL`.
- **xlsx library choice** (`frontend/src/lib/xlsxExport.ts`): moved from
  `write-excel-file` to `exceljs` (2026-09-14) once the Context column
  needed a real rich-text run to bold the matched word - `write-excel-file`
  has no rich-text API at all. `exceljs` carries one moderate advisory
  itself, transitively through `uuid`'s v3/v5/v6-explicit-buffer bug - a
  narrow misuse pattern this module's write-only, no-untrusted-input,
  browser-only usage doesn't exercise, so it was accepted rather than
  chased. Worth a fresh look if that advisory's status changes, or if a
  lighter write-only library ever adds real rich-text support.
