"""
Backfills WordFrequencyOverride rows for HSK/CEDICT words that are real
dictionary entries but have NULL frequency in every raw corpus source file -
the same underlying corpus gap as scripts/backfill_numeral_frequencies.py,
but for a much larger, unbounded population (CEDICT alone has ~42,900 NULL-
frequency entries) where hand-picking a word list the way that script did
doesn't scale. See this project's own planning conversation for the full
diagnostic trail (the reported case: 跑来跑去, a real CEDICT word, was
segmenting as 跑来/跑去 because both pieces already have strong real
frequency and 跑来跑去 itself has none to compete with).

## Candidate selection - computed, not hardcoded

Unlike backfill_numeral_frequencies.py's fixed word list, this script
re-derives its candidates every run: every CEDICT/HSK dictionary_words row
with NULL frequency is segmented *in isolation* through the real segmenter
(no overlay) - only words the DP itself currently chooses to fragment are
"provably at risk" (not just "has no frequency," which most NULL-frequency
CEDICT entries correctly have no bearing on, since nothing competes with
them for an isolated/rare word). This means the script stays useful after
any future dictionary/HSK data refresh - re-run it and it'll catch newly
introduced gaps of the same shape, rather than needing a new hardcoded list
each time.

Candidates split into three groups by where their estimate comes from:

- Group A: HSK-backed, has a usable hsk_entries.hsk_frequency rank (not
  NULL, not the 1,000,000 sentinel - see below). Estimated via a live-fit
  rank-to-frequency regression (see fit_rank_regression).
- Group B: HSK-backed, no usable rank. Estimated via the margin-based
  method (see estimate_via_margin), same as Group C.
- Group C: CEDICT-only (no HSK level at all - hsk_entries never covers
  these, confirmed empirically: 0 of 23,341 CEDICT-only broken words in
  this project's own scoping had any hsk_entries row). Restricted to words
  matching a 4-character reduplication pattern (AABB/ABAB/ABAC/ABCB) -
  see reduplication_pattern - since the wider CEDICT-only tail has no
  reliable automatic signal for "worth fixing" (a first attempt at ranking
  by weakest-component-frequency surfaced junk like 我人/中中/为上 - real
  but obscure CEDICT entries coincidentally built from ultra-common
  characters - ahead of genuine compounds, and was abandoned).

## Group A methodology: the HSK rank IS real, external, calibratable data

complete.json's "frequency" field (imported verbatim into hsk_entries.
hsk_frequency by scripts/import_hsk.py) turned out to be a *rank* from some
external reference wordlist, not a raw count - confirmed by its shape
(11,470 entries, values 1 to 379,791, exactly 93 pinned at a suspiciously
round 1,000,000 sentinel for "no rank data") and by fitting it against this
app's own real corpus frequency for the 11,000+ words that have both:
log(rank) vs log(real frequency) gives Pearson r ≈ -0.90 (R² ≈ 0.82), a
strong Zipfian power-law relationship. fit_rank_regression refits this live
from the current DB every run (not hardcoded coefficients) - self-
calibrating if the underlying data ever changes - and estimate_via_rank
applies it to each Group A word using its own rank.

## Group B/C methodology: same margin-based approach as the numeral script,
## generalized to N-way splits

For a word with no rank data, the segmenter's own chosen fragmentation
(from segmenting the word in isolation) tells us exactly what it's
currently losing to. estimate_via_margin computes the DP break-even point
for that specific split - for a word splitting into k pieces with
frequencies f1..fk, that's (f1*f2*...*fk) / total^(k-1) (generalizing the
numeral script's 2-way f1*f2/total) - and sets the estimate to
MARGIN_MULTIPLIER times that, or the word's own best-attested containing
compound's frequency, whichever is higher. Same reasoning as
backfill_numeral_frequencies.py's STRUCTURAL_COMPOUNDS: a safety margin
over the exact split-competition threshold, not a precise measurement.

## What this script does

1. Finds every currently-fragmenting CEDICT/HSK word (the segmenter-based
   test above), splits into Groups A/B/C.
2. Computes an estimated frequency per word (rank regression for A, margin
   method for B/C), upserts a WordFrequencyOverride row per word (word,
   frequency, reason - reason records exactly how the number was derived).
3. Syncs those values into dictionary_words.frequency for these words only
   (same reasoning as backfill_numeral_frequencies.py - dictionary_words.
   frequency is a derived cache of the override table for these words, so
   the UI's rarity badge/corpus-frequency display stays consistent).
4. Re-runs compute_word_rarity.py.

Re-running this script is safe/idempotent - upserts throughout. A word
fixed in an earlier run will simply no longer appear as a "broken"
candidate (it segments as itself now), so subsequent runs only ever touch
newly-introduced gaps.

segmenter_loader.invalidate_segmenter_cache() is NOT called here - this
script talks to the DB directly. Restart the backend (or otherwise trigger
a fresh get_segmenter() build) after running this for the new overrides to
take effect in live segmentation.

Usage:
    uv run python scripts/backfill_hsk_cedict_frequencies.py
"""
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.modules.known_words.segmenter_loader import get_segmenter

MARGIN_MULTIPLIER = 3
# A compound shouldn't come out to a wildly smaller order of magnitude than
# its own rarest piece just because the break-even margin against its
# specific split happened to be tiny - see estimate_via_margin's docstring
# for the concrete case (跑来跑去) that surfaced this.
REALISTIC_FLOOR_DIVISOR = 50
# Confirmed empirically (this project's own planning conversation) - a
# round number this suspicious, at exactly this value, on exactly this many
# rows, is a "no rank data" placeholder, not a real rank of one million.
HSK_RANK_SENTINEL = 1_000_000


def find_broken_candidates(db, segmenter) -> list[dict]:
    """
    Every CEDICT/HSK dictionary_words row with NULL frequency that the
    segmenter itself currently fragments when segmenting the word alone -
    see this script's own docstring for why this (not just "has no
    frequency") is the qualifying test.
    """
    rows = db.execute(text("""
        SELECT word, hsk_v2_2012, hsk_v3_2021, hsk_v3_2026
        FROM dictionary_words
        WHERE frequency IS NULL
          AND (is_cedict = true OR hsk_v2_2012 IS NOT NULL OR hsk_v3_2021 IS NOT NULL OR hsk_v3_2026 IS NOT NULL)
          AND char_length(word) >= 2
    """)).fetchall()

    broken = []
    for word, v2, v3a, v3b in rows:
        segs = segmenter.segment(word)
        if len(segs) > 1:
            broken.append({
                "word": word,
                "is_hsk": bool(v2 or v3a or v3b),
                "fragments": [s.word for s in segs],
            })
    return broken


def reduplication_pattern(word: str) -> str | None:
    """AABB/ABAB/ABAC/ABCB for a 4-character word, else None. See this
    script's docstring (Group C) for why only 4-character CEDICT-only words
    are considered at all."""
    if len(word) != 4:
        return None
    a, b, c, d = word
    if a == b and c == d and a != c:
        return "AABB"
    if a == c and b == d and a != b:
        return "ABAB"
    if a == c and b != d and a != b and a != d:
        return "ABAC"
    if b == d and a != c and a != b and c != b:
        return "ABCB"
    return None


def fit_rank_regression(db) -> tuple[float, float, int]:
    """Returns (slope, intercept, sample_size) fit live from every word
    that currently has both a real dictionary_words.frequency and a usable
    hsk_entries.hsk_frequency rank - see this script's docstring for why
    this relationship (and refitting it live rather than hardcoding
    coefficients) is trustworthy."""
    rows = db.execute(text("""
        SELECT h.hsk_frequency, d.frequency
        FROM hsk_entries h
        JOIN dictionary_words d ON d.word = h.simplified
        WHERE h.hsk_frequency IS NOT NULL AND h.hsk_frequency < :sentinel
          AND d.frequency IS NOT NULL AND d.frequency > 0
    """), {"sentinel": HSK_RANK_SENTINEL}).fetchall()

    xs = [math.log(r[0]) for r in rows]
    ys = [math.log(r[1]) for r in rows]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept, n


def get_hsk_rank(db, word: str) -> int | None:
    row = db.execute(text("""
        SELECT hsk_frequency FROM hsk_entries
        WHERE simplified = :word AND hsk_frequency IS NOT NULL AND hsk_frequency < :sentinel
        ORDER BY hsk_frequency ASC LIMIT 1
    """), {"word": word, "sentinel": HSK_RANK_SENTINEL}).fetchone()
    return row[0] if row else None


def estimate_via_rank(rank: int, slope: float, intercept: float, n: int) -> tuple[int, str]:
    """Returns (freq, description) - description is a fragment, not a full
    sentence, since this always feeds into estimate_via_margin as an
    extra_candidate (see this script's docstring, Group A, for why: the
    regression is trustworthy on average but found live to occasionally
    undershoot the actual break-even point for a fragmenting word, so it
    still needs the same break-even/floor/top-1 safety net Group B/C get,
    not a bare pass-through)."""
    freq = round(math.exp(intercept) * (rank ** slope))
    description = (
        f"its HSK frequency rank ({rank:,}) via a log-log power-law regression fit live against "
        f"{n:,} words with both a real corpus frequency and an HSK rank "
        f"(freq = exp({intercept:.4f}) * rank^{slope:.4f} = {max(freq, 1):,})"
    )
    return max(freq, 1), description


def estimate_via_margin(db, word: str, fragments: list[str], extra_candidate: tuple[int, str] | None = None) -> tuple[int, str]:
    """Same method as backfill_numeral_frequencies.py's STRUCTURAL_COMPOUNDS,
    generalized to however many fragments the segmenter's own chosen split
    actually has (usually 2, occasionally more), plus one addition that
    script didn't need: a realistic-magnitude floor.

    The numeral script's fragments were themselves extremely frequent
    (millions+), so 3x their break-even point was still a substantial,
    realistic number. Most of this script's fragments are only moderately
    frequent (thousands to hundreds of thousands) - for those, the bare
    break-even point is a tiny fraction of 1 (product/total^(k-1) shrinks
    fast as the fragments shrink), so 3x it can round to single digits -
    found live while testing this script: 跑来跑去 (fragments 跑来=120,242,
    跑去=199,051) came out to frequency=4, which is absurd for an everyday
    phrase and would classify it as "extremely rare" in the UI. Mathematically
    correct (it does beat its own specific split by exactly 3x), but not a
    credible estimate of real-world usage on its own.

    min(fragment_freqs) / REALISTIC_FLOOR_DIVISOR fixes this: a compound
    should plausibly occur at least a modest fraction as often as its
    rarest piece alone, not orders of magnitude less. Taking the max of
    all candidates (split margin, this floor, top-1 containing word, plus
    extra_candidate if given) can only ever raise the estimate, never lower
    it below the proven break-even margin - the floor is a backstop, not a
    replacement.

    extra_candidate lets Group A reuse this same safety net: the rank
    regression is a real, data-driven estimate, but found live while
    testing this script to occasionally undershoot for words whose
    fragments are BOTH unusually extreme (不太 "not very" split into 不=
    70.2M + 太=15.5M, two of the most common characters in the language -
    the regression's 21,382 lost to their ~54,278 break-even point). Group
    A callers pass (rank_estimate, description) here so the same
    break-even/floor/top-1 comparison still applies as a backstop, exactly
    as it does for Group B/C.
    """
    total = db.execute(text(
        "SELECT SUM(frequency) FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
    )).scalar()

    fragment_freqs = []
    for frag in fragments:
        row = db.execute(text("SELECT frequency FROM dictionary_words WHERE word = :w"), {"w": frag}).fetchone()
        fragment_freqs.append(row[0] if row and row[0] else 1)

    product = 1
    for f in fragment_freqs:
        product *= f
    k = len(fragments)
    split_margin_value = round(MARGIN_MULTIPLIER * product / (total ** (k - 1)))
    realistic_floor_value = round(min(fragment_freqs) / REALISTIC_FLOOR_DIVISOR)

    top1 = db.execute(text("""
        SELECT word, frequency FROM dictionary_words
        WHERE word LIKE :pat AND word != :word AND frequency IS NOT NULL
        ORDER BY frequency DESC LIMIT 1
    """), {"pat": f"%{word}%", "word": word}).fetchone()
    top1_freq, top1_word = (top1[1], top1[0]) if top1 else (0, None)

    fragment_desc = "+".join(fragments)
    fragment_freq_desc = ", ".join(f"{f}={n:,}" for f, n in zip(fragments, fragment_freqs))
    candidates = [
        (split_margin_value, (
            f"{MARGIN_MULTIPLIER}x the DAG break-even point against being split into its own "
            f"segmenter-chosen fragments {fragment_desc} ({fragment_freq_desc}; "
            f"{MARGIN_MULTIPLIER} * product / total^{k-1} = {split_margin_value:,})"
        )),
        (realistic_floor_value, (
            f"1/{REALISTIC_FLOOR_DIVISOR} of its rarest fragment's own frequency "
            f"(min({fragment_freq_desc}) / {REALISTIC_FLOOR_DIVISOR} = {realistic_floor_value:,}) - a realistic-"
            f"magnitude floor, since the break-even margin alone can round to an unrealistically tiny "
            f"number when the fragments themselves aren't extremely frequent (see this function's own "
            f"docstring)"
        )),
        (top1_freq, (
            f"the frequency of its single highest-frequency real containing dictionary word, "
            f"{top1_word}={top1_freq:,}" if top1_word else "0 (no real dictionary word contains it)"
        )),
    ]
    if extra_candidate is not None:
        candidates.append(extra_candidate)
    freq, chosen_desc = max(candidates, key=lambda c: c[0])
    reason = (
        f"Estimated as {chosen_desc}. See scripts/backfill_hsk_cedict_frequencies.py's docstring "
        f"for the full method and why multiple candidate values are compared."
    )
    return max(freq, 1), reason


def main():
    db = SessionLocal()
    try:
        segmenter = get_segmenter(db)

        print("Scanning for currently-fragmenting CEDICT/HSK words with NULL frequency...")
        broken = find_broken_candidates(db, segmenter)
        print(f"Found {len(broken):,} broken candidates.")

        hsk_words = [w for w in broken if w["is_hsk"]]
        cedict_words = [w for w in broken if not w["is_hsk"]]

        print("Fitting rank-to-frequency regression...")
        slope, intercept, n_calibration = fit_rank_regression(db)
        print(f"  slope={slope:.4f} intercept={intercept:.4f} (fit against {n_calibration:,} words)")

        group_a, group_b = [], []
        for w in hsk_words:
            rank = get_hsk_rank(db, w["word"])
            (group_a if rank is not None else group_b).append((w, rank))

        group_c = [w for w in cedict_words if reduplication_pattern(w["word"])]

        print(f"Group A (HSK, has rank): {len(group_a):,}")
        print(f"Group B (HSK, no rank): {len(group_b):,}")
        print(f"Group C (CEDICT-only, reduplication pattern): {len(group_c):,}")

        estimates: dict[str, tuple[int, str]] = {}

        for w, rank in group_a:
            rank_freq, rank_desc = estimate_via_rank(rank, slope, intercept, n_calibration)
            estimates[w["word"]] = estimate_via_margin(
                db, w["word"], w["fragments"], extra_candidate=(rank_freq, rank_desc)
            )

        for w, _rank in group_b:
            estimates[w["word"]] = estimate_via_margin(db, w["word"], w["fragments"])

        for w in group_c:
            estimates[w["word"]] = estimate_via_margin(db, w["word"], w["fragments"])

        print(f"\nComputed estimates for {len(estimates):,} words.")

        for word, (freq, reason) in estimates.items():
            db.execute(text("""
                INSERT INTO word_frequency_overrides (word, frequency, reason)
                VALUES (:word, :freq, :reason)
                ON CONFLICT (word) DO UPDATE
                SET frequency = EXCLUDED.frequency, reason = EXCLUDED.reason
            """), {"word": word, "freq": freq, "reason": reason})
        print(f"Upserted {len(estimates):,} word_frequency_overrides rows.")

        for word, (freq, _reason) in estimates.items():
            db.execute(text(
                "UPDATE dictionary_words SET frequency = :freq WHERE word = :word"
            ), {"word": word, "freq": freq})
        print(f"Synced {len(estimates):,} dictionary_words.frequency values.")

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("\nRe-running compute_word_rarity.py...")
    subprocess.run(
        [sys.executable, str(Path(__file__).parent / "compute_word_rarity.py")],
        check=True,
    )


if __name__ == "__main__":
    main()
