import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.modules.known_words.segmenter_loader import _load_affix_config


def _matching_affix_note(word: str, suffixes: dict[str, float], prefixes: dict[str, float]) -> str | None:
    """
    Returns a note describing which configured affix rule `word` would be
    discounted by, or None if it doesn't match any. Same matching logic as
    Segmenter._affix_discount (word must be strictly longer than the affix).
    """
    for suffix in suffixes:
        if len(word) > len(suffix) and word.endswith(suffix):
            return f"HSK, ends with configured suffix '{suffix}'"
    for prefix in prefixes:
        if len(word) > len(prefix) and word.startswith(prefix):
            return f"HSK, starts with configured prefix '{prefix}'"
    return None


def populate_affix_exemptions():
    """
    Pre-populates segmentation_affix_exemptions from HSK vocabulary: any HSK
    word that would otherwise be caught by a configured affix discount (e.g.
    这里, 家里) is protected, since HSK is a small, hand-curated "this is a
    word worth learning" list - a much more reliable lexicalization signal
    than CC-CEDICT, which documents plenty of compositional strings (村里,
    水里) and coincidental matches (transliterated names like 马德里) that
    are exactly the kind of thing the affix discount is meant to catch.
    Deliberately NOT sourced from CC-CEDICT for this reason.

    Safe to re-run: uses _load_affix_config (the same code-defaults + DB
    merge Segmenter itself uses, see segmenter_loader.py) so it always
    reflects the currently active affix rules, and inserts are
    ON CONFLICT (word) DO NOTHING against the unique `word` column.
    """
    db = SessionLocal()
    try:
        suffixes, prefixes, _ = _load_affix_config(db)
        print(f"Checking against {len(suffixes)} suffix / {len(prefixes)} prefix affix rules...")

        hsk_words = [row[0] for row in db.execute(text("SELECT simplified FROM hsk_entries"))]
        print(f"Scanning {len(hsk_words):,} HSK words...")

        exemptions: dict[str, str] = {}
        for word in hsk_words:
            note = _matching_affix_note(word, suffixes, prefixes)
            if note:
                exemptions[word] = note

        print(f"Found {len(exemptions)} HSK words matching a configured affix.")

        inserted = 0
        for word, note in exemptions.items():
            result = db.execute(text(
                "INSERT INTO segmentation_affix_exemptions (word, note) VALUES (:word, :note) "
                "ON CONFLICT (word) DO NOTHING"
            ), {"word": word, "note": note})
            if result.rowcount:
                inserted += 1

        db.commit()
        print(f"Inserted {inserted} new exemptions ({len(exemptions) - inserted} already present).")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    populate_affix_exemptions()
