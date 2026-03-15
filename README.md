# Supabase Memory Bridge

**Production-ready, multi-user memory system for AI agents.**

---

## Why Supabase?

| Feature | ChromaDB | Supabase |
|---------|----------|----------|
| **Authentication** | ❌ | ✅ Built-in |
| **Multi-user** | ❌ | ✅ RLS |
| **Vector search** | ✅ | ✅ pgvector |
| **Full-text search** | ❌ | ✅ PostgreSQL |
| **Keyword indexing** | ❌ | ✅ Automatic |
| **Production-ready** | ⚠️ | ✅ |
| **Cloud-hosted** | ❌ | ✅ |

## Features

### Security
- [x] User authentication
- [x] Row-level security (RLS)
- [x] Users can only see their own data
- [x] API key or JWT auth

### Search
- [x] Full-text search (PostgreSQL)
- [x] Vector similarity search (pgvector)
- [x] Hybrid search (both)

### Data
- [x] Collections (folders)
- [x] Tags
- [x] Metadata
- [x] Timestamps
- [x] Bulk import/export

## Setup

### 1. Create Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Create a new project
3. Get your:
   - Project URL
   - `anon` public key
   - `service_role` secret key (for admin)

### 2. Run Schema

Copy `schema.sql` into Supabase SQL Editor and run it.

### 3. Configure Client

```python
from client import create_memory_client

client = create_memory_client(
    supabase_url="https://your-project.supabase.co",
    supabase_key="your-anon-key"
)
```

## Usage

### Sign Up / Sign In

```python
# Sign up
client.sign_up("user@example.com", "password123")

# Sign in
client.sign_in("user@example.com", "password123")
```

### Collections

```python
# Create collection
collection = client.create_collection("Trading Notes")

# Get all collections
collections = client.get_collections()
```

### Memories

```python
# Create memory
memory = client.create_memory(
    title="EURUSD Trade",
    content="Opened buy position at 1.0850",
    tags=["forex", "eurusd"],
    source="trading"
)

# Get memories
memories = client.get_memories()
```

### Search

```python
# Full-text search
results = client.search_fulltext("EURUSD")

# Vector search (requires embeddings)
results = client.search_vector(embedding_array)

# Hybrid (best of both)
results = client.search_hybrid("EURUSD positions", embedding_array)
```

## API Server

```bash
# Run API
python api.py
```

Endpoints:
- `POST /auth/signup`
- `POST /auth/signin`
- `GET /collections`
- `POST /collections`
- `GET /memories`
- `POST /memories`
- `GET /memories/{id}`
- `PUT /memories/{id}`
- `DELETE /memories/{id}`
- `POST /search`

## Architecture

```
┌─────────────┐
│   Client    │
│  (Python)   │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│  Supabase   │────▶│  PostgreSQL │
│   (REST)    │     │  + pgvector │
└─────────────┘     └─────────────┘
```

## Pricing

| Tier | Price | Notes |
|------|-------|-------|
| **Free** | $0 | Up to 500MB |
| **Pro** | $25/mo | 10GB |
| **Enterprise** | Custom | Unlimited |

## Next Steps

- [ ] Add OpenAI embeddings
- [ ] Add Obsidian sync
- [ ] Add Notion sync
- [ ] Webhook support

---

Built for production. Built for privacy.
