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

    affects_dag is tri-state (NULL/true/false - see UserWord's docstring,
    models.py) - a NULL means "no opinion at this scope," so the walk skips
    straight past it to the next broader scope, exactly as if that row
    didn't exist for this purpose (its own freq_combined is skipped right
    along with it - a row with no opinion on whether to affect segmentation
    has nothing to contribute to it either). This is distinct from "no row
    exists at this scope" only in that the row still exists for its other
    fields (pronunciation/meaning/notes, untouched by any of this); the
    *segmentation* outcome is identical either way. A text-scoped row with
    a non-NULL affects_dag still wins over a global row outright, false
    included, same as before this tri-state existed. Only when EVERY scope
    (text, global - analysis is already excluded above) has either no row
    or a NULL affects_dag does resolution fall back to a hardcoded `true`
    default - but with no row left to source a frequency from at that
    point, there's nothing to add to the overlay either, so this case is
    functionally identical to the word having no UserWord entry at all:
    segmentation falls through to the segmenter's own global dictionary
    frequency, same as build_user_overlay returning None entirely.

    A *resolved* affects_dag=false no longer means "excluded from the
    overlay" - add_word is now called unconditionally for every resolved
    row, passing affects_dag through. See UserOverlay.add_word's docstring
    (dag_segmentor.py) for what it does with that: the word still becomes a
    real trie candidate (so it always shows up as at least an extra match),
    it just doesn't get a competitive frequency, so it essentially never
    wins best-guess. This is the actual point of affects_dag=false - "don't
    let this drive segmentation" - not "pretend this word doesn't exist."
    """
    rows = db.execute(text("""
        SELECT word, freq_combined, scope_input_text_id, affects_dag FROM user_words
        WHERE user_id = :user_id
        AND scope_analysis_id IS NULL
        AND (scope_input_text_id IS NULL OR scope_input_text_id = :input_text_id)
    """), {"user_id": user_id, "input_text_id": input_text_id}).fetchall()

    if not rows:
        return None

    # Split into text-scoped vs. global candidates per word (priority
    # order: text, then global - analysis-scoped rows are already excluded
    # by the query above).
    text_scoped: dict[str, tuple[int | None, bool | None]] = {}
    global_scoped: dict[str, tuple[int | None, bool | None]] = {}
    for word, freq_combined, scope_input_text_id, affects_dag in rows:
        if scope_input_text_id is not None:
            text_scoped[word] = (freq_combined, affects_dag)
        else:
            global_scoped[word] = (freq_combined, affects_dag)

    overlay = UserOverlay()
    floor = segmenter.dominance_floor()
    any_added = False
    for word in set(text_scoped) | set(global_scoped):
        # Walk text -> global, skipping any row whose affects_dag is NULL -
        # "no opinion here, inherit from the next broader scope" (see
        # docstring above). The first non-NULL opinion found wins, along
        # with that same row's freq_combined.
        resolved = None
        for candidates in (text_scoped, global_scoped):
            if word in candidates and candidates[word][1] is not None:
                resolved = candidates[word]
                break
        if resolved is None:
            # No scope expressed an opinion anywhere - defaults to
            # affects_dag=true, but there's no row left to source a weight
            # from, so there's nothing to add (see docstring above).
            continue
        freq_combined, affects_dag = resolved
        # Called unconditionally, affects_dag included either way - see
        # UserOverlay.add_word's docstring for what it does with a false
        # opinion (floor scoring, not exclusion).
        overlay.add_word(word, freq_combined, dominance_floor=floor, affects_dag=bool(affects_dag))
        any_added = True
    # Keep the "None means nothing to add" contract honest - tracked via
    # `any_added` rather than `overlay.freq`, since an overlay containing
    # only affects_dag=false words is trie-only (add_word deliberately
    # skips self.freq for those - see its docstring) and so is NOT empty,
    # even though overlay.freq is. Checking overlay.freq here would
    # silently drop every affects_dag=false word from the overlay entirely,
    # undoing the whole point of the floor-based rewrite.
    return overlay if any_added else None
