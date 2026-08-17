import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.modules.known_words.models import HskEntry, HskForm


HSK_FILE = Path(__file__).parent.parent / "assets" / "hsk" / "complete.json"


def parse_levels(levels: list[str]) -> dict:
    result = {"hsk_v2_2012": None, "hsk_v3_2021": None, "hsk_v3_2026": None}
    for level in levels:
        if level.startswith("old-"):
            result["hsk_v2_2012"] = int(level.split("-")[1])
        elif level.startswith("newest-"):
            result["hsk_v3_2026"] = int(level.split("-")[1])
        elif level.startswith("new-"):
            result["hsk_v3_2021"] = int(level.split("-")[1])
    return result


def import_hsk():
    print(f"Loading {HSK_FILE}...")
    with open(HSK_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Importing {len(data)} entries...")

    db = SessionLocal()
    try:
        batch_size = 500
        for i, entry in enumerate(data):
            levels = parse_levels(entry.get("level", []))

            hsk_entry = HskEntry(
                simplified=entry["simplified"],
                radical=entry.get("radical"),
                hsk_v2_2012=levels["hsk_v2_2012"],
                hsk_v3_2021=levels["hsk_v3_2021"],
                hsk_v3_2026=levels["hsk_v3_2026"],
                hsk_frequency=entry.get("frequency"),
                pos=entry.get("pos", []),
            )
            db.add(hsk_entry)
            db.flush()  # get the id without committing

            for form in entry.get("forms", []):
                transcriptions = form.get("transcriptions", {})
                hsk_form = HskForm(
                    entry_id=hsk_entry.id,
                    traditional=form.get("traditional"),
                    pinyin=transcriptions.get("pinyin"),
                    numeric_transcription=transcriptions.get("numeric"),
                    meanings=form.get("meanings", []),
                    classifiers=form.get("classifiers", []),
                )
                db.add(hsk_form)

            if i % batch_size == 0:
                db.commit()
                print(f"  {i}/{len(data)} entries committed...")

        db.commit()
        print(f"HSK import complete. {len(data)} entries imported.")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_hsk()