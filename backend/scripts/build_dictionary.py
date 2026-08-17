import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal


def build_dictionary():
    db = SessionLocal()
    try:
        print("Building dictionary_words from word_frequencies and hsk_entries...")

        db.execute(text("""
            INSERT INTO dictionary_words (word, frequency, hsk_v2_2012, hsk_v3_2021, hsk_v3_2026)

            SELECT
                COALESCE(wf.word, he.simplified) AS word,
                wf.frequency,
                he.hsk_v2_2012,
                he.hsk_v3_2021,
                he.hsk_v3_2026

            FROM word_frequencies wf
            FULL OUTER JOIN hsk_entries he ON he.simplified = wf.word

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
        hsk_only = db.execute(text("""
            SELECT COUNT(*) FROM dictionary_words
            WHERE frequency IS NULL
        """)).scalar()
        both = db.execute(text("""
            SELECT COUNT(*) FROM dictionary_words
            WHERE frequency IS NOT NULL
            AND (hsk_v2_2012 IS NOT NULL OR hsk_v3_2021 IS NOT NULL OR hsk_v3_2026 IS NOT NULL)
        """)).scalar()

        print(f"  Total dictionary entries: {result:,}")
        print(f"  Frequency data only: {freq_only:,}")
        print(f"  HSK data only (not in frequency corpus): {hsk_only:,}")
        print(f"  Both frequency and HSK data: {both:,}")
        print("Done.")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    build_dictionary()