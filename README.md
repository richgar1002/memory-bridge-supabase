# 🧠 Memory Bridge - Supabase Edition

**Production-ready, multi-user memory system with Notion & Obsidian sync.**

---

## Features

### Core
- ✅ Collections (folders)
- ✅ Memories with metadata  
- ✅ Tags
- ✅ Full-text search
- ✅ User authentication

### Sync (Bi-directional)
- ✅ Obsidian → Supabase
- ✅ Notion → Supabase
- ✅ Supabase → Obsidian (manual)
- ✅ Supabase → Notion (manual)

### Security
- ✅ Row-level security (RLS)
- ✅ User isolation
- ✅ API key auth

---

## Quick Start

### 1. Create Supabase Project
1. Go to [supabase.com](https://supabase.com)
2. Create a new project
3. Run `schema.sql` in SQL Editor
4. Get your credentials

### 2. Install & Configure

```python
from client_complete import create_memory_client

client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key",
    user_id="your-user-id"
)
```

### 3. Use

```python
# Create memory
memory = client.create_memory(
    title="EURUSD Trade",
    content="Bearish divergence on 4H chart",
    tags=["forex", "trading"]
)

# Search
results = client.search("EURUSD")

# Get all
memories = client.get_memories()
```

---

## API

Run the API:
```bash
python api_complete.py
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/collections` | List collections |
| POST | `/collections` | Create collection |
| DELETE | `/collections/{id}` | Delete collection |
| GET | `/memories` | List memories |
| POST | `/memories` | Create memory |
| GET | `/memories/{id}` | Get memory |
| PUT | `/memories/{id}` | Update memory |
| DELETE | `/memories/{id}` | Delete memory |
| POST | `/search` | Search |
| POST | `/sync/obsidian` | Sync from Obsidian |
| POST | `/sync/notion` | Sync from Notion |
| GET | `/stats` | Statistics |

### Example

```bash
# Create memory
curl -X POST http://localhost:8003/memories \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test",
    "content": "Memory content"
  }'

# Search
curl -X POST http://localhost:8003/search \
  -H "Content-Type: application/json" \
  -d '{"query": "EURUSD", "limit": 10}'
```

---

## Sync Examples

### Obsidian → Supabase

```python
from client_complete import create_memory_client
from obsidian_sync import create_obsidian_sync

client = create_memory_client(url, key, user_id)
sync = create_obsidian_sync("/path/to/vault", client)
result = sync.sync_to_supabase()
```

### Notion → Supabase

```python
from notion_client import Client as NotionClient
from client_complete import create_memory_client

notion = NotionClient(auth="your-token")
notion.database_id = "your-db-id"

client = create_memory_client(url, key, user_id)
result = client.sync_from_notion(notion)
```

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Obsidian  │────▶│  Supabase   │◀────│   Notion   │
│   Vault    │     │ PostgreSQL  │     │   Pages    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                          │
                   ┌──────▼──────┐
                   │  REST API   │
                   │  Python SDK  │
                   └─────────────┘
```

---

## Files

| File | Description |
|------|-------------|
| `schema.sql` | Database schema |
| `client_complete.py` | Full Python client |
| `obsidian_sync.py` | Obsidian sync |
| `notion_sync.py` | Notion sync |
| `api_complete.py` | REST API |
| `embeddings.py` | Vector embeddings |

---

## Status

| Feature | Status |
|---------|---------|
| Create/Read memories | ✅ |
| Collections | ✅ |
| Tags | ✅ |
| Search | ✅ |
| Obsidian sync | ✅ |
| Notion sync | ✅ |
| Vector embeddings | 🔄 |
| REST API | ✅ |
| Production RLS | 🔄 |

---

**Note:** Run schema.sql in Supabase first. Get credentials from Settings → API.
