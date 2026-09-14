# Roadmap / future work

Not-yet-built ideas and deliberately-deferred work, consolidated in one
place instead of scattered across `CLAUDE.md` and individual planning
conversations. Nothing here is scheduled — it's a backlog, not a
commitment. See [BUGS.md](BUGS.md) for known-broken behavior instead of
not-yet-built behavior.

## Export

- **Additional export formats.** The Pleco flashcard export
  (`frontend/src/lib/pleco.ts`, `GET /known-words/analyze/{id}/export-data`)
  was built as the first of what should be several export targets (e.g. a
  plain CSV/Anki-compatible export). The backend endpoint already returns
  format-agnostic per-word data for exactly this reason — a new target is
  a new frontend formatter module, not a new endpoint.
- **Per-export override of the account-level settings.** Today the Export
  dialog (`ExportDialog.svelte`) only offers "respect the current filter or
  not" — every other setting (pinyin, definition sources, user-word scopes)
  is account-level only, edited on the Account page. A one-off override
  without leaving the dialog was deliberately deferred, not ruled out.
- **Include `UserWord.notes` in the export**, not just `.meaning` — the
  export's "Your definitions" source currently only reads `meaning`, since
  `notes` reads more like a private working note than a definition. Worth
  revisiting if that assumption turns out wrong in practice.

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
