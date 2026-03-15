# Memory Bridge - Supabase Edition

**Production-ready, multi-user memory system with semantic search.**

---

## Features

### Core
- [x] Collections (folders)
- [x] Memories with metadata
- [x] Tags
- [x] Full-text search
- [x] Vector embeddings (semantic search)
- [x] Hybrid search (keywords + semantic)

### Security
- [x] Row-level security (RLS)
- [x] User isolation
- [x] API key auth

### Storage
- [x] PostgreSQL (Supabase)
- [x] pgvector for embeddings
- [x] Full-text search

## Setup

### 1. Supabase Setup
1. Create project at supabase.com
2. Run `schema.sql` in SQL Editor
3. Get credentials

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure
```python
from client import create_memory_client

client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key"
)
```

## Usage

### Create Memory
```python
memory = client.create_memory(
    title="EURUSD Trade",
    content="Bearish divergence on 4H chart",
    tags=["forex", "eurusd"],
    source="analysis"
)
```

### Search
```python
# Keyword search
results = client.search("EURUSD")

# Semantic search (requires embeddings)
# Coming soon
```

## API

Run the API:
```bash
python api.py
```

Endpoints:
- `GET /memories` - List memories
- `POST /memories` - Create memory
- `GET /memories/{id}` - Get memory
- `DELETE /memories/{id}` - Delete memory
- `POST /search` - Search
- `GET /collections` - List collections
- `POST /collections` - Create collection
- `GET /stats` - Get stats

## Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│   Supabase       │
│  PostgreSQL      │
│  + pgvector      │
└──────────────────┘
```

## Status

✅ Working - Basic CRUD
✅ Search - Full-text
🔄 Coming - Vector embeddings

---

**Note:** For vector/semantic search, you need Ollama running with an embedding model.
