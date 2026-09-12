# Text difficulty score — research notes & v2 roadmap

This document captures the research and design reasoning behind the
per-analysis "text difficulty" score (v1 shipped in
`backend/app/modules/known_words/difficulty.py`), and lays out what was
deliberately deferred so it doesn't get lost or silently re-litigated later.
See `difficulty.py`'s own module docstring for the v1 model itself; this
doc is the "why," including the pieces v1 doesn't implement yet.

## v1 recap

A token-weighted average of each word's "effective weight" — the greater
of its own `KnownWord.familiarity` and, for multi-character words, a
discounted estimate from its component characters' own familiarity (the
希奇/希望/奇怪 case: an unknown compound built from two known characters
is a smaller readability hit than one built from unfamiliar characters).
Mapped onto five bands (`very_easy` … `very_difficult`). Computed fresh on
every read from current `KnownWord` state, never persisted — same
convention as `WordResult.familiarity`/`is_garbage`/`evidence_tier`.

Only counts words with at least one CJK character, and excludes
`is_garbage` rows entirely (both revised after initial usage — see
`difficulty.compute_difficulty`'s docstring: a text mixing in English
words was tanking the score on words that were never Mandarin vocabulary
to begin with, and dominating "weighing your score down most" with single
English letters instead of real unknown Chinese words).

## 1. Lexical coverage research (the anchors behind the band cutoffs)

The "98%/95%" thresholds referenced throughout this feature come from L2
English reading research:

- **Hu & Nation (2000)**: ~98% coverage let most readers get adequate
  comprehension of a text unassisted; ~95% was roughly the floor below
  which comprehension started collapsing.
- **Laufer & Ravenhorst-Kalovski (2010)**: refined this into "minimal"
  comprehension at ~95% coverage and "optimal" comprehension at ~98%
  (roughly 4-5k word families vs. 6-8k, in English vocabulary-size terms —
  not transferable to Chinese directly).
- **Caveat (Schmitt/Jiang/Grabe; Kremmel's 2023 replication of Hu &
  Nation)**: coverage-to-comprehension looks more like a continuous curve
  that steepens around 95-98%, not a hard step function. Treat the band
  cutoffs as directionally right, not precise.
- **Chinese-specific**: no well-established Chinese replication of these
  exact thresholds was found. One study found Chinese L2 textbook series
  reaching only ~81% cumulative coverage by their final volume — well
  short of even the 95% floor — suggesting Chinese vocabulary progressions
  may not behave the same way English graded readers do. `difficulty.py`'s
  `DIFFICULTY_BANDS` (99%/98%/95%/90%) are English-L2 numbers borrowed as a
  starting point, explicitly not validated for Mandarin.

Sources: Laufer & Ravenhorst-Kalovski (2010), *Lexical threshold revisited*
(https://files.eric.ed.gov/fulltext/EJ887873.pdf); Kremmel (2023),
*Unknown Vocabulary Density and Reading Comprehension: Replicating Hu and
Nation (2000)*, Language Learning
(https://onlinelibrary.wiley.com/doi/10.1111/lang.12622); Cumulative
coverage of Chinese L2 textbooks
(https://www.tandfonline.com/doi/full/10.1080/07908318.2025.2528779).

## 2. Deferred: corpus-frequency severity weighting

`DictionaryWord.freq_per_million`/`rarity_tier` (`models.py:160-202`) are
already computed and available, but v1 does not use them. Two distinct
ideas were considered and both pushed to v2:

- **A prior for never-marked common words.** A word with no `KnownWord`
  row at all currently scores as fully unknown (weight 0), which is likely
  wrong for extremely-common function words (的/是/了) a user almost
  certainly knows but never got around to marking. A frequency-based prior
  could soften this — but risks papering over genuinely-unmarked
  vocabulary rather than encouraging users to actually mark it, so it
  needs product judgment, not just an algorithm change.
- **Severity discount for unknown rare words.** An unknown *rare* word
  encountered once is arguably less of a real-world reading obstacle than
  an unknown *common* one, since it's less likely to recur. Flagged as a
  secondary tuning knob — worth revisiting only if it demonstrably
  improves on the character-decomposition signal alone, not built
  speculatively.

## 3. Deferred: phonetic/semantic radical inference

The idea: if the pronunciation or meaning of an unknown character can be
partially inferred from characters the user already knows — even without
recognizing the specific word — that should reduce (not eliminate) the
readability hit, more so for advanced readers who've learned to actually
use these cues.

- **Phonetic series** — characters sharing a phonetic component often
  share (or nearly share) a reading: 提/题/踢/剔/惕/锑/涕 all relate to
  "tī"-ish pronunciations via a shared phonetic component. Not every
  phonetic component is reliable in modern Mandarin (some are historical
  accidents), so this needs a *reliability-scored* phonetic-series table,
  not a naive "shares a component → same sound" rule.
- **Semantic radicals** — 裤/袜/裙 all carry 衣 (clothing) and are all
  clothing-related; a semantic-radical → meaning-category table could let
  an unknown word's *rough* meaning be guessable from a known radical even
  when the specific word isn't known.
- **Why this is deferred, not just harder**: no such data exists anywhere
  in this schema today (confirmed during implementation exploration) —
  this is a genuine data-acquisition problem, not an algorithm problem,
  exactly parallel to how Traditional Chinese support was deferred in this
  codebase for the same reason (see `CLAUDE.md`'s Traditional Chinese
  section). It deserves the same treatment: design the model once the
  data's actual shape is known, rather than guessing at a schema now.
- **Should scale with proficiency.** Native speakers and advanced learners
  use radical cues constantly; a beginner often can't yet, because radical
  awareness is itself a skill that develops with proficiency. Any future
  implementation should apply this bonus more generously as a function of
  overall reading level (however that ends up being measured — plausibly
  this very difficulty score, once trustworthy), not as a flat bonus for
  everyone.

## 4. Deferred: calibration feedback loop

The 95%/98%-style thresholds (and the `FAMILIARITY_WEIGHTS`/
`CHAR_DECOMPOSITION_DISCOUNT`/`DIFFICULTY_BANDS` constants in
`difficulty.py` generally) are placeholders borrowed from English-L2
research and internal judgment calls, not validated against how this
app's actual users experience actual texts. A lightweight feedback capture
— e.g. "how did this feel? too easy / just right / too hard" — logged
against the computed score for that analysis, was considered for v1 and
explicitly deferred to ship the core model first.

This is the natural fast-follow once the v1 score has real usage behind
it: with enough (score, user-reported-difficulty) pairs, the band cutoffs
and weight constants can be empirically retuned instead of staying fixed
at their English-literature-derived starting points — which is likely to
matter more for Mandarin specifically, given the coverage-threshold
literature's Chinese-specific gap noted in §1.
