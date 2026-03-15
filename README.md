# Memory Bridge - Supabase Edition

**Production-ready, multi-user memory system with Notion & Obsidian sync.**

---

## Features

### Core
- [x] Collections (folders)
- [x] Memories with metadata
- [x] Tags
- [x] Full-text search
- [x] User authentication

### Sync
- [x] Obsidian → Supabase
- [x] Notion → Supabase
- [x] Supabase → Obsidian (coming)
- [x] Supabase → Notion (coming)

### Security
- [x] Row-level security (RLS)
- [x] User isolation

---

## Quick Start

```python
from client_complete import create_memory_client

# Create client
client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key",
    user_id="your-user-id"
)

# Create memory
memory = client.create_memory(
    title="EURUSD Trade",
    content="Bearish divergence on 4H chart",
    tags=["forex", "trading"]
)

# Search
results = client.search("EURUSD")
```

## Obsidian Sync

```python
from client_complete import create_memory_client
from obsidian_sync import create_obsidian_sync

client = create_memory_client(url, key, user_id)

# Create sync
obsidian = create_obsidian_sync("/path/to/vault", client)

# Sync to Supabase
result = obsidian.sync_to_supabase()
print(f"Synced {result['synced']} notes")
```

## Notion Sync

```python
from notion_client import Client
from client_complete import create_memory_client

# Notion client
notion = Client(auth="your-notion-token")
notion.database_id = "your-database-id"

# Memory client
client = create_memory_client(url, key, user_id)

# Sync
result = client.sync_from_notion(notion)
print(f"Synced {result['synced']} pages")
```

## API

Run the API:
```bash
python api.py
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Obsidian  │────▶│  Supabase  │◀────│   Notion   │
│   Vault    │     │  (Postgres)│     │   Pages    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │   Search    │
                    │  + Vectors  │
                    └─────────────┘
```

## Status

| Feature | Status |
|---------|--------|
| Create/Read memories | ✅ |
| Collections | ✅ |
| Tags | ✅ |
| Search | ✅ |
| Obsidian sync | ✅ |
| Notion sync | ✅ |
| Vector embeddings | 🔄 |
| RLS | ✅ |

---

**Note:** You need to run the SQL schema in Supabase first.
