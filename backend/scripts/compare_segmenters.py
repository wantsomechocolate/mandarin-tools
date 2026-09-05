"""
Runs the segmenter's best-guess (DP) walk and full segmentation (every DAG
candidate, chosen or not) against the real dictionary/Postgres data on one
or more sample passages, and prints a side-by-side diff. Useful for
eyeballing what full segmentation adds before trusting it as the source of
"extra matches" in production analysis (service.analyze_text).

Previously compared the DAG segmenter against the now-retired segmentor.py
longest_matching; repurposed rather than deleted; the manual-comparison
need is the same.

Usage:
    uv run python scripts/compare_segmenters.py
    uv run python scripts/compare_segmenters.py --text "自定义的一句话"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.modules.known_words.segmenter_loader import get_segmenter
from app.modules.known_words.dag_segmentor import aggregate_segments, aggregate_full_segmentation


DEFAULT_SAMPLES = [
    "我来到北京清华大学",
    "他来到了网易杭研大厦",
    "研究生命起源是一个有趣的话题",
    "小明硕士毕业于中国科学院计算所",
]

# Matches service.DEFAULT_STOPWORDS' minimal newline handling closely enough
# for a standalone dev script - not pulling in the full DB-backed user
# stopword resolution here, since this script has no logged-in user.
STOPWORDS = {"\n"}


def run_comparison(text_body: str, db) -> None:
    segmenter = get_segmenter(db)

    dag = segmenter.build_dag(text_body, overlay=None, stopwords=STOPWORDS)
    best_guess = aggregate_segments(segmenter.segment(text_body, stopwords=STOPWORDS, dag=dag))
    full_segmentation = aggregate_full_segmentation(text_body, dag, STOPWORDS)

    print(f"\n{'=' * 60}")
    print(f"TEXT: {text_body}")
    print(f"{'=' * 60}")

    best_guess_words = [r.word for r in segmenter.segment(text_body, stopwords=STOPWORDS, dag=dag)]

    print(f"  Best guess:       {' / '.join(best_guess_words)}")
    print(f"  Full segmentation: {' / '.join(sorted(full_segmentation.keys()))}")

    best_guess_set, full_set = set(best_guess.keys()), set(full_segmentation.keys())
    only_best_guess = best_guess_set - full_set
    only_full = full_set - best_guess_set

    if only_best_guess or only_full:
        print("  --- differences ---")
        if only_best_guess:
            print(f"  only in best guess:        {sorted(only_best_guess)}")
        if only_full:
            print(f"  only in full segmentation: {sorted(only_full)}")
    else:
        print("  (identical word sets)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", action="append", help="Custom text to test (repeatable)")
    args = parser.parse_args()

    samples = args.text if args.text else DEFAULT_SAMPLES

    db = SessionLocal()
    try:
        for sample in samples:
            run_comparison(sample, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
