# 🧠 Memory Bridge - Production Edition

**Complete, production-ready memory system with bi-directional sync.**

---

## Features

### Core
- ✅ Collections (folders)
- ✅ Memories with metadata
- ✅ Tags
- ✅ Full-text search
- ✅ User authentication

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
- ✅ Error tracking

### Security
- ✅ Row-level security (RLS)
- ✅ User isolation
- ✅ API key auth

---

## Quick Start

```python
from client_production import create_memory_client, ClientConfig

# Configure client
config = ClientConfig(
    max_retries=3,
    retry_delay=2.0,
    verbose=True
)

client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key",
    user_id="user-id",
    config=config
)

# Create memory (with automatic retry)
memory = client.create_memory(
    title="EURUSD Trade",
    content="Bearish divergence on 4H"
)
```

## Error Handling

The client handles:

| Error Type | Handling |
|-----------|----------|
| Network timeout | Retry with backoff |
| Rate limited (429) | Wait and retry |
| Auth error | Raise AuthenticationError |
| Not found (404) | Raise NotFoundError |
| Other errors | Retry, then raise |

```python
from client_production import (
    create_memory_client,
    AuthenticationError,
    NotFoundError,
    ClientError
)

try:
    memory = client.create_memory(title="Test", content="Content")
except AuthenticationError:
    print("Check your credentials")
except NotFoundError:
    print("Resource not found")
except ClientError as e:
    print(f"Failed: {e}")
```

## Sync with Error Handling

### Obsidian Sync

```python
from obsidian_sync_production import create_obsidian_sync, SyncDirection

# Create sync with direction
sync = create_obsidian_sync(
    vault_path="/path/to/vault",
    memory_client=client,
    direction=SyncDirection.BIDIRECTIONAL
)

# Sync (returns detailed result)
result = sync.sync_bidirectional(force=False)

print(f"Status: {result.status}")
print(f"Synced: {result.synced}")
print(f"Failed: {result.failed}")
print(f"Errors: {result.errors}")
```

### Notion Sync

```python
from notion_sync_production import create_notion_sync, SyncDirection

sync = create_notion_sync(
    notion_client=notion,
    memory_client=client,
    direction=SyncDirection.BIDIRECTIONAL
)

result = sync.sync_bidirectional()

print(f"Status: {result.status}")
```

## API

Run the API:
```bash
python api_complete.py
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/memories` | Create memory |
| GET | `/memories` | List memories |
| GET | `/memories/{id}` | Get memory |
| PUT | `/memories/{id}` | Update memory |
| DELETE | `/memories/{id}` | Delete memory |
| POST | `/search` | Search |
| GET | `/collections` | List collections |
| POST | `/collections` | Create collection |
| DELETE | `/collections/{id}` | Delete collection |

## Files

| File | Description |
|------|-------------|
| `schema.sql` | Database schema |
| `rls_production.sql` | Production security |
| `client_production.py` | Client with error handling |
| `obsidian_sync_production.py` | Obsidian sync |
| `notion_sync_production.py` | Notion sync |
| `api_complete.py` | REST API |

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Obsidian  │────▶│  Supabase   │◀────│   Notion   │
│   Vault    │◀────│ PostgreSQL  │────▶│   Pages    │
└─────────────┘     └──────┬──────┘     └─────────────┘
                          │
                   ┌──────▼──────┐
                   │  API + SDK   │
                   │   + Errors  │
                   └─────────────┘
```

## Status

| Feature | Status |
|---------|--------|
| CRUD Operations | ✅ |
| Bi-directional Sync | ✅ |
| Error Handling | ✅ |
| Retry Logic | ✅ |
| Logging | ✅ |
| RLS | ✅ |
| Production Ready | ✅ |

---

**Note:** Run `schema.sql` first, then `rls_production.sql` for production.
