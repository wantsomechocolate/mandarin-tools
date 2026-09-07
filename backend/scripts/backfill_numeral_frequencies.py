"""
Backfills WordFrequencyOverride rows for a specific, bounded set of words
that are real HSK/CEDICT vocabulary but have NULL frequency in every raw
corpus source file (backend/assets/frequencies/*.txt) - not a rounding
artifact, a genuine gap in the source data itself (confirmed by grepping
the raw corpus files directly - these words never appear there as
standalone tokens, only ever fused into larger tokens like 一个/十分/二十几).

## How this surfaced

Segmenting "森林是一个中文词语" (a plain sentence containing 一) produced
森/林是一/个/中文/词语 instead of the correct 森林/是/一/个/中文/词语. Root
cause: Segmenter._word_weight (dag_segmentor.py) scores a trie hit with no
frequency as the catastrophic "unknown floor" (-log(total)), same as a
genuinely unrecognized character sequence. Since 一's frequency is NULL,
segmenting the correct path pays that floor penalty for 一 no matter what -
and because the DP optimizes the *whole path*, not word-by-word, it will
happily sacrifice a locally-obvious word (森林) elsewhere in the sentence to
avoid paying it, if some other real-but-rare dictionary word (here 林是一)
lets it dodge the penalty by absorbing the orphan character. A per-word
UserWord boost of 森林 cannot fix this - 森林 isn't the word with the actual
problem. See conversation/CLAUDE.md history for the full diagnostic trail;
not repeated here.

## Scoping this fix: two tiers

**SINGLE_CHARS (18 words)** - restricting the 42,935 CEDICT-backed
dictionary_words rows with NULL frequency down to HSK-backed ones (i.e.
words explicitly curated as essential, not just "in a dictionary
somewhere") narrows it to 327 words; restricting further to single
characters - the only length capable of the exact "orphan character forced
into a bad neighbor" bug shape, since a single character is a DAG
candidate at *every* position it appears, competing against every longer
alternative - gives:

    一 七 三 九 二 五 八 六 十 四 多 点 百 零 万 亿 千 余

(多 "more/many" and 点 "o'clock/dot/a bit" aren't numerals but hit the
exact same gap and bug shape - 很多/更多/差不多, 有点/重点/几点 etc. are all
extremely common yet 多/点 alone have NULL frequency, same as the numerals.)

The other ~309 HSK words in that 327 are multi-character (下载, 与否, 两侧,
主页, ...) and NOT structurally forced into scope by this fix (unlike
STRUCTURAL_COMPOUNDS below) - left out of this first pass as originally
scoped. If that turns out to matter later,
`WHERE frequency IS NULL AND (hsk_v2_2012 IS NOT NULL OR hsk_v3_2021 IS NOT NULL
OR hsk_v3_2026 IS NOT NULL) AND char_length(word) > 1` on dictionary_words
reproduces that list - the SINGLE_CHARS methodology below (a word's
standalone frequency estimated from its best-attested real compounds)
generalizes to those the same way.

**STRUCTURAL_COMPOUNDS (21 words)** - NOT part of the original scoping,
added after live regression testing caught real breakage: boosting the 18
single characters made several *other* real, CEDICT-backed dictionary_words
entries lose to being split into those now-boosted characters, because
those entries are themselves ALSO NULL-frequency:

    二十 三十 四十 五十 六十 七十 八十 九十 十万 百万 千万 万一
    十一 十二 十三 十四 十五 十六 十七 十八 十九

(the last 9 - the teens - are the same exposure as the tens family above,
just N+十 vs 十+N; caught in a second round of regression testing after the
first round only tried "他今年十八岁了" for the tens and missed 十八 itself.)

Example: 万一 ("just in case") is a real HSK4/CEDICT word, NULL frequency.
Before this script ran, both 万 and 一 were *also* NULL, so splitting it
into 万+一 was roughly a wash. After SINGLE_CHARS gives 万 and 一 real
frequencies, keeping 万一 whole started losing decisively to the split -
this script fixing the character-level gap was *actively making this word
worse* unless it's fixed in the same pass. These 12 are exactly the set of
real dictionary_words entries that are directly composed of two
SINGLE_CHARS words end-to-end (verified via dictionary_words lookups, not
assumed) - not a general "let's also grab some 2-char words" expansion.
一百/一千/一万/一亿 are NOT in this list because they aren't in
dictionary_words at all (no entry to protect) - they'll correctly compose
from 一 + 百/千/万/亿 on their own once those have real frequencies.

## Methodology for the actual numbers

SINGLE_CHARS: each word's standalone frequency is estimated as the
frequency of its single highest-frequency real containing compound (e.g.
一's is 一些's 11,583,138) - a conservative anchor, not a precise
measurement. This was checked against the DP math needed to actually fix
the reproduction sentence: with 林是一 at its real frequency (397) and the
rest of the sentence's scores computed by hand, 一 needed roughly >55,000
to flip the sentence to the correct segmentation - every one of these top-1
values clears that by at least two orders of magnitude, so there was no
reason to reach for a larger, more collision-prone estimate (an earlier
draft of this script used 3x the sum of the top 5 containing words, which
over-estimated badly enough to cause the STRUCTURAL_COMPOUNDS regression
below at higher severity - reverted in favor of this more conservative
version once that surfaced in testing).

STRUCTURAL_COMPOUNDS: since these words are being newly exposed to a
character-level split risk *by* the SINGLE_CHARS values above, their
estimate is defined directly against that risk rather than against their
own (sparse, similarly under-counted) containing compounds:

    max(3 * freq(char1) * freq(char2) / total_corpus_frequency,
        top-1 real containing compound's frequency)

The first term is a 3x safety margin over the exact break-even point
against splitting into its two SINGLE_CHARS components (below that
multiple, it would lose the DP comparison to the split); the max() with
the compound's own best-attested real data keeps this from ever *under*-
shooting where the corpus does have decent signal (matters most for
十万/百万/千万, whose own attested compounds like 几百万/数千万 already
clear the split-margin threshold on their own).

These are estimates, not measurements - if a better source of real word
frequency data ever turns up, prefer it and update the rows here (or
dictionary_words directly, if the new source is a proper corpus re-import)
rather than re-deriving from this same formula again.

## What this script does

1. Computes SINGLE_CHARS frequencies first (order matters - STRUCTURAL_COMPOUNDS's
   formula depends on them), upserts WordFrequencyOverride rows for both
   tiers (word, frequency, reason - the reason records the exact inputs and
   formula used, so a future reader doesn't have to re-run this script just
   to see where a number came from).
2. Syncs those same values into dictionary_words.frequency for these 30
   words only - WordFrequencyOverride is the source of truth (see its
   docstring, models.py, for why this is a separate table rather than a
   direct dictionary_words hand-edit), but dictionary_words.frequency is
   what the word-detail panel's "Corpus frequency" display and rarity_tier
   badge read, so it's kept in sync rather than continuing to show blank
   for a word this table now has an answer for.
3. Re-runs compute_word_rarity.py so freq_per_million/rarity_tier reflect
   the new frequencies (that script is itself idempotent/safe to re-run -
   see its own docstring).

Re-running this script is safe/idempotent - step 1 is an upsert on the
unique `word` column, step 2 is a plain UPDATE.

segmenter_loader.invalidate_segmenter_cache() is NOT called here - this
script talks to the DB directly, not through a running app process. Restart
the backend (or otherwise trigger a fresh get_segmenter() build) after
running this for the new overrides to actually take effect in segmentation.

Regression coverage: verified live against a hand-written batch of
numeral-heavy sentences (the reproduction case, plus 十分/十一月/三十而立/
十全十美/一举两得/差不多/万一/二十几/几百万-style sentences) via
get_segmenter().segment() before/after - not (yet) captured as an automated
pytest case; worth adding to tests/known_words/ if this class of fix
recurs.

Usage:
    uv run python scripts/backfill_numeral_frequencies.py
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal

SINGLE_CHARS = ["一", "七", "三", "九", "二", "五", "八", "六", "十", "四", "多", "点", "百", "零", "万", "亿", "千", "余"]

# Each entry: (word, (char1, char2)) - the two SINGLE_CHARS words it's
# directly composed of, verified against dictionary_words (see this
# script's docstring's STRUCTURAL_COMPOUNDS section).
STRUCTURAL_COMPOUNDS = [
    ("二十", ("二", "十")), ("三十", ("三", "十")), ("四十", ("四", "十")),
    ("五十", ("五", "十")), ("六十", ("六", "十")), ("七十", ("七", "十")),
    ("八十", ("八", "十")), ("九十", ("九", "十")),
    ("十万", ("十", "万")), ("百万", ("百", "万")), ("千万", ("千", "万")),
    ("万一", ("万", "一")),
    # The teens (十一-十九) are the same structural exposure as X十 above,
    # just the other component order (十+N instead of N+十) - caught in a
    # second regression-test round (他今年十八岁了 split 十八 into 十/八)
    # after the first round of testing only checked the tens family.
    ("十一", ("十", "一")), ("十二", ("十", "二")), ("十三", ("十", "三")),
    ("十四", ("十", "四")), ("十五", ("十", "五")), ("十六", ("十", "六")),
    ("十七", ("十", "七")), ("十八", ("十", "八")), ("十九", ("十", "九")),
]

STRUCTURAL_MARGIN = 3


def top1_containing_frequency(db, word: str) -> tuple[int, str]:
    """Returns (frequency, description) of `word`'s single highest-frequency
    real containing dictionary word, e.g. 一 -> (11583138, "一些")."""
    row = db.execute(text("""
        SELECT word, frequency
        FROM dictionary_words
        WHERE word LIKE :pat AND word != :word AND frequency IS NOT NULL
        ORDER BY frequency DESC
        LIMIT 1
    """), {"pat": f"%{word}%", "word": word}).fetchone()
    if row is None:
        raise ValueError(f"No frequency-bearing dictionary words contain {word!r} - can't estimate.")
    return row[1], row[0]


def main():
    db = SessionLocal()
    try:
        total = db.execute(text(
            "SELECT SUM(frequency) FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
        )).scalar()

        estimates: dict[str, tuple[int, str]] = {}

        # Tier 1: single characters, top-1-containing-compound estimate.
        for word in SINGLE_CHARS:
            freq, source_word = top1_containing_frequency(db, word)
            reason = (
                f"Estimated as the frequency of its single highest-frequency real "
                f"containing dictionary word, {source_word}={freq:,}. Word itself has "
                f"NULL frequency in every raw corpus source file - not a bug in this "
                f"app's import pipeline, the gap is in the source data. See "
                f"scripts/backfill_numeral_frequencies.py's docstring (SINGLE_CHARS) "
                f"for the full methodology and why this needed to be conservative."
            )
            estimates[word] = (freq, reason)

        # Tier 2: structural compounds - depends on tier 1's values, so
        # computed second. See docstring's STRUCTURAL_COMPOUNDS section for
        # why these are in scope and how the formula is derived.
        for word, (c1, c2) in STRUCTURAL_COMPOUNDS:
            f1, _ = estimates[c1]
            f2, _ = estimates[c2]
            split_margin_value = round(STRUCTURAL_MARGIN * f1 * f2 / total)
            try:
                top1_freq, top1_word = top1_containing_frequency(db, word)
            except ValueError:
                top1_freq, top1_word = 0, None

            if split_margin_value >= top1_freq:
                freq = split_margin_value
                reason = (
                    f"Estimated as {STRUCTURAL_MARGIN}x the DAG break-even point against "
                    f"being split into its own components {c1}+{c2} "
                    f"({STRUCTURAL_MARGIN} * {f1:,} * {f2:,} / {total:,} = {split_margin_value:,}). "
                    f"This word is real (CEDICT/HSK-backed) but has NULL frequency itself; "
                    f"once {c1} and {c2} were given real frequencies (see their own "
                    f"word_frequency_overrides rows), this word started losing to being "
                    f"split into those two characters unless given a comparable value of "
                    f"its own. See scripts/backfill_numeral_frequencies.py's docstring "
                    f"(STRUCTURAL_COMPOUNDS) for why this word is in scope."
                )
            else:
                freq = top1_freq
                reason = (
                    f"Estimated as the frequency of its single highest-frequency real "
                    f"containing dictionary word, {top1_word}={top1_freq:,} - higher than "
                    f"the {STRUCTURAL_MARGIN}x split-safety-margin against {c1}+{c2} "
                    f"({split_margin_value:,}), so used directly. See "
                    f"scripts/backfill_numeral_frequencies.py's docstring "
                    f"(STRUCTURAL_COMPOUNDS) for why this word is in scope."
                )
            estimates[word] = (freq, reason)

        print("Estimated frequencies:")
        for word, (freq, _) in sorted(estimates.items(), key=lambda kv: -kv[1][0]):
            print(f"  {word}\t{freq:,}")
        print()

        # Step 1: upsert WordFrequencyOverride rows.
        for word, (freq, reason) in estimates.items():
            db.execute(text("""
                INSERT INTO word_frequency_overrides (word, frequency, reason)
                VALUES (:word, :freq, :reason)
                ON CONFLICT (word) DO UPDATE
                SET frequency = EXCLUDED.frequency, reason = EXCLUDED.reason
            """), {"word": word, "freq": freq, "reason": reason})
        print(f"Upserted {len(estimates)} word_frequency_overrides rows.")

        # Step 2: sync into dictionary_words.frequency for just these words,
        # so the UI (rarity badge / corpus frequency display) stays
        # consistent with what the segmenter now uses. See this script's
        # docstring for why dictionary_words.frequency is treated as a
        # derived cache of word_frequency_overrides for these specific words.
        for word, (freq, _) in estimates.items():
            db.execute(text(
                "UPDATE dictionary_words SET frequency = :freq WHERE word = :word"
            ), {"word": word, "freq": freq})
        print(f"Synced {len(estimates)} dictionary_words.frequency values.")

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Step 3: re-derive freq_per_million/rarity_tier for the whole table
    # (cheap, idempotent - see compute_word_rarity.py's own docstring).
    print("\nRe-running compute_word_rarity.py...")
    subprocess.run(
        [sys.executable, str(Path(__file__).parent / "compute_word_rarity.py")],
        check=True,
    )


if __name__ == "__main__":
    main()
