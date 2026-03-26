# 🧠 Memory Bridge - Production Edition

**Complete, production-ready memory system with bi-directional sync.**

---

## Features

### Core
- ✅ Collections (folders)
- ✅ Memories with metadata
- ✅ Tags
- ✅ Full-text search (PostgreSQL FTS)
- ✅ Semantic search (vector embeddings)
- ✅ User authentication (JWT)

### Sync (Bi-directional)
- ✅ Obsidian ↔ Supabase
- ✅ Notion ↔ Supabase
- ✅ Conflict detection
- ✅ Content hash tracking

### Error Handling
- ✅ Automatic retry with backoff
- ✅ Rate limit handling
- ✅ Authentication errors
- ✅ Comprehensive logging

### Security
- ✅ Row-level security (RLS)
- ✅ User isolation
- ✅ JWT Bearer token authentication

---

## Installation

```bash
# Clone the repository
git clone https://github.com/richgar1002/memory-bridge-supabase.git
cd memory-bridge-supabase

# Install dependencies
pip install -e .

# Or for development
pip install -e ".[dev]"
```

---

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
OLLAMA_URL=http://localhost:11434  # optional
```

---

## Quick Start

### Python Client

```python
from client import create_memory_client, ClientConfig

config = ClientConfig(max_retries=3, retry_delay=2.0)
client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key",
    user_id="user-id",
    config=config
)

# Create memory
memory = client.create_memory(
    title="EURUSD Trade",
    content="Bearish divergence on 4H"
)

# Search
results = client.search("EURUSD")
```

### API Server

```bash
# Set environment variables first
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_SERVICE_KEY=your-key

# Run server
python api.py
# or
uvicorn api:app --reload
```

### API Authentication

```bash
# Login to get JWT token
curl -X POST http://localhost:8003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password"}'

# Use token in requests
curl http://localhost:8003/memories \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## Sync

### Obsidian Sync

```python
from obsidian_sync import create_obsidian_sync, SyncDirection

sync = create_obsidian_sync(
    vault_path="/path/to/vault",
    memory_client=client,
    direction=SyncDirection.BIDIRECTIONAL
)

result = sync.sync_bidirectional()
print(f"Status: {result.status}")
print(f"Synced: {result.synced}")
```

### Notion Sync

```python
from notion_sync import create_notion_sync, SyncDirection

sync = create_notion_sync(
    notion_client=notion,
    memory_client=client,
    direction=SyncDirection.BIDIRECTIONAL
)

result = sync.sync_bidirectional()
print(f"Status: {result.status}")
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Login |
| POST | `/auth/signup` | Register |
| GET | `/collections` | List collections |
| POST | `/collections` | Create collection |
| DELETE | `/collections/{id}` | Delete collection |
| GET | `/memories` | List memories |
| POST | `/memories` | Create memory |
| GET | `/memories/{id}` | Get memory |
| PUT | `/memories/{id}` | Update memory |
| DELETE | `/memories/{id}` | Delete memory |
| POST | `/search` | Full-text search |
| POST | `/sync/obsidian` | Sync Obsidian |
| POST | `/sync/notion` | Sync Notion |
| GET | `/stats` | Get statistics |
| GET | `/health` | Health check |

---

## Project Structure

```
memory-bridge-supabase/
├── api.py              # FastAPI REST API
├── client.py           # Memory client SDK
├── obsidian_sync.py    # Obsidian sync adapter
├── notion_sync.py      # Notion sync adapter
├── embeddings.py       # Vector embeddings
├── schema.sql          # Database schema
├── rls_production.sql # Row-level security
├── pyproject.toml      # Dependencies
├── tests/              # Test suite
└── .github/workflows/  # CI/CD
```

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Type check
mypy .
```

---

## Database Setup

1. Run `schema.sql` in Supabase SQL Editor
2. Run `rls_production.sql` for production security

---

## Status

| Feature | Status |
|---------|--------|
| CRUD Operations | ✅ |
| Bi-directional Sync | ✅ |
| Error Handling | ✅ |
| Retry Logic | ✅ |
| JWT Auth | ✅ |
| PostgreSQL FTS | ✅ |
| CI/CD | ✅ |
| Test Suite | ✅ |
