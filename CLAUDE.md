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

## Word categorization: `KnownWord`, `GarbageWord`, and `UserWord.affects_dag`

Working through real test cases (segmenting 三只小猪 / Three Little Pigs)
originally surfaced a need for a category between "known vocabulary" and
"garbage" — a standalone `Fragment` model was built for it, then later
**removed entirely** and folded into a single boolean on `UserWord` (see
below) once it became clear the two concepts didn't need separate tables.

1. **`KnownWord`** — familiarity score (1-5) for real vocabulary the user is
   studying/has studied. Always global, no scoping — familiarity was scoped
   to a specific analysis/text for a while (same mechanism `UserWord` still
   uses), but that was reversed: "how well do I know this word" isn't a
   per-text question the way "should this count toward this text's
   vocabulary, and should it boost segmentation here" (`UserWord`/
   `affects_dag`) is.
2. **`GarbageWord`** — numbers, punctuation, junk. **Not** excluded from
   analysis results before persistence (this was the original design, later
   reversed — see below) — every word from a text's segmentation is always
   persisted, garbage or not, so the analysis stays a faithful
   representation of the full text. `service.filter_results` (called from
   `/analyze`) only *annotates* each `WordResult` with `is_garbage`; hiding
   it is a client-side toggle (`hideGarbage`, default on, "Show garbage (N)"
   checkbox). Marking is fully reversible: the row/card/panel trash icon
   toggles like the Bookmark/Star buttons (filled+red when marked, click to
   unmark). Unmarking (`DELETE /known-words/garbage-words/word/{word}`,
   `unmark_garbage_word` in router.py) deletes the user's own `GarbageWord`
   row if they added one themselves, or - if the word is only garbage
   because of a system-default row (`user_id IS NULL`) - adds an
   `is_override=true` row instead, which `service.get_user_garbage_words`
   subtracts back out. Re-marking a word whose only local row is such an
   override flips it back to `is_override=false` rather than erroring as a
   duplicate (see `create_garbage_word`'s docstring).
3. **`UserWord.affects_dag`** (replaced the standalone `Fragment` model) —
   a **tri-state** (nullable) boolean on every `UserWord` row controlling
   whether that entry's frequency boosts DAG segmentation at all. This is
   what lets a word be "in your dictionary" (worth a pronunciation/meaning/
   notes entry) without necessarily being real vocabulary the segmenter
   should treat as a unit — e.g. 的房子, 猪的, 哥猪和 (segmentation
   artifacts spanning word boundaries) get a `UserWord` row with
   `affects_dag = false`. Originally shipped `NOT NULL DEFAULT true`, which
   was a bug: a row created purely to hold a note had no opinion on
   segmentation weight, but silently got `true` anyway, letting it override
   a broader scope's explicit `false` without the user ever touching that
   setting. Fixed by making the column nullable with no default (no
   backfill — existing true/false rows keep their meaning; nullability only
   changes what new rows default to) — `NULL` means "no opinion at this
   scope, inherit from the next broader scope." `build_user_overlay`
   (`segmenter_loader.py`) resolves this by walking text → global (analysis
   is never resolved here — see below), skipping any row whose
   `affects_dag` is `NULL` as if it weren't there at all (its `freq_combined`
   is skipped right along with it), landing on the first row with an actual
   opinion; only when *nothing* in the walk has an opinion does it fall back
   to a hardcoded `true` default — but with no row left to source a weight
   from at that point, there's nothing to add to the overlay either, so
   that fallback case is functionally identical to the word having no
   `UserWord` entry. When a resolved opinion is `false`, segmentation
   proceeds exactly as if no `UserWord` existed for that word/scope, while
   the row's pronunciation/meaning/notes stay fully intact and visible
   regardless. `affects_dag` can only ever have an observable effect at
   global or text scope: an analysis-scoped row can't influence
   segmentation (its analysis has already finished segmenting by the time
   such a row could exist — `build_user_overlay` never resolves
   analysis-scoped rows at all, for exactly this reason), so the UI hides
   the toggle for analysis-scoped entries in the word-detail panel's
   "Your entries" list (a 3-way radio: Affects segmentation / Excluded from
   segmentation / No preference), though pronunciation/meaning/notes stay
   editable there.

**`UserWord` scopes via its own `scope_analysis_id`/`scope_input_text_id`
columns** and its own scope selector in the word-detail panel
(`userWordScope` in `+page.svelte`). This is what makes the original
motivating case work without a separate `Fragment` table: a dictionary word
that's a genuine word in one text but a segmentation artifact in another is
a single `UserWord` row per scope, with `affects_dag = false` at whatever
scope it's an artifact in.

**`UserWord` also gained rich fields:** `pronunciation` (renamed from an
earlier `pinyin` — see migration note below), `meaning`, `notes`. Adding any
of these via the word-detail panel auto-creates the `UserWord` row via an
upsert endpoint (`PUT /known-words/user-words/{word}`) — no separate "add"
step needed, since filling in a definition already implies "this is a word I
care about."

**`SampleSentence`** — a word can have many example sentences, meant for
capturing real usage (copy the relevant part from a text's context view,
paste it into the word-detail panel's "Sample sentences" section) rather
than writing one from scratch. Its own top-level entity (`GET/POST
/known-words/sample-sentences`, `DELETE /known-words/sample-sentences/{id}`)
— **deliberately not attached to `UserWord`**: an earlier version required a
word to be "in your dictionary" before it could have sample sentences
(sentences hung off the `UserWord` row, auto-creating one on first add),
but that coupling turned out to be wrong once actually used — a sample
sentence is useful for a word regardless of whether it's ever added to the
dictionary, removed from it, etc. `GET /known-words/words/{word}` (word
detail) returns `sample_sentences` as its own top-level list, a sibling of
`user_words` rather than nested under it. Global per user+word, no scoping
(same reasoning as `StarredWord`).

## `WordVisibility`: hiding a word from results, scoped independently of UserWord

A word can be hidden from an analysis's results (e.g. 的, 了, 是 — real,
correctly-segmented words nobody needs surfaced every time) via its own
`hidden: bool` (`NOT NULL`) on a `WordVisibility` row — deliberately a
sibling table to `UserWord`, not a column on it: forcing an empty `UserWord`
row to exist just to carry one boolean would make "has a `UserWord` row"
stop reliably meaning "has customized dictionary info," which the results
table's +Add word/Added button already relies on. Same
`scope_analysis_id`/`scope_input_text_id` shape, mutual-exclusion CHECK, and
`NULLS NOT DISTINCT` unique index as `UserWord` — same analysis > text >
global resolution priority too, reusing router.py's
`_resolve_scope_columns`/`_scope_filter_conditions`/`_resolve_by_scope`
helpers rather than reimplementing them (see `_resolve_word_visibility`).

Unlike `affects_dag`, `hidden` is a plain `NOT NULL` boolean, no tri-state
needed — this table's only reason to exist at a given scope is to express an
opinion on this one field, so a row's mere presence already means
"opinion"; there's no "row exists to hold other data but has no opinion on
this field" case to disambiguate. Absence of a row at a scope IS the "no
opinion, inherit from broader scope" state.

**Unlike `affects_dag`, all three scope levels (including analysis) are
live and meaningful**, and the word-detail panel's Visibility section shows
all three, never hiding the analysis slot the way the "Your entries" list
hides it for `affects_dag`: an analysis-scoped `affects_dag` can never have
an observable effect (its analysis already finished segmenting), but an
analysis-scoped hidden override *does* have a real, observable effect every
time that exact analysis is reopened and re-rendered (`GET
/analyze/{id}`) — segmentation and visibility are resolved at completely
different times relative to when an analysis row can exist.

`WordResult.is_hidden`/`hidden_governing_scope` are resolved fresh on every
read (never persisted — same reasoning as `is_garbage`/familiarity), wired
into both `POST /analyze` and `GET /analyze/{id}`. The results-table quick-
action (eye/eye-slash icon + a small G/T/A corner badge for
`hidden_governing_scope`, omitted when "default") opens a menu built by one
rule-based function (`buildVisibilityMenu`, +page.svelte), not a lookup
table of special cases: the 3 possible "set" actions (Show/Hide at each
scope, whichever is the opposite of the resolved state) are each omitted
if a row already exists at that exact scope with that exact target value
(would be a no-op); independently, a "Remove this text's/analysis's
override" action (never global — there's no broader fallback beyond global
to "remove" back to) is offered at a scope whenever a row exists there,
regardless of whether that scope's own set-action was just omitted as
redundant. Both the row/card quick-action and the panel's own Visibility
section patch `analysis.results` locally after every mutation, so they
stay in sync with each other live, no refetch needed.

**No pre-existing icon-badge system exists for scope anywhere in this
app** — scope elsewhere (`UserWord`) is shown via a text-label `<select>`
(`scopeLabel()`/`ALL_SCOPES`), never icon badges. The small G/T/A corner
badge built for this feature is new, purpose-built, not a reuse of
anything — flagged here since an earlier round's instructions assumed such
a badge system already existed for `UserWord` scope and it doesn't.

`WordResult.is_user_word` (resolved the same way, via
`_resolve_user_word_presence`) is a third field in this same "resolved
fresh on every read" family — existence-based like `is_hidden`, not
tri-state like `affects_dag`: does this word have *any* applicable
`UserWord` row for this viewing context, regardless of that row's own
`affects_dag` opinion. It exists purely to power the results-page "User
words" filter bucket (see below) — the pre-existing `userWords` frontend
Set is a different, narrower thing (global-only, drives the "+ Add word"
quick-action's own filled/outline state) and was left untouched.

## Results-page filtering: one bucket registry, not scattered booleans

The analysis-results page's filters (`+page.svelte`) were unified from a
pile of independent booleans (`hideNonChinese`, `hideSupplemental`,
`hideGarbage`, a starred-only checkbox, `hideHidden`) into a single
**bucket registry** (`BUCKETS`, an array of `{id, label, iconKey, test,
defaultHide}`) rendered as a chip bar. Each bucket's `test: (r: WordResult)
=> boolean` is a plain closure — buckets backed by component state
(Starred via the `starredWords` Set, Non-Chinese via `containsChinese`)
stay reactive with no `$derived` of their own, since closures over `let`
bindings just read the live value when called. Nine buckets, in this
display/review order: Garbage, Hidden, User words, Extra matches,
Unrecognized sequences (`source === 'token'`), Unknown (`source ===
'unknown'`), DAG words (`source === 'dag' || 'trie'`), Starred,
Non-Chinese.

**Each bucket carries two independent booleans, `hide` and `iso`** (not a
single tri-state) — this is what makes "hide my starred words" possible
for the first time; the old starred-only checkbox was isolate-only, with
no hide option at all. One shared predicate (`isVisible`, not per-bucket
special-casing) decides every row: hide always wins first (any
hide-active bucket matching the row excludes it, full stop); *then*, if
any bucket has `iso` on, the row must match **at least one** of them
(union/OR across simultaneously-iso'd buckets — isolating Garbage and
Hidden together shows anything garbage *or* hidden in one pass, not their
intersection; that composition is the actual point of allowing multiple
buckets to be isolated at once). Search box and familiarity threshold stay
their own separate, unchanged predicates, AND-ed on top in
`filteredResults` — not part of the registry.

**Every bucket defaults to `hide: false, iso: false` except Hidden**
(`defaultHide: true`, preserving the pre-existing "hidden words start
hidden until revealed" behavior). This is a deliberate reset, not an
oversight: Garbage and Non-Chinese *used to* default to hidden (their old
standalone booleans defaulted `true`) and no longer do — the whole filter
model starts from a clean, fully-visible slate now except for the one
bucket whose entire reason to exist is noise reduction by default.

Chip counts (`bucketCount`) are always computed against the **full**
`analysis.results`, never `filteredResults` — the point is that "Garbage
(8)" stays legible regardless of what other filters are currently active,
so the user always knows how many are waiting for review. Each chip shows
its state at a glance without opening its popover: `iso`-active uses a
filled/highlighted treatment (blue, matching this app's general
"selected/active" language elsewhere — selected familiarity-score buttons,
the selected-row highlight — deliberately *not* the star icon's amber,
which is that icon's own identity color rather than a reusable
state-styling pattern); `hide`-active uses a strikethrough label plus a
small dot, both visible without opening the popover. Clicking a chip opens
a small popover with two independent Hide/Isolate checkboxes; changes
apply live, same as the old checkboxes did.

**Column sorting** (`sortColumn`/`sortDirection`, session-only - not
persisted like the filters above): a tri-state toggle per column (Word/
Count/Source/Familiarity) - first click ascending, second descending,
third clears back to the server's natural count-descending order. The
desktop table's clickable `<th>` headers (`sortHeader` snippet, reusing
`iconChevron` rotated as the ascending/descending indicator rather than a
new arrow glyph) and a "Sort by" `<select>` in the filter bar both drive
the same state, so they stay in sync - the dropdown exists because the
mobile card list has no headers to click. Word sorts by **plain codepoint
comparison**, deliberately not `localeCompare` with a `'zh'` locale - ICU's
Chinese collation sorts by pinyin, which is exactly what was ruled out:
pinyin support is an intentionally separate, not-yet-designed piece of
this app (see the Traditional Chinese section above for the closest
existing "deferred, needs its own design pass" precedent) - a real,
stable, non-phonetic ordering was chosen instead of blocking on that.
Source sorts by the *displayed* label (`sourceLabel`), not the raw
`source` key, so `dag` and legacy `trie` (both shown as "segmenter") sort
adjacently; Familiarity treats unset (`null`) as lower than any scored
value 1-5.

## Rarity tier: a persisted read-cache derived from corpus frequency

`DictionaryWord.freq_per_million`/`.rarity_tier` are derived, persisted
columns (both NULL whenever `frequency` is), not computed live — populated
by `backend/scripts/compute_word_rarity.py`, run after
`import_frequencies.py`/whenever frequency data changes. `rarity_tier` is
one of 5 fixed values (`extremely_rare`/`rare`/`uncommon`/`common`/
`extremely_common`), enforced via a CHECK constraint (this schema's
existing pattern for a small fixed string set — see
`ck_analysis_results_source` — rather than a native Postgres enum type).

**Cutoffs are finalized, not something to recompute per environment**:
`backend/scripts/analyze_word_rarity.py` (read-only, run once) found them
by log10-transforming occurrences-per-million (raw/equal-width bucketing
both fail here — word frequency follows Zipf's law, a handful of words
account for a huge share of occurrences — log-space is what makes
equal-width buckets actually mean "roughly an order of magnitude more/less
common than its neighbor"), then cross-checked the candidate cutoffs
against HSK levels (lower HSK levels should skew toward the common end -
they did). `compute_word_rarity.py` itself does no log-space work at
all — the log transform was only ever needed to *find* sensible cutoffs;
final tier assignment is a plain occurrences-per-million range check
(`extremely_rare` < 0.03, `rare` 0.03-1, `uncommon` 1-50, `common`
50-2250, `extremely_common` >= 2250).

**`compute_word_rarity.py` is 2 bulk `UPDATE`s, not a Python row loop** —
a deliberate deviation from "batch commits" read literally: the same
"single bulk UPDATE across the whole table" shape `import_frequencies.py`'s
`calc_combined`/`frequency` steps already use, not a new pattern. At ~1.6M
rows this is fewer round trips than any per-row/chunked approach, and
still satisfies re-runnability — both columns are reset to NULL first for
rows that no longer qualify (`frequency` NULL or 0), so a re-run after
frequency data changes doesn't leave stale tiers behind. No
insert/conflict handling needed either way, since every row already
exists (`dictionary_words` is populated by `build_dictionary.py`/
`import_frequencies.py` beforehand) — this only ever `UPDATE`s.

**Frontend**: the word-detail panel's rarity badge sits directly next to
the existing "Corpus frequency" number (`analyze/[id]/+page.svelte`),
using the same small-pill visual language as the HSK badges in that same
section — but its own gray-to-warm color scale (`rarityColor`), distinct
from HSK's blue/purple/green, so the two badge families read as separate
things at a glance. The raw `freq_per_million` number lives in the
badge's `title` tooltip rather than inline, to avoid a second number
competing with the frequency count right next to it. Omitted entirely
(not an empty/placeholder badge) whenever `rarity_tier` is null — same
"omit if absent" pattern the optional HSK badges in that section already
use.

## Word-detail panel: early steps toward a Pleco-style multi-source view

Long-term goal (explicitly deferred, not built): instead of merging all data
sources into one uniform schema, display each source's info under its own
heading, in whatever shape that source provides it — closer to how Pleco
handles multiple dictionaries. Currently only two real sources exist (HSK
entries/forms, corpus frequency) plus the new user-entered data, so the
generalized multi-source data model isn't worth building yet — better to
design it once a second/third *real* data source's actual shape is known
rather than guess. In the meantime, the current `WordDetail` response has
`user_words` (a list — every scope-relevant entry, most-specific first, see
below) as a separate field (not merged into the flat HSK/frequency fields),
and the frontend panel labels these as visually distinct sections
("Dictionary" / "Your entries") — a cheap step that doesn't require the full
abstraction but leaves a visual seam to extend later.

**`WordDetail.user_words` is a list, not a single resolved entry** — a word
can have several simultaneous `UserWord` rows (e.g. a global one plus a
one-off override for a specific text), and none is ever hidden just because
a more-specific one exists; the panel's "Your entries" section shows each
independently, editable/deletable on its own. This is purely a display
concern — segmentation resolution stays entirely in
`build_user_overlay`/`segmenter_loader.py`, which picks exactly one row's
weight (and skips it if `affects_dag` is false) per its own unrelated
scope-priority logic.

## Profile pages: standalone management screens for the "global" lists

Before this, `KnownWord`/`UserWord`/`GarbageWord`/`Stopword`/`StarredWord`
were only ever visible/editable through the lens of one analysis's results
page - there was no way to see "all my known words" or "all my user words
across every text" in one place. `frontend/src/routes/profile/` adds one
tab per list (`+layout.svelte` renders the shared nav/tab bar; `+page.svelte`
is a landing page of count-cards linking into each tab), each a fully
independent page (own fetch, own search box, own add-form) rather than one
mega-component - this matches the rest of the app's existing "one page owns
its own state" convention (no shared page-level components existed before
this either).

**`UserWord` needed a genuinely new backend capability, the other four
didn't.** `KnownWord`/`GarbageWord`/`Stopword`/`StarredWord` have no
per-text/per-analysis scoping, so their existing `GET` list endpoints were
already complete "show me everything" views with zero backend changes
needed. `UserWord` does have scoping, and `GET /user-words` always resolved
to one row per word (analysis > text > global winner) — exactly right for
segmentation/the results page, exactly wrong for "show me every entry I've
ever made, wherever it's scoped." Added `all_scopes: bool = False` to that
endpoint (`list_user_words`, router.py): when true, resolution is bypassed
entirely and every row for the user comes back unresolved, each annotated
with `input_text_title` (via `_resolve_input_text_titles` — a 2-query bulk
join, not per-row) so the page can label/link a scoped row without a
second round trip per row. `api.ts` exposes this as `listAllUserWords()`,
kept a separate function from `listUserWords(analysisId, inputTextId)`
rather than overloading it, since the two return shapes mean genuinely
different things (one resolved answer per word vs. every row) and mixing
them behind one signature invited a caller using the wrong mode by
accident.

**The User Words page's "+ Add" only ever creates a global entry** - unlike
every other list here, a brand-new `UserWord` row from this page has no
"current text/analysis" to scope to (that's still only available from
inside a specific analysis's word-detail panel, which is unchanged). Its
per-row edit form reuses the exact tri-state `affects_dag` radio-group
markup from that same panel (`entry.scope_analysis_id == null` gate, three
`<input type="radio">`s, not a checkbox) rather than a boolean checkbox -
a plain checkbox literally cannot represent `NULL` ("no preference,
inherit from a broader scope") as distinct from `false` ("explicitly
excluded"), and would silently coerce an untouched `NULL` to `false` on
every save. This was caught live while building this page (the exact same
bug pattern the nullability fix earlier in this doc was about, recurring
in a second location) - fixed there and cross-checked that the original
results-page panel never had it in the first place.

**Garbage Words and Stopwords show raw, unresolved rows** (system defaults
mixed with the user's own additions/overrides), not a single merged view -
`service.get_user_garbage_words`'s exact `garbage - overrides` math is
re-implemented client-side (same as the results page's own `garbageWords`
Set already does) to produce a "your effective garbage words" section plus
a secondary "excluded from garbage" section for override rows, but
Stopwords' code-level defaults (`DEFAULT_LM_STOPWORDS`/
`DEFAULT_TOKENIZER_STOPWORDS`, service.py) have no API surfacing them at
all — `GET /stopwords` only ever returned DB rows — so they're absent from
that page entirely; flagged here since it's an intentional scoping choice
(nothing there would be editable/deletable anyway), not a gap to fix later
without a reason to.

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
  floated but deliberately not built — a separate need from
  `UserWord.affects_dag`, not yet necessary.
- Traditional Chinese support (see above) — not started.
- The generalized multi-source `WordDetail` data model (Pleco-style) — not
  started, deferred until a second/third real data source is in hand.
- Deployment: planned single Hetzner VPS, FastAPI + SvelteKit behind Caddy,
  self-hosted Postgres — not yet started.