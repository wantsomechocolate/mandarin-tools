"""
One-time setup step (like import_frequencies.py/build_dictionary.py) - not
run automatically, not run on every deploy. Converts Helsinki-NLP/opus-mt-zh-en
to CTranslate2's int8-quantized format for the local fallback translation
provider (app/modules/known_words/enrichment.py) and downloads its
source/target sentencepiece models alongside it - together these are
everything enrichment.py needs to run translations, with NO torch/transformers
dependency at app runtime (see this project's translation-module planning
conversation for why that split matters: Argos Translate turned out to
still depend on torch transitively via stanza, which is exactly what this
setup avoids - ctranslate2 itself needs only numpy + pyyaml at runtime).

torch + transformers ARE needed for this one-time conversion (they're what
loads the original PyTorch checkpoint before re-serializing it) - kept out
of this project's own pyproject.toml/uv.lock entirely via uv's ephemeral
--with flags below, so they never become a real dependency of the app,
only of this one setup command.

Writes to backend/assets/translation_model/ (gitignored, like
assets/frequencies and assets/hsk - a prepared/downloaded artifact, not
source-controlled). Safe to re-run - overwrites in place.

Usage:
    uv run --with ctranslate2 --with transformers --with torch --with sentencepiece --with sacremoses \
        python scripts/prepare_translation_model.py
"""
from pathlib import Path

MODEL_NAME = "Helsinki-NLP/opus-mt-zh-en"
OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "translation_model"


def main():
    import ctranslate2.converters
    from huggingface_hub import hf_hub_download

    print(f"Downloading + converting {MODEL_NAME} (cached by huggingface_hub after first run)...")
    converter = ctranslate2.converters.TransformersConverter(MODEL_NAME)
    converter.convert(str(OUTPUT_DIR), quantization="int8", force=True)

    # enrichment.py tokenizes with sentencepiece directly (no transformers
    # dependency at runtime - see this script's own docstring) using these
    # same two files the original checkpoint ships.
    for filename in ("source.spm", "target.spm"):
        downloaded_path = Path(hf_hub_download(MODEL_NAME, filename))
        target_path = OUTPUT_DIR / filename
        target_path.write_bytes(downloaded_path.read_bytes())

    size_mb = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file()) / (1024 * 1024)
    print(f"Model + tokenizers written to {OUTPUT_DIR} ({size_mb:.1f} MB on disk).")
    print("app/modules/known_words/enrichment.py will load from this path automatically.")


if __name__ == "__main__":
    main()
