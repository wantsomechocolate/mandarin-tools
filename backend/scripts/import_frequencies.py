import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from app.core.config import settings


FREQUENCIES_DIR = Path(__file__).parent.parent / "assets" / "frequencies"

CORPUS_FILES = {
    "blog": "blogs_wordfreq.release_UTF-8.txt",
    "literature": "literature_wordfreq.release_UTF-8.txt",
    "news": "news_wordfreq.release_UTF-8.txt",
    "tech": "technology_wordfreq.release_UTF-8.txt",
    "weibo": "weibo_wordfreq.release_UTF-8.txt",
    "combined": "global_wordfreq.release_UTF-8.txt",
}


def import_frequencies():
    db_url = settings.database_url
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    conn.set_client_encoding('UTF8') 
    conn.autocommit = False

    try:
        for corpus, filename in CORPUS_FILES.items():
            filepath = FREQUENCIES_DIR / filename
            if not filepath.exists():
                print(f"Skipping {corpus}: file not found at {filepath}")
                continue

            print(f"Importing {corpus} from {filename}...")
            cursor = conn.cursor()

            cursor.execute(f"""
                CREATE TEMP TABLE IF NOT EXISTS tmp_freq (
                    word TEXT,
                    freq BIGINT
                )
            """)
            cursor.execute("TRUNCATE tmp_freq")

            with open(filepath, "r", encoding="utf-8") as f:
                cursor.copy_expert(
                    "COPY tmp_freq (word, freq) FROM STDIN WITH (FORMAT text, DELIMITER E'\\t')",
                    f
                )

            cursor.execute(f"""
                INSERT INTO word_frequencies (word, {corpus})
                SELECT word, SUM(freq) FROM tmp_freq
                GROUP BY word
                ON CONFLICT (word) DO UPDATE SET {corpus} = EXCLUDED.{corpus}
            """)

            conn.commit()
            print(f"  {corpus} done.")


            print("Calculating combined frequencies...")
            cursor.execute("""
                UPDATE word_frequencies
                SET calc_combined = COALESCE(blog, 0) + 
                                    COALESCE(literature, 0) + 
                                    COALESCE(news, 0) + 
                                    COALESCE(tech, 0) + 
                                    COALESCE(weibo, 0)
            """)
            cursor.execute("""
                UPDATE word_frequencies
                SET frequency = COALESCE(combined, calc_combined)
            """)
            conn.commit()
            print("  Frequency calculation done.")


        print("All frequency files imported successfully.")

    except Exception as e:
        print(f"Error during import: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import_frequencies()