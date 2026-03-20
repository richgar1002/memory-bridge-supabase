# Bridge Validation Test Plan

## Prerequisites
- Supabase project with schema.sql applied
- Obsidian vault with at least one note
- Notion integration token (if testing Notion)

## Test 1: Obsidian → Supabase

```python
from obsidian_sync_production import create_obsidian_sync
from client_production import create_memory_client

# Setup
client = create_memory_client(
    supabase_url="YOUR_URL",
    supabase_key="YOUR_KEY", 
    user_id="YOUR_USER_ID"
)

sync = create_obsidian_sync(
    vault_path="/path/to/vault",
    memory_client=client
)

# Run sync
result = sync.sync_to_supabase()

# Verify
# Check Supabase: memories table should have new entry
# Check Supabase: sync_links should have obsidian entry
```

## Test 2: Supabase → Obsidian (Round-trip)

```python
# Edit memory directly in Supabase dashboard, then:
result = sync.sync_from_supabase()

# Verify
# Check Obsidian vault: file should be updated
```

## Test 3: Bidirectional Conflict Detection

```python
# 1. Create note in Obsidian, sync to Supabase
result1 = sync.sync_to_supabase()

# 2. Edit the same note in Obsidian
# 3. Edit the same memory in Supabase dashboard
# 4. Run sync again

result2 = sync.sync_to_supabase()

# Verify
# Check Supabase: sync_conflicts table should have a row
# sync_links should show sync_state = 'conflicted'
```

## Test 4: Semantic Search with Chunks

```python
# After creating memories with content

# Get embeddings for a search query
from embeddings import get_embedding  # or use OpenAI

query_embedding = get_embedding("your search term")

# Search
results = client.semantic_search(query_embedding, limit=5)

# Verify
# Results should include chunk_text, similarity scores
# Should return chunk-level matches, not just note-level
```

## Expected Results

| Test | Expected Outcome |
|------|-----------------|
| 1 | Memory created in Supabase, sync_link created |
| 2 | File updated in Obsidian with Supabase changes |
| 3 | Conflict row in sync_conflicts, no silent overwrite |
| 4 | Chunk-level semantic results with similarity scores |

## Debug Queries

```sql
-- Check sync_links
SELECT * FROM sync_links WHERE provider = 'obsidian';

-- Check memory_events
SELECT * FROM memory_events ORDER BY created_at DESC LIMIT 20;

-- Check conflicts
SELECT * FROM sync_conflicts WHERE resolution_status = 'open';

-- Check chunk embeddings
SELECT memory_id, chunk_index, chunk_text, embedding IS NOT NULL as has_embedding 
FROM memory_embeddings LIMIT 10;
```
