import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.known_words.dag_segmentor import Segmenter, UserOverlay
from app.modules.known_words.trie_loader import get_trie

logger = logging.getLogger(__name__)

# Module-level cache - built once and reused, same pattern as trie_loader.
_segmenter_cache: Segmenter | None = None


def get_segmenter(db: Session) -> Segmenter:
    global _segmenter_cache
    if _segmenter_cache is None:
        _segmenter_cache = _build_segmenter(db)
    return _segmenter_cache


def invalidate_segmenter_cache() -> None:
    global _segmenter_cache
    _segmenter_cache = None


def _build_segmenter(db: Session) -> Segmenter:
    logger.info("Building DAG segmenter from database...")

    trie = get_trie(db)

    result = db.execute(text(
        "SELECT word, frequency FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
    ))
    freq_dict = {row[0]: row[1] for row in result}

    logger.info(f"Loaded {len(freq_dict):,} word frequencies for DAG segmenter.")

    # Dictionary words with no usable frequency (NULL or 0) are excluded from
    # freq_dict above but remain reachable in the trie, so the DAG scan still
    # offers them as candidates - Segmenter._word_weight treats a trie hit
    # with no freq_dict entry as an unknown-floor score rather than dropping
    # the edge, so they can still be chosen if nothing better exists.
    segmenter = Segmenter(trie=trie, freq_dict=freq_dict)
    logger.info("DAG segmenter built successfully.")
    return segmenter


def build_user_overlay(user_id: int, db: Session, segmenter: Segmenter) -> UserOverlay | None:
    """
    Builds a per-user overlay from that user's UserWord entries. Returns None
    if the user has no custom words, so callers can skip overlay handling
    entirely on the common path.
    """
    rows = db.execute(text(
        "SELECT word, freq_combined FROM user_words WHERE user_id = :user_id"
    ), {"user_id": user_id}).fetchall()

    if not rows:
        return None

    overlay = UserOverlay()
    floor = segmenter.dominance_floor()
    for word, freq_combined in rows:
        overlay.add_word(word, freq_combined, dominance_floor=floor)
    return overlay
