import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.modules.known_words.models import CedictEntry


CEDICT_FILE = Path(__file__).parent.parent / "assets" / "cc-cedict" / "cedict_ts.u8"

LINE_RE = re.compile(r"^(\S+) (\S+) \[(.*?)\] /(.*)/\s*$")

TONE_MARKS = {
    "a": "aāáǎà",
    "e": "eēéěè",
    "i": "iīíǐì",
    "o": "oōóǒò",
    "u": "uūúǔù",
    "ü": "üǖǘǚǜ",
}


def _convert_syllable(syllable: str) -> str:
    """
    Converts one numeric-tone pinyin syllable (e.g. "Bei3", "nu:3", "de5",
    "r5") to diacritic form (e.g. "Běi", "nǚ", "de", "r"). Preserves case, so
    proper-noun capitalization (CC-CEDICT capitalizes the first syllable of
    names) survives.
    """
    match = re.match(r"^([A-Za-züÜ:]+)([0-5]?)$", syllable)
    if not match:
        return syllable

    body, tone_digit = match.group(1), match.group(2)
    body = body.replace("u:", "ü").replace("U:", "Ü")
    tone = int(tone_digit) if tone_digit else 0  # 0/5 = neutral, no mark

    if tone in (0, 5):
        return body

    # Tone-mark placement: a/e always take it; "ou" takes it on the o;
    # otherwise it goes on the last of i/o/u/ü in the syllable (this single
    # rule correctly covers both "iu" -> u and "ui" -> i).
    lower = body.lower()
    if "a" in lower:
        idx = lower.index("a")
    elif "e" in lower:
        idx = lower.index("e")
    elif "ou" in lower:
        idx = lower.index("o")
    else:
        idx = None
        for i in range(len(lower) - 1, -1, -1):
            if lower[i] in "iouü":
                idx = i
                break
        if idx is None:
            return body

    vowel = lower[idx]
    marked = TONE_MARKS[vowel][tone]
    if body[idx].isupper():
        marked = marked.upper()
    return body[:idx] + marked + body[idx + 1:]


def numeric_to_diacritic(pinyin: str) -> str:
    """Converts a whole CC-CEDICT pinyin field (space-separated syllables,
    e.g. "Bei3 jing1") to diacritic form (e.g. "Běi jīng")."""
    return " ".join(_convert_syllable(s) for s in pinyin.split(" "))


def parse_line(line: str) -> dict | None:
    match = LINE_RE.match(line.strip())
    if not match:
        return None
    traditional, simplified, pinyin_numeric, defs = match.groups()
    return {
        "traditional": traditional,
        "simplified": simplified,
        "pinyin_numeric": pinyin_numeric,
        "pinyin": numeric_to_diacritic(pinyin_numeric),
        "definitions": defs.split("/"),
    }


def import_cedict():
    print(f"Loading {CEDICT_FILE}...")

    db = SessionLocal()
    try:
        print("Clearing existing cedict_entries (re-runnable import)...")
        db.execute(text("TRUNCATE cedict_entries RESTART IDENTITY"))
        db.commit()

        batch_size = 2000
        count = 0
        skipped = 0

        with open(CEDICT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.startswith("#") or line.startswith("%"):
                    continue

                parsed = parse_line(line)
                if parsed is None:
                    skipped += 1
                    continue

                db.add(CedictEntry(**parsed))
                count += 1

                if count % batch_size == 0:
                    db.commit()
                    print(f"  {count:,} entries committed...")

        db.commit()
        print(f"CC-CEDICT import complete. {count:,} entries imported, {skipped} lines skipped (unparsable).")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_cedict()
