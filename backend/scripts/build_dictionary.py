import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal


def build_dictionary():
    db = SessionLocal()
    try:
        print("Building dictionary_words from word_frequencies, hsk_entries, and cedict_entries...")

        # CC-CEDICT contributes no columns of its own (no frequency or HSK
        # level) - it only contributes *presence*, the same way an HSK-only
        # word does. That's enough to make it reachable in the trie/DAG: a
        # dictionary_words row with a NULL frequency still forms trie edges,
        # it just scores at the DP's existing unknown-floor weight instead of
        # a real frequency (see Segmenter._word_weight / segmenter_loader's
        # freq_dict filter), so it's only chosen when nothing better covers
        # that span - not force-injected into segmentation.
        db.execute(text("""
            INSERT INTO dictionary_words (word, frequency, hsk_v2_2012, hsk_v3_2021, hsk_v3_2026)

            SELECT
                COALESCE(wf.word, he.simplified, ce.simplified) AS word,
                wf.frequency,
                he.hsk_v2_2012,
                he.hsk_v3_2021,
                he.hsk_v3_2026

            FROM word_frequencies wf
            FULL OUTER JOIN hsk_entries he ON he.simplified = wf.word
            FULL OUTER JOIN (SELECT DISTINCT simplified FROM cedict_entries) ce
                ON ce.simplified = COALESCE(wf.word, he.simplified)

            ON CONFLICT (word) DO UPDATE SET
                frequency = EXCLUDED.frequency,
                hsk_v2_2012 = EXCLUDED.hsk_v2_2012,
                hsk_v3_2021 = EXCLUDED.hsk_v3_2021,
                hsk_v3_2026 = EXCLUDED.hsk_v3_2026
        """))

        db.commit()

        result = db.execute(text("SELECT COUNT(*) FROM dictionary_words")).scalar()
        freq_only = db.execute(text("""
            SELECT COUNT(*) FROM dictionary_words
            WHERE frequency IS NOT NULL
            AND hsk_v2_2012 IS NULL
            AND hsk_v3_2021 IS NULL
            AND hsk_v3_2026 IS NULL
        """)).scalar()
        no_frequency = db.execute(text("""
            SELECT COUNT(*) FROM dictionary_words
            WHERE frequency IS NULL
        """)).scalar()
        both = db.execute(text("""
            SELECT COUNT(*) FROM dictionary_words
            WHERE frequency IS NOT NULL
            AND (hsk_v2_2012 IS NOT NULL OR hsk_v3_2021 IS NOT NULL OR hsk_v3_2026 IS NOT NULL)
        """)).scalar()
        cedict_only = db.execute(text("""
            SELECT COUNT(*) FROM dictionary_words dw
            WHERE dw.frequency IS NULL
            AND dw.hsk_v2_2012 IS NULL
            AND dw.hsk_v3_2021 IS NULL
            AND dw.hsk_v3_2026 IS NULL
            AND EXISTS (SELECT 1 FROM cedict_entries ce WHERE ce.simplified = dw.word)
        """)).scalar()
        hsk_only = no_frequency - cedict_only

        print(f"  Total dictionary entries: {result:,}")
        print(f"  Frequency data only: {freq_only:,}")
        print(f"  Both frequency and HSK data: {both:,}")
        print(f"  No frequency data (HSK and/or CC-CEDICT only): {no_frequency:,}")
        print(f"    of which CC-CEDICT-only (no frequency, no HSK level): {cedict_only:,}")
        print(f"    of which HSK-only or HSK+CC-CEDICT (no frequency): {hsk_only:,}")
        print("Done.")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    build_dictionary()