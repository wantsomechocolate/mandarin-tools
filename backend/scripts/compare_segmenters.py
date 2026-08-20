"""
Runs both the longest-matching and DAG+DP segmenters against the real
dictionary/Postgres data on one or more sample passages, and prints a
side-by-side diff. Useful for eyeballing behavior differences on real
vocabulary before switching the main /analyze endpoint over.

Usage:
    uv run python scripts/compare_segmenters.py
    uv run python scripts/compare_segmenters.py --text "自定义的一句话"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.modules.known_words.segmentor import longest_matching
from app.modules.known_words.trie_loader import get_trie
from app.modules.known_words.segmenter_loader import get_segmenter
from app.modules.known_words.dag_segmentor import aggregate_segments


DEFAULT_SAMPLES = [
    "我来到北京清华大学",
    "他来到了网易杭研大厦",
    "研究生命起源是一个有趣的话题",
    "小明硕士毕业于中国科学院计算所",
]


def run_comparison(text_body: str, db) -> None:
    trie = get_trie(db)
    segmenter = get_segmenter(db)

    lm_result = longest_matching(text_body, trie, stopwords={"\n"})
    dag_result = aggregate_segments(segmenter.segment(text_body))

    print(f"\n{'=' * 60}")
    print(f"TEXT: {text_body}")
    print(f"{'=' * 60}")

    lm_words = list(lm_result.keys())
    dag_words = [r.word for r in segmenter.segment(text_body)]

    print(f"  Longest match: {' / '.join(lm_words)}")
    print(f"  DAG + DP:      {' / '.join(dag_words)}")

    lm_set, dag_set = set(lm_result.keys()), set(dag_result.keys())
    only_lm = lm_set - dag_set
    only_dag = dag_set - lm_set

    if only_lm or only_dag:
        print("  --- differences ---")
        if only_lm:
            print(f"  only in longest-match: {sorted(only_lm)}")
        if only_dag:
            print(f"  only in DAG+DP:        {sorted(only_dag)}")
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
