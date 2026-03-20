-- ============================================
-- Memory Bridge Hub Migration v2
-- Adds sync identity, conflict tracking, events,
-- and chunked embeddings for Supabase hub model.
-- ============================================

-- Required extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------
-- 1. Upgrade memories table
-- ----------------------------------------------
ALTER TABLE memories
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  ADD COLUMN IF NOT EXISTS content_hash TEXT,
  ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS source_preference TEXT,
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS content_plain TEXT,
  ADD COLUMN IF NOT EXISTS content_markdown TEXT;

-- Backfill content_plain if useful
UPDATE memories
SET content_plain = COALESCE(content_plain, content)
WHERE content_plain IS NULL;

-- Search vector (upgrade from searchable_text to searchable)
ALTER TABLE memories
  ADD COLUMN IF NOT EXISTS searchable tsvector;

-- Update searchable trigger function
CREATE OR REPLACE FUNCTION update_memories_searchable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.content_plain := COALESCE(NEW.content_plain, NEW.content);
  NEW.searchable :=
    setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(NEW.content_plain, '')), 'B') ||
    setweight(to_tsvector('english', array_to_string(COALESCE(NEW.tags, '{}'), ' ')), 'C');
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_memories_searchable ON memories;
CREATE TRIGGER trg_memories_searchable
BEFORE INSERT OR UPDATE ON memories
FOR EACH ROW
EXECUTE FUNCTION update_memories_searchable();

-- Indexes
DROP INDEX IF EXISTS idx_memories_user_updated;
CREATE INDEX IF NOT EXISTS idx_memories_user_updated
  ON memories(user_id, updated_at DESC);

DROP INDEX IF EXISTS idx_memories_tags;
CREATE INDEX IF NOT EXISTS idx_memories_tags
  ON memories USING gin(tags);

DROP INDEX IF EXISTS idx_memories_metadata;
CREATE INDEX IF NOT EXISTS idx_memories_metadata
  ON memories USING gin(metadata);

DROP INDEX IF EXISTS idx_memories_searchable;
CREATE INDEX IF NOT EXISTS idx_memories_searchable
  ON memories USING gin(searchable);

-- ----------------------------------------------
-- 2. Sync links table
-- ----------------------------------------------
CREATE TABLE IF NOT EXISTS sync_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  provider TEXT NOT NULL CHECK (provider IN ('obsidian', 'notion')),
  external_id TEXT NOT NULL,
  external_path TEXT,
  external_parent_id TEXT,
  external_url TEXT,
  remote_revision TEXT,
  remote_updated_at TIMESTAMPTZ,
  last_synced_hash TEXT,
  last_synced_revision INTEGER,
  last_synced_at TIMESTAMPTZ,
  sync_state TEXT NOT NULL DEFAULT 'linked'
    CHECK (sync_state IN ('linked', 'pending', 'conflicted', 'orphaned', 'disabled')),
  adapter_metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, provider, external_id)
);

CREATE INDEX IF NOT EXISTS idx_sync_links_memory
  ON sync_links(memory_id);

CREATE INDEX IF NOT EXISTS idx_sync_links_provider_external
  ON sync_links(user_id, provider, external_id);

-- ----------------------------------------------
-- 3. Memory events table
-- ----------------------------------------------
CREATE TABLE IF NOT EXISTS memory_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  memory_id UUID REFERENCES memories(id) ON DELETE CASCADE,
  sync_link_id UUID REFERENCES sync_links(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL
    CHECK (event_type IN (
      'created',
      'updated',
      'deleted',
      'synced',
      'conflict_detected',
      'conflict_resolved',
      'embedded',
      'search_indexed'
    )),
  actor_type TEXT NOT NULL
    CHECK (actor_type IN ('user', 'system', 'agent', 'adapter')),
  actor_id TEXT,
  before_hash TEXT,
  after_hash TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_events_memory
  ON memory_events(memory_id, created_at DESC);

-- ----------------------------------------------
-- 4. Sync conflicts table
-- ----------------------------------------------
CREATE TABLE IF NOT EXISTS sync_conflicts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  provider_a TEXT NOT NULL,
  provider_b TEXT NOT NULL,
  hash_a TEXT,
  hash_b TEXT,
  title_a TEXT,
  title_b TEXT,
  content_a TEXT,
  content_b TEXT,
  resolution_status TEXT NOT NULL DEFAULT 'open'
    CHECK (resolution_status IN ('open', 'resolved', 'ignored')),
  resolution_strategy TEXT
    CHECK (resolution_strategy IN ('manual', 'source_won', 'merged', 'llm_suggested')),
  resolved_content TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sync_conflicts_memory
  ON sync_conflicts(memory_id, created_at DESC);

-- ----------------------------------------------
-- 5. Replace/upgrade embeddings table
-- ----------------------------------------------
-- Rename old embeddings table if it exists
ALTER TABLE IF EXISTS memory_embeddings RENAME TO memory_embeddings_v1;

-- Create new chunked embeddings table
CREATE TABLE IF NOT EXISTS memory_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT NOT NULL,
  chunk_hash TEXT NOT NULL,
  token_estimate INTEGER,
  embedding vector(1536),
  embedding_model TEXT NOT NULL,
  embedded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  UNIQUE(memory_id, chunk_index, chunk_hash)
);

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_memory
  ON memory_embeddings(memory_id);

-- Vector search index (IVFFlat for approximate search)
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_vector
  ON memory_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- ----------------------------------------------
-- 6. Derived memories for agent-generated content
-- ----------------------------------------------
CREATE TABLE IF NOT EXISTS derived_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  parent_memory_id UUID REFERENCES memories(id) ON DELETE CASCADE,
  kind TEXT NOT NULL
    CHECK (kind IN ('summary', 'insight', 'task', 'entity', 'reflection', 'extraction')),
  title TEXT,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  model_name TEXT,
  created_by_agent TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_derived_memories_parent
  ON derived_memories(parent_memory_id);

-- ----------------------------------------------
-- 7. Updated timestamps helper
-- ----------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sync_links_updated_at ON sync_links;
CREATE TRIGGER trg_sync_links_updated_at
BEFORE UPDATE ON sync_links
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- ----------------------------------------------
-- 8. Full-text search function
-- ----------------------------------------------
CREATE OR REPLACE FUNCTION search_memories_fts(
  p_user_id UUID,
  p_query TEXT,
  p_limit INTEGER DEFAULT 20
)
RETURNS TABLE (
  id UUID,
  title TEXT,
  content TEXT,
  rank REAL,
  updated_at TIMESTAMPTZ
)
LANGUAGE SQL
STABLE
AS $$
  SELECT
    m.id,
    m.title,
    m.content,
    ts_rank(m.searchable, plainto_tsquery('english', p_query)) AS rank,
    m.updated_at
  FROM memories m
  WHERE m.user_id = p_user_id
    AND m.deleted_at IS NULL
    AND m.searchable @@ plainto_tsquery('english', p_query)
  ORDER BY rank DESC, m.updated_at DESC
  LIMIT p_limit;
$$;

-- ----------------------------------------------
-- 9. Vector search function
-- ----------------------------------------------
CREATE OR REPLACE FUNCTION search_memories_semantic(
  p_user_id UUID,
  p_embedding vector(1536),
  p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
  memory_id UUID,
  chunk_text TEXT,
  similarity FLOAT,
  title TEXT,
  updated_at TIMESTAMPTZ
)
LANGUAGE SQL
STABLE
AS $$
  SELECT
    e.memory_id,
    e.chunk_text,
    1 - (e.embedding <=> p_embedding) AS similarity,
    m.title,
    m.updated_at
  FROM memory_embeddings e
  JOIN memories m ON m.id = e.memory_id
  WHERE e.user_id = p_user_id
    AND m.deleted_at IS NULL
  ORDER BY e.embedding <=> p_embedding
  LIMIT p_limit;
$$;
