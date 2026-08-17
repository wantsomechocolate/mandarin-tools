import logging
from functools import lru_cache

from sqlalchemy.orm import Session

from app.modules.known_words.trie import Trie, build_trie

logger = logging.getLogger(__name__)

# Module-level cache — the trie is built once and reused
_trie_cache: Trie | None = None


def get_trie(db: Session) -> Trie:
    global _trie_cache
    if _trie_cache is None:
        _trie_cache = _build_trie_from_db(db)
    return _trie_cache


def invalidate_trie_cache() -> None:
    global _trie_cache
    _trie_cache = None


def _build_trie_from_db(db: Session) -> Trie:
    logger.info("Building trie from database...")
    
    from sqlalchemy import text
    result = db.execute(text("SELECT word FROM dictionary_words ORDER BY word"))
    words = [row[0] for row in result]
    
    logger.info(f"Loading {len(words):,} words into trie...")
    trie = build_trie(words)
    logger.info("Trie built successfully.")
    return trie