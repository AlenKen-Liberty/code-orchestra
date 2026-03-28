# Handoff: code -> e2e_test
## Task
Migrate hybrid-store to PostgreSQL

## Description
# Task: Migrate hybrid-store from ES+Qdrant to PostgreSQL

## Background

The `hybrid-store` library at `/home/ubuntu/scripts/hybrid-store/` currently uses:
- **Elasticsearch** for titles/metadata storage + BM25 full-text search
- **Qdrant Cloud** for vector semantic search (dense + sparse collections)

Both are being replaced by a **single Neon PostgreSQL** database with:
- **pgvector** (halfvec for float16 1024-dim vectors, HNSW index)
- **tsvector** + GIN index for BM25 full-text search
- **TOAST** auto-compression for full_text storage

## Neon PostgreSQL Connection

- **Project ID**: `quiet-king-84484226`
- **Region**: aws-us-east-1
- **PG Version**: 18.2
- **Extensions installed**: vector 0.8.1, pg_trgm 1.6, btree_gin 1.3

Connection string can be obtained via Neon MCP `get_connection_string` tool,
or from the project's `.env` file (to be created).

## Database Schema (already created)

### swimswam_articles
```sql
url             TEXT PRIMARY KEY
title           TEXT NOT NULL DEFAULT ''
author          TEXT
published_time  TIMESTAMPTZ
homepage_time   TIMESTAMPTZ
comment_count   INTEGER DEFAULT 0
full_text       TEXT                        -- TOAST auto-compressed
fts             TSVECTOR GENERATED ALWAYS AS (
                    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(full_text, '')), 'B')
                ) STORED
embedding       halfvec(1024)               -- float16 vector
fetch_status    TEXT NOT NULL DEFAULT 'pending'
processing_since TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

**Indexes**: GIN on fts, HNSW on embedding (halfvec_cosine_ops, m=16, ef=128),
partial btree on fetch_status='pending', btree on published_time DESC.

### reddit_posts
```sql
url             TEXT PRIMARY KEY
subreddit       TEXT NOT NULL
reddit_id       TEXT
title           TEXT NOT NULL DEFAULT ''
author          TEXT
author_karma    INTEGER
body            TEXT
score           INTEGER DEFAULT 0
num_comments    INTEGER DEFAULT 0
created_utc     TIMESTAMPTZ
flair           TEXT
is_self         BOOLEAN DEFAULT TRUE
interest_score  REAL
full_text       TEXT
fts             TSVECTOR GENERATED ALWAYS AS (
                    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(body, '')), 'B')
                ) STORED
embedding       halfvec(1024)
fetch_status    TEXT NOT NULL DEFAULT 'pending'
collected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

### reddit_comments
```sql
id              TEXT PRIMARY KEY
post_url        TEXT NOT NULL REFERENCES reddit_posts(url) ON DELETE CASCADE
author          TEXT
body            TEXT
score           INTEGER DEFAULT 0
created_utc     TIMESTAMPTZ
parent_id       TEXT
depth           INTEGER DEFAULT 0
collected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
```

## Current hybrid-store Code Structure

```
/home/ubuntu/scripts/hybrid-store/hybrid_store/
├── __init__.py
├── config.py        # HybridStoreConfig dataclass, load_config()
├── store.py         # HybridStore class - main API (ES + Qdrant operations)
├── embedder.py      # Ollama embedding client (qwen3-embedding:0.6b, 1024-dim)
└── sparse.py        # BM25 sparse vector tokenizer for Qdrant
```

### Key API methods to migrate (from store.py):
- `write_title(url, title, homepage_time, fetch_status, comment_count_hint)` → ES index
- `read_title(url)` → ES get by doc_id (SHA256 of normalized URL)
- `list_pending(limit)` → ES search where fetch_status='pending'
- `upsert_article(url, title, full_text, published_time, ...)` → ES + Qdrant (sparse + dense)
- `search_articles(query, top_k)` → Qdrant dense vector search
- `get_count(name)` → ES count
- `normalize_url(url)` / `url_id(url)` → URL normalization + SHA256 hash

### Callers:
1. **swimswam** (`/home/ubuntu/scripts/swimswam/`):
   - `sync_titles.py` - calls write_title/read_title for title sync
   - `fetch_articles.py` - calls list_pending + upsert_article for full content fetch
   - Uses `.env` for config: ES_INDEX_TITLES, QDRANT_URL, QDRANT_API_KEY, etc.

2. **grow-in-reddit** (`/home/ubuntu/scripts/grow-in-reddit/`):
   - `storage/qdrant_store.py` - direct Qdrant client for vector upsert/search
   - `storage/es_store.py` - direct ES client for full-text search
   - Has its own SQLite as primary store; ES/Qdrant are secondary

## What Needs to Be Done

### Phase 1: Design (Codex)
- Design the new `pg_store.py` module API that replaces both ES and Qdrant
- Design config changes (PostgreSQL connection string instead of ES+Qdrant)
- Design the migration path for callers (swimswam, grow-in-reddit)
- Consider: connection pooling, embedding float32→halfvec conversion,
  hybrid search (BM25 + vector with RRF), batch operations

### Phase 2: Implement (Gemini)
- Implement `pg_store.py` in hybrid-store with asyncpg or psycopg
- Update `config.py` to support PostgreSQL connection
- Update swimswam callers (sync_titles.py, fetch_articles.py)
- Update grow-in-reddit storage layer
- Remove ES and Qdrant dependencies

### Phase 3: E2E Test (Opus)
- Test write_title / read_title cycle
- Test upsert_article with full_text + embedding
- Test BM25 search (tsvector)
- Test vector search (halfvec cosine)
- Test hybrid search (BM25 + vector)
- Verify TOAST compression on large text
- Run swimswam sync_titles against live Neon DB

## Embedding Details
- Model: qwen3-embedding:0.6b via Ollama at http://127.0.0.1:11434
- Dimensions: 1024
- Storage: halfvec(1024) in PostgreSQL (float32 from Ollama → cast to float16)
- API: POST /api/embed {"model": "qwen3-embedding:0.6b", "input": ["text"]}


## Goal
hybrid-store uses single PostgreSQL (Neon) instead of ES+Qdrant. swimswam sync_titles works end-to-end.

## Context
- Complexity: complex
- Current Stage: e2e_test (e2e_tester)
- Working Directory: /home/ubuntu/scripts/hybrid-store

## Previous Stage Output
### plan
{"type":"thread.started","thread_id":"019d34ae-2552-7341-85b8-20e0aa40776f"} {"type":"turn.started"} {"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I’m treating this as the planning handoff for the PostgreSQL migration. I’ll inspect `hybrid-store...

### code
No summary recorded.

## Current Stage Instructions
Complete the `e2e_test` stage for this task in `/home/ubuntu/scripts/hybrid-store`.

## Verification
Run: `python3 -c "from hybrid_store import HybridStore"`
