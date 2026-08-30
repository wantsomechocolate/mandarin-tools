import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.known_words.dag_segmentor import (
    Segmenter,
    UserOverlay,
    DEFAULT_SUFFIX_DISCOUNTS,
    DEFAULT_PREFIX_DISCOUNTS,
)
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


def _load_affix_config(db: Session) -> tuple[dict[str, float], dict[str, float], set[str]]:
    """
    Merges the code-level DEFAULT_SUFFIX_DISCOUNTS/DEFAULT_PREFIX_DISCOUNTS
    (see dag_segmentor.py) with the segmentation_affixes table - a DB row for
    the same affix+position overrides the default's discount, a new affix
    not in the defaults gets added. See SegmentationAffix/SegmentationAffixExemption
    model docstrings for why this is system-wide config, not per-user.
    """
    suffixes = dict(DEFAULT_SUFFIX_DISCOUNTS)
    prefixes = dict(DEFAULT_PREFIX_DISCOUNTS)

    rows = db.execute(text("SELECT affix, position, discount FROM segmentation_affixes")).fetchall()
    for affix, position, discount in rows:
        if position == "suffix":
            suffixes[affix] = discount
        else:
            prefixes[affix] = discount

    exemptions = {row[0] for row in db.execute(text("SELECT word FROM segmentation_affix_exemptions"))}

    return suffixes, prefixes, exemptions


def _build_segmenter(db: Session) -> Segmenter:
    logger.info("Building DAG segmenter from database...")

    trie = get_trie(db)

    result = db.execute(text(
        "SELECT word, frequency FROM dictionary_words WHERE frequency IS NOT NULL AND frequency > 0"
    ))
    freq_dict = {row[0]: row[1] for row in result}

    logger.info(f"Loaded {len(freq_dict):,} word frequencies for DAG segmenter.")

    suffix_discounts, prefix_discounts, exemptions = _load_affix_config(db)
    logger.info(
        f"Loaded {len(suffix_discounts)} suffix / {len(prefix_discounts)} prefix "
        f"affix discounts, {len(exemptions)} exemptions."
    )

    # Dictionary words with no usable frequency (NULL or 0) are excluded from
    # freq_dict above but remain reachable in the trie, so the DAG scan still
    # offers them as candidates - Segmenter._word_weight treats a trie hit
    # with no freq_dict entry as an unknown-floor score rather than dropping
    # the edge, so they can still be chosen if nothing better exists.
    segmenter = Segmenter(
        trie=trie,
        freq_dict=freq_dict,
        suffix_discounts=suffix_discounts,
        prefix_discounts=prefix_discounts,
        exemptions=exemptions,
    )
    logger.info("DAG segmenter built successfully.")
    return segmenter


def build_user_overlay(
    user_id: int,
    db: Session,
    segmenter: Segmenter,
    input_text_id: int | None = None,
) -> UserOverlay | None:
    """
    Builds a per-user overlay from that user's UserWord entries. Returns None
    if the user has no matching custom words, so callers can skip overlay
    handling entirely on the common path.

    Scope resolution (see UserWord's scope_analysis_id/scope_input_text_id
    docstring): includes global entries plus any entry scoped to
    `input_text_id`, with the input-text-scoped entry winning over a global
    one for the same word. Deliberately never resolves *analysis*-scoped
    entries here, even though they exist as a concept - an analysis-scoped
    UserWord can only reference a past analysis (the one currently being
    analyzed, if this is mid-`/analyze`, has no id yet to have been scoped
    to), so there's nothing at the analysis level a fresh overlay build
    could ever match against. This is also the literal mechanism that keeps
    an analysis/text-scoped custom word from leaking into *other* texts'
    segmentation - callers simply don't pass its input_text_id.
    """
    rows = db.execute(text("""
        SELECT word, freq_combined, scope_input_text_id FROM user_words
        WHERE user_id = :user_id
        AND scope_analysis_id IS NULL
        AND (scope_input_text_id IS NULL OR scope_input_text_id = :input_text_id)
    """), {"user_id": user_id, "input_text_id": input_text_id}).fetchall()

    if not rows:
        return None

    # Resolve: an input-text-scoped entry wins over the global entry for the
    # same word (mirrors Fragment's resolution priority, one level down since
    # analysis-scoped entries are excluded above already).
    resolved: dict[str, int | None] = {}
    scoped_words: set[str] = set()
    for word, freq_combined, scope_input_text_id in rows:
        if scope_input_text_id is not None:
            resolved[word] = freq_combined
            scoped_words.add(word)
        elif word not in scoped_words:
            resolved[word] = freq_combined

    overlay = UserOverlay()
    floor = segmenter.dominance_floor()
    for word, freq_combined in resolved.items():
        overlay.add_word(word, freq_combined, dominance_floor=floor)
    return overlay
