# Mandarin Tools

A web application for analyzing simplified Chinese text to identify unknown vocabulary. Paste or submit Chinese text and get back a filtered word list based on your familiarity with each word — helping you focus on what you actually need to study.

## Features

- **Text analysis** — segments Chinese text into words using a longest-matching trie algorithm, plus a tokenizer that finds repeated unknown sequences not in the dictionary
- **Known word filtering** — mark words with a familiarity score (1–5); analyses automatically filter out words you already know well
- **Word details** — look up HSK level, pinyin, traditional form, meanings, and corpus frequency for any word
- **Garbage words** — flag junk tokens (proper nouns, artifacts, punctuation sequences) so they stop appearing in results
- **Saved analyses** — every analysis is saved and can be revisited; familiarity scores apply retroactively across all analyses
- **User accounts** — full authentication with JWT tokens; each user has their own known words, stopwords, and garbage words

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 17 |
| Package management | uv |
| Auth | python-jose (JWT), pwdlib + argon2 |
| Frontend | SvelteKit, TypeScript, Tailwind CSS v4 |
| Node | v26 LTS |

## Project Structure

```
mandarin-tools/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py         # Pydantic settings (reads from env vars)
│   │   │   ├── database.py       # SQLAlchemy engine, session, Base
│   │   │   └── auth.py           # JWT creation, password hashing, get_current_user
│   │   ├── models/
│   │   │   └── user.py           # User model
│   │   ├── modules/
│   │   │   ├── auth/             # Register, login endpoints
│   │   │   └── known_words/      # Core module
│   │   │       ├── models.py     # All known_words table definitions
│   │   │       ├── schemas.py    # Pydantic request/response schemas
│   │   │       ├── router.py     # API endpoints
│   │   │       ├── service.py    # Business logic, filtering
│   │   │       ├── trie.py       # Trie data structure
│   │   │       ├── trie_loader.py# Loads trie from DB, caches in memory
│   │   │       ├── segmentor.py  # Longest matching algorithm
│   │   │       └── tokenizer.py  # Repeated unknown sequence finder
│   │   └── main.py               # FastAPI app, routers, CORS, OpenAPI config
│   ├── migrations/               # Alembic migrations
│   ├── scripts/
│   │   ├── import_frequencies.py # Imports corpus frequency files
│   │   ├── import_hsk.py         # Imports HSK JSON vocabulary
│   │   └── build_dictionary.py   # Merges sources into dictionary_words
│   ├── assets/                   # Data files (git-ignored)
│   │   ├── frequencies/          # Corpus frequency .txt files
│   │   └── hsk/                  # complete.json HSK vocabulary
│   └── pyproject.toml
└── frontend/
    ├── src/
    │   ├── lib/
    │   │   ├── api.ts            # All backend API calls
    │   │   └── auth.ts           # Token storage, login/logout helpers
    │   └── routes/
    │       ├── +layout.svelte    # App shell, Tailwind import
    │       ├── +layout.ts        # SSR disabled (ssr = false)
    │       ├── +page.svelte      # Dashboard — saved analyses list
    │       ├── login/            # Login page
    │       ├── register/         # Registration page
    │       └── analyze/
    │           ├── +page.svelte  # Text input form
    │           └── [id]/
    │               └── +page.svelte  # Results page
    └── package.json
```

## Database Schema

| Table | Description |
|---|---|
| `users` | User accounts |
| `word_frequencies` | Per-corpus frequency counts (blog, literature, news, tech, weibo, combined, calc_combined, frequency) |
| `hsk_entries` | HSK vocabulary entries with level data for HSK 2012, 2021, and 2026 |
| `hsk_forms` | Per-form detail for HSK entries (traditional, pinyin, meanings, classifiers) |
| `dictionary_words` | Master word list merged from all sources; used to build the trie |
| `user_words` | User-added or user-overridden words |
| `known_words` | Per-user familiarity scores (1–5) for any word string |
| `stopwords` | Per-user stopwords for each algorithm; null user_id = system default |
| `garbage_words` | Words excluded from results; null user_id = system default; is_override to reinstate |
| `input_texts` | Saved text submissions |
| `analysis_results` | Cached shingle output per input text |

## Local Development Setup

### Prerequisites

- Python 3.12+
- Node.js 22+
- PostgreSQL 17
- uv (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`)

### 1. Database

Create a PostgreSQL database with UTF-8 encoding and C locale:

```sql
CREATE DATABASE mandarin_tools_dev
    WITH
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TEMPLATE = template0;
```

### 2. Environment Variables

Set the following as user environment variables (Windows) or in your shell profile:

```
MANDARIN_TOOLS_DB_HOST=localhost
MANDARIN_TOOLS_DB_PORT=5432
MANDARIN_TOOLS_DB_NAME=mandarin_tools_dev
MANDARIN_TOOLS_DB_USER=postgres
MANDARIN_TOOLS_DB_PASSWORD=yourpassword
MANDARIN_TOOLS_SECRET_KEY=your_long_random_secret_key
MANDARIN_TOOLS_DEBUG=True
```

Generate a secret key with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
```

### 4. Data Import

Place the following files in `backend/assets/`:

- `frequencies/blogs_wordfreq.release_UTF-8.txt`
- `frequencies/literature_wordfreq.release_UTF-8.txt`
- `frequencies/news_wordfreq.release_UTF-8.txt`
- `frequencies/technology_wordfreq.release_UTF-8.txt`
- `frequencies/weibo_wordfreq.release_UTF-8.txt`
- `frequencies/global_wordfreq.release_UTF-8.txt`
- `hsk/complete.json` (from [drkameleon/complete-hsk-vocabulary](https://github.com/drkameleon/complete-hsk-vocabulary))

Then run the import scripts in order:

```bash
uv run python scripts/import_frequencies.py
uv run python scripts/import_hsk.py
uv run python scripts/build_dictionary.py
```

This loads ~1.6M words from the frequency corpus and ~11,400 HSK vocabulary entries into the dictionary.

### 5. Start the Backend

```bash
cd backend
uv run uvicorn app.main:app --reload
```

API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 6. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

## How the Algorithms Work

### Longest Matching (Segmentation)

Starting at each character position in the input text, the algorithm traverses a trie of all known dictionary words to find the longest matching word. A `right_max` pointer prevents the same characters from being counted twice. Characters that don't lead to any dictionary word are collected into "unknown" runs. A set of stopwords (default: `\n`) resets the current segmentation.

### Tokenizer

Finds repeated sequences of characters that don't appear in the dictionary. All substrings up to a configurable max length are enumerated, then pruned: substrings already in the dictionary are removed, as are substrings that only ever appear as part of a longer substring with the same count, and substrings below a minimum count threshold. What remains are candidate "community words" — repeated patterns the dictionary doesn't know about.

### Result Filtering

After both algorithms run, results are merged (longest-matching takes priority for the same word), then filtered by:
- Garbage words (user-defined or system default)
- Non-Chinese character filter (toggleable, on by default)
- Familiarity score threshold (default: hide words scored 4 or 5)

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account |
| POST | `/auth/token` | Login, get JWT |
| POST | `/known-words/analyze` | Analyze text |
| GET | `/known-words/analyze/{id}` | Get saved analysis |
| GET | `/known-words/input-texts` | List saved texts |
| DELETE | `/known-words/input-texts/{id}` | Delete saved text |
| POST | `/known-words/known-words` | Set word familiarity |
| GET | `/known-words/known-words` | List known words |
| DELETE | `/known-words/known-words/{word}` | Remove known word |
| POST | `/known-words/user-words` | Add user word |
| GET | `/known-words/words/{word}` | Get word detail |
| GET | `/known-words/stopwords` | List stopwords |
| POST | `/known-words/stopwords` | Add stopword |
| DELETE | `/known-words/stopwords/{id}` | Remove stopword |
| GET | `/known-words/garbage-words` | List garbage words |
| POST | `/known-words/garbage-words` | Add garbage word |
| DELETE | `/known-words/garbage-words/{id}` | Remove garbage word |

## Roadmap

- Settings page (manage stopwords, garbage words, user words)
- Pleco flashcard export
- Auto-generated icons for saved texts
- Deployment to Hetzner VPS (FastAPI + SvelteKit behind Caddy)
- Community words (words added by enough users become shared vocabulary)
- Additional text input sources (audio transcription, image OCR, camera feed)
