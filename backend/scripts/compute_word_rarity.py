"""
Populates DictionaryWord.freq_per_million and .rarity_tier from `frequency`,
using the finalized cutoffs analyze_word_rarity.py's distribution analysis
produced. Writes to the database - unlike analyze_word_rarity.py, which is
read-only.

Cutoffs (occurrences per million, finalized - not recomputed here):
  extremely_rare:    < 0.03
  rare:               0.03 - 1
  uncommon:           1 - 50
  common:             50 - 2250
  extremely_common:  >= 2250

Implementation note: this is done as a couple of bulk SQL UPDATEs (one to
compute freq_per_million from the total corpus frequency, one to assign
rarity_tier from freq_per_million via a CASE expression) rather than a
Python row-by-row/chunked loop - the same "single bulk UPDATE across the
whole table" shape import_frequencies.py's calc_combined/frequency steps
already use. At ~1.6M rows this is both simpler and far fewer round trips
than any per-row or batched-per-row approach, while still satisfying "don't
commit one row at a time" - there's no reason to loop in Python for a
computation the database can do in one pass. Both columns are also reset
to NULL first for any row that no longer qualifies (frequency NULL or 0),
so a re-run after frequency data changes doesn't leave stale values behind
- this is what makes the script safely re-runnable (plain UPDATEs, no
INSERT/conflict handling needed either way).

Usage:
    uv run python scripts/compute_word_rarity.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal


def main():
    db = SessionLocal()
    try:
        total = db.execute(text(
            "SELECT SUM(frequency) FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
        )).scalar()
        if not total:
            print("No dictionary words with frequency > 0 found — nothing to compute.")
            return

        n_qualifying = db.execute(text(
            "SELECT COUNT(*) FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
        )).scalar()
        print(f"Total corpus frequency: {total:,} across {n_qualifying:,} words with frequency > 0.")

        # Reset first - keeps this re-runnable/correct if frequency data has
        # changed since a previous run (a word that no longer qualifies
        # shouldn't keep a stale tier from before).
        db.execute(text(
            "UPDATE dictionary_words SET freq_per_million = NULL, rarity_tier = NULL "
            "WHERE frequency IS NULL OR frequency = 0"
        ))

        db.execute(text("""
            UPDATE dictionary_words
            SET freq_per_million = frequency::float / :total * 1000000
            WHERE frequency IS NOT NULL AND frequency > 0
        """), {"total": total})

        db.execute(text("""
            UPDATE dictionary_words
            SET rarity_tier = CASE
                WHEN freq_per_million < 0.03 THEN 'extremely_rare'
                WHEN freq_per_million < 1 THEN 'rare'
                WHEN freq_per_million < 50 THEN 'uncommon'
                WHEN freq_per_million < 2250 THEN 'common'
                ELSE 'extremely_common'
            END
            WHERE freq_per_million IS NOT NULL
        """))

        db.commit()

        print("\nWords per tier:")
        rows = db.execute(text("""
            SELECT rarity_tier, COUNT(*) FROM dictionary_words
            WHERE rarity_tier IS NOT NULL
            GROUP BY rarity_tier
        """)).fetchall()
        # Print in cutoff order (extremely_rare -> extremely_common), not
        # whatever order GROUP BY happened to return.
        order = ["extremely_rare", "rare", "uncommon", "common", "extremely_common"]
        counts = {tier: count for tier, count in rows}
        total_assigned = 0
        for tier in order:
            count = counts.get(tier, 0)
            total_assigned += count
            print(f"  {tier:<18} {count:>10,}")
        print(f"  {'total':<18} {total_assigned:>10,}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
