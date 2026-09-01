"""
One-time exploratory analysis of the corpus frequency distribution, to
decide where to set rarity-tier cutoffs before committing them to
DictionaryWord. Read-only - doesn't write anything to the database.

Frequency in a natural-language corpus follows a power law (Zipf's law): a
handful of words account for a huge share of occurrences, and most distinct
words are rare. That means:
  - Equal-COUNT buckets (e.g. "top 20% of words by rank") produce a
    misleadingly wide "common" bucket and a "rare" bucket that swallows
    most of the dictionary.
  - Equal-WIDTH buckets on raw frequency are worse in the same direction.
  - Equal-width buckets in LOG-frequency space is the standard approach for
    this kind of distribution - each tier represents roughly "an order of
    magnitude more/less common" than its neighbor, which is the actual
    shape of the data.

This script normalizes each word's frequency to occurrences-per-million
(so tiers are interpretable independent of this specific corpus's total
size), log-transforms it, and reports the real distribution plus candidate
cutoff sets - so tiers get chosen from what's actually in the data rather
than guessed at.

Usage:
    uv run python scripts/analyze_word_rarity.py
    uv run python scripts/analyze_word_rarity.py --tiers 7
"""
import argparse
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal


TIER_NAMES = {
    5: ["Extremely rare", "Rare", "Uncommon", "Common", "Extremely common"],
    7: ["Extremely rare", "Very rare", "Rare", "Uncommon", "Common", "Very common", "Extremely common"],
}


def fetch_frequencies(db):
    return db.execute(text(
        "SELECT word, frequency, hsk_v2_2012, hsk_v3_2021, hsk_v3_2026 "
        "FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
    )).fetchall()


def print_percentiles(values):
    qs = statistics.quantiles(values, n=100, method="inclusive")
    picks = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    print("\nlog10(freq per million) percentiles:")
    for p in picks:
        fpm = 10 ** qs[p - 1]
        print(f"  p{p:>2}: log={qs[p-1]:7.4f}   (~{fpm:>10.4f} per million)")


def print_histogram(values, bins=24):
    lo, hi = min(values), max(values)
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    max_count = max(counts) or 1
    print(f"\nHistogram of log10(freq per million) — {bins} bins, {len(values):,} words:")
    for i, c in enumerate(counts):
        bin_lo = lo + i * width
        bar = "#" * int(c / max_count * 50)
        print(f"  {bin_lo:7.3f} | {bar} {c}")


def propose_equal_width_log_tiers(values, n_tiers):
    tier_names = TIER_NAMES.get(n_tiers, [f"Tier {i+1}" for i in range(n_tiers)])
    lo, hi = min(values), max(values)
    width = (hi - lo) / n_tiers
    cutoffs = [lo + i * width for i in range(n_tiers + 1)]

    tier_counts = [0] * n_tiers
    for v in values:
        idx = min(int((v - lo) / width), n_tiers - 1)
        tier_counts[idx] += 1

    print(f"\nCandidate {n_tiers}-tier cutoffs (equal-width in log10 space):")
    for i, name in enumerate(tier_names):
        freq_lo, freq_hi = 10 ** cutoffs[i], 10 ** cutoffs[i + 1]
        print(f"  {name:<20} {freq_lo:>10.4f} - {freq_hi:>10.4f} per million   ({tier_counts[i]:,} words)")

    return cutoffs, tier_names


def tier_for_value(v, cutoffs, tier_names):
    lo, width = cutoffs[0], cutoffs[1] - cutoffs[0]
    idx = min(max(int((v - lo) / width), 0), len(tier_names) - 1)
    return tier_names[idx]


def cross_tab_hsk(rows, fpm_by_word, cutoffs, tier_names):
    """Sanity check: HSK1/2 words should land overwhelmingly in the top one
    or two tiers. If they don't, the corpus may be skewed or the cutoffs
    need adjusting before committing to them."""
    for hsk_attr, label in [("hsk_v3_2021", "HSK v3 2021")]:
        by_level = defaultdict(lambda: defaultdict(int))
        for row in rows:
            level = getattr(row, hsk_attr)
            if level is None:
                continue
            v = math.log10(fpm_by_word[row.word])
            by_level[level][tier_for_value(v, cutoffs, tier_names)] += 1

        print(f"\nCross-tab against {label} (sanity check — lower HSK levels should skew toward the common end):")
        for level in sorted(by_level.keys()):
            total = sum(by_level[level].values())
            breakdown = ", ".join(
                f"{name}: {by_level[level].get(name, 0)} ({by_level[level].get(name, 0)/total*100:.0f}%)"
                for name in tier_names if by_level[level].get(name, 0) > 0
            )
            print(f"  HSK {level:<3} ({total:>5} words) — {breakdown}")


def print_extremes(rows, fpm_by_word, n=10):
    sorted_rows = sorted(rows, key=lambda r: r.frequency, reverse=True)
    print(f"\nTop {n} most frequent words (sanity check — should be function words):")
    for row in sorted_rows[:n]:
        print(f"  {row.word:<8} {fpm_by_word[row.word]:>12.2f} / million")
    print(f"\n{n} rarest words with frequency > 0 (bottom of the loaded set):")
    for row in sorted_rows[-n:]:
        print(f"  {row.word:<8} {fpm_by_word[row.word]:>12.6f} / million")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiers", type=int, default=5, help="Number of candidate tiers (5 or 7 have named labels; any other number gets generic 'Tier N' labels)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = fetch_frequencies(db)
        if not rows:
            print("No dictionary words with frequency > 0 found — nothing to analyze.")
            return

        total_freq = sum(row.frequency for row in rows)
        print(f"Loaded {len(rows):,} words with frequency data. Total corpus frequency: {total_freq:,}")

        fpm_by_word = {row.word: row.frequency / total_freq * 1_000_000 for row in rows}
        log_values = [math.log10(fpm) for fpm in fpm_by_word.values()]

        print_percentiles(log_values)
        print_histogram(log_values)
        cutoffs, tier_names = propose_equal_width_log_tiers(log_values, args.tiers)
        cross_tab_hsk(rows, fpm_by_word, cutoffs, tier_names)
        print_extremes(rows, fpm_by_word)

        print(
            "\nNote: these are equal-WIDTH-in-log-space cutoffs, so tier word-counts "
            "are expected to be unequal — that's the point, not a bug. If a tier's "
            "count looks too small/large or the HSK cross-tab looks off, try "
            "--tiers with a different count, or use these numbers as a starting "
            "point for manually-chosen cutoffs instead of the automatic ones."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()