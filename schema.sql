-- Memory Bridge - Supabase Database Schema
-- Single source of truth for the production hub model.
-- Run this first, then apply rls_production.sql.

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Users table (extends Supabase auth)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    username TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Memory collections (folders/categories)
CREATE TABLE IF NOT EXISTS public.collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Memories (hub model)
CREATE TABLE IF NOT EXISTS public.memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES public.collections(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    source TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    content_hash TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    source_preference TEXT,
    deleted_at TIMESTAMPTZ,
    content_plain TEXT,
    content_markdown TEXT,
    searchable tsvector,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT memories_status_check CHECK (status IN ('active', 'archived', 'deleted'))
);

-- Chunked embeddings
CREATE TABLE IF NOT EXISTS public.memory_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    memory_id UUID NOT NULL REFERENCES public.memories(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    token_estimate INTEGER,
    embedding vector(1536),
    embedding_model TEXT NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (memory_id, chunk_index, chunk_hash)
);

-- Sync identity and adapter state
CREATE TABLE IF NOT EXISTS public.sync_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    memory_id UUID NOT NULL REFERENCES public.memories(id) ON DELETE CASCADE,
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
    UNIQUE (user_id, provider, external_id)
);

-- Sync/event audit log
CREATE TABLE IF NOT EXISTS public.memory_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    memory_id UUID REFERENCES public.memories(id) ON DELETE CASCADE,
    sync_link_id UUID REFERENCES public.sync_links(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'created',
        'updated',
        'deleted',
        'synced',
        'conflict_detected',
        'conflict_resolved',
        'embedded',
        'search_indexed'
    )),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'system', 'agent', 'adapter')),
    actor_id TEXT,
    before_hash TEXT,
    after_hash TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Conflicts for multi-provider sync
CREATE TABLE IF NOT EXISTS public.sync_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    memory_id UUID NOT NULL REFERENCES public.memories(id) ON DELETE CASCADE,
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

-- Derived memories for agent-generated content
CREATE TABLE IF NOT EXISTS public.derived_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    parent_memory_id UUID REFERENCES public.memories(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('summary', 'insight', 'task', 'entity', 'reflection', 'extraction')),
    title TEXT,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    model_name TEXT,
    created_by_agent TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_collections_user_id ON public.collections(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_user_created ON public.memories(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_user_updated ON public.memories(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_collection_id ON public.memories(collection_id);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON public.memories USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_memories_metadata ON public.memories USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_memories_searchable ON public.memories USING GIN(searchable);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_memory ON public.memory_embeddings(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user_memory ON public.memory_embeddings(user_id, memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_vector
    ON public.memory_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_sync_links_memory ON public.sync_links(memory_id);
CREATE INDEX IF NOT EXISTS idx_sync_links_provider_external ON public.sync_links(user_id, provider, external_id);
CREATE INDEX IF NOT EXISTS idx_memory_events_memory ON public.memory_events(memory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_conflicts_memory ON public.sync_conflicts(memory_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_derived_memories_parent ON public.derived_memories(parent_memory_id);

-- Trigger helpers
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.update_memories_searchable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.content_plain := COALESCE(NEW.content_plain, NEW.content);
    NEW.content_markdown := COALESCE(NEW.content_markdown, NEW.content);
    NEW.searchable :=
        setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.content_plain, '')), 'B') ||
        setweight(to_tsvector('english', array_to_string(COALESCE(NEW.tags, '{}'), ' ')), 'C');
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON public.profiles;
CREATE TRIGGER trg_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_collections_updated_at ON public.collections;
CREATE TRIGGER trg_collections_updated_at
    BEFORE UPDATE ON public.collections
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_memories_updated_at ON public.memories;
CREATE TRIGGER trg_memories_updated_at
    BEFORE UPDATE ON public.memories
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_sync_links_updated_at ON public.sync_links;
CREATE TRIGGER trg_sync_links_updated_at
    BEFORE UPDATE ON public.sync_links
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_memories_searchable ON public.memories;
CREATE TRIGGER trg_memories_searchable
    BEFORE INSERT OR UPDATE ON public.memories
    FOR EACH ROW
    EXECUTE FUNCTION public.update_memories_searchable();

-- Function to create profile on user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    INSERT INTO public.profiles (id, email, username)
    VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data->>'username')
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- Full-text search
CREATE OR REPLACE FUNCTION public.search_memories_fts(
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
    FROM public.memories m
    WHERE m.user_id = p_user_id
      AND m.deleted_at IS NULL
      AND m.searchable @@ plainto_tsquery('english', p_query)
    ORDER BY rank DESC, m.updated_at DESC
    LIMIT p_limit;
$$;

-- Vector search over chunk embeddings
CREATE OR REPLACE FUNCTION public.search_memories_semantic(
    p_user_id UUID,
    p_embedding vector(1536),
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    memory_id UUID,
    chunk_text TEXT,
    similarity DOUBLE PRECISION,
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
    FROM public.memory_embeddings e
    JOIN public.memories m ON m.id = e.memory_id
    WHERE e.user_id = p_user_id
      AND m.deleted_at IS NULL
    ORDER BY e.embedding <=> p_embedding
    LIMIT p_limit;
$$;

-- Backward-compatible wrappers
CREATE OR REPLACE FUNCTION public.search_memories(
    search_query TEXT,
    search_limit INTEGER DEFAULT 10,
    filter_user_id UUID DEFAULT auth.uid()
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    content TEXT,
    rank REAL
)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        r.id,
        r.title,
        r.content,
        r.rank
    FROM public.search_memories_fts(filter_user_id, search_query, search_limit) AS r;
$$;

CREATE OR REPLACE FUNCTION public.match_memories(
    query_embedding vector(1536),
    match_count INTEGER DEFAULT 5,
    filter_user_id UUID DEFAULT auth.uid()
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    content TEXT,
    similarity DOUBLE PRECISION
)
LANGUAGE SQL
STABLE
AS $$
    SELECT
        m.id,
        m.title,
        m.content,
        MAX(1 - (e.embedding <=> query_embedding)) AS similarity
    FROM public.memory_embeddings e
    JOIN public.memories m ON m.id = e.memory_id
    WHERE e.user_id = filter_user_id
      AND m.deleted_at IS NULL
    GROUP BY m.id, m.title, m.content
    ORDER BY similarity DESC
    LIMIT match_count;
$$;
