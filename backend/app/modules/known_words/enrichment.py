"""
Machine-generated pinyin/translation for words with no dictionary entry -
see WordEnrichment's docstring (models.py) for the storage shape and why
it's shared across every user, and this feature's own planning conversation
for the full design (Google Translate, phase 2, is deliberately not built
yet - see generate_google_translation's absence here).

Two independent generators, each with its own module-level cache mirroring
trie_loader.py/segmenter_loader.py's existing "build once, reuse" pattern:

- generate_pinyin: pypinyin, pure Python, no cache needed (nothing to load).
- generate_ctranslate2_translation: a local CTranslate2 model (see
  scripts/prepare_translation_model.py - the model itself is a prepared/
  downloaded asset, not committed to the repo, same as assets/frequencies).
  Deliberately imports neither torch nor transformers - ctranslate2's own
  runtime dependencies are just numpy + pyyaml. Loaded lazily (first call,
  not at app startup) since translation is a minority-path feature, not
  something every request needs.
"""
import logging
from pathlib import Path

from pypinyin import Style, pinyin as pypinyin_pinyin

logger = logging.getLogger(__name__)

# Bump this whenever the model backing generate_ctranslate2_translation
# changes (a different base model, requantized, retrained, etc.) - compared
# against WordEnrichment.ctranslate2_model_version at read time
# (service.py) to decide staleness. Deliberately NOT tied to the model
# file's own timestamp or hash - this is a value *this code* controls, so a
# stale-marking only ever happens when a developer deliberately decides the
# old translations should be reconsidered, not on every incidental
# re-download of the same model.
CURRENT_CTRANSLATE2_MODEL_VERSION = "opus-mt-zh-en-int8-v1"

_MODEL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "translation_model"

_translator_cache = None
_sp_source_cache = None
_sp_target_cache = None


def generate_pinyin(word: str) -> str:
    """
    Space-separated, tone-diacritic pinyin (e.g. "sēn lín") - matches
    cedict_entries.pinyin's own format exactly, so the two are visually
    interchangeable wherever pinyin is displayed regardless of source.
    """
    syllables = pypinyin_pinyin(word, style=Style.TONE)
    return " ".join(s[0] for s in syllables)


def _load_ctranslate2():
    global _translator_cache, _sp_source_cache, _sp_target_cache
    if _translator_cache is not None:
        return _translator_cache, _sp_source_cache, _sp_target_cache

    if not _MODEL_DIR.exists():
        raise RuntimeError(
            f"Translation model not found at {_MODEL_DIR} - run "
            "scripts/prepare_translation_model.py once to download and convert it."
        )

    import ctranslate2
    import sentencepiece as spm

    logger.info(f"Loading CTranslate2 translation model from {_MODEL_DIR}...")
    _translator_cache = ctranslate2.Translator(str(_MODEL_DIR), device="cpu")
    _sp_source_cache = spm.SentencePieceProcessor(model_file=str(_MODEL_DIR / "source.spm"))
    _sp_target_cache = spm.SentencePieceProcessor(model_file=str(_MODEL_DIR / "target.spm"))
    logger.info("CTranslate2 translation model loaded.")
    return _translator_cache, _sp_source_cache, _sp_target_cache


def generate_ctranslate2_translation(word: str) -> str:
    """
    A single word/short phrase's English translation via the local
    opus-mt-zh-en model. beam_size/max_decoding_length/repetition_penalty/
    no_repeat_ngram_size aren't defaults picked lightly - a first pass with
    none of these set (plain greedy decoding, no explicit end token on the
    source sequence) produced runaway repetition on every short input
    ("Forests forest forest forest..." x200+) during this feature's own
    proof-of-concept testing. The "</s>" appended below is likewise not
    optional - raw sentencepiece encoding doesn't add it automatically the
    way transformers' MarianTokenizer does, and without it the model has no
    signal for where the source sequence actually ends.
    """
    translator, sp_source, sp_target = _load_ctranslate2()
    source_tokens = sp_source.encode(word, out_type=str) + ["</s>"]
    result = translator.translate_batch(
        [source_tokens],
        beam_size=4,
        max_decoding_length=30,
        repetition_penalty=1.3,
        no_repeat_ngram_size=3,
    )
    target_tokens = result[0].hypotheses[0]
    return sp_target.decode(target_tokens)
