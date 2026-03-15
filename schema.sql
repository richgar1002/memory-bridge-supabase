-- Memory Bridge - Supabase Database Schema
-- Run this in Supabase SQL Editor

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (extends Supabase auth)
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    username TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Memory collections (folders/categories)
CREATE TABLE public.collections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Memories (the actual content)
CREATE TABLE public.memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES public.collections(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    
    -- Metadata
    tags TEXT[],
    source TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- For full-text search
    searchable_text tsvector
);

-- Create indexes
CREATE INDEX memories_user_id_idx ON public.memories(user_id);
CREATE INDEX memories_collection_id_idx ON public.memories(collection_id);
CREATE INDEX memories_created_at_idx ON public.memories(created_at DESC);

-- Vector embeddings (using pgvector)
CREATE TABLE public.memory_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    memory_id UUID NOT NULL REFERENCES public.memories(id) ON DELETE CASCADE,
    embedding vector(1536),  -- OpenAI ada-002 dimension
    model TEXT DEFAULT 'text-embedding-ada-002',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX memory_embeddings_memory_id_idx ON public.memory_embeddings(memory_id);

-- Full-text search index
CREATE INDEX memories_search_idx ON public.memories USING GIN(searchable_text);

-- Triggers for automatic timestamps
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER collections_updated_at
    BEFORE UPDATE ON public.collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER memories_updated_at
    BEFORE UPDATE ON public.memories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Function to update searchable text
CREATE OR REPLACE FUNCTION update_searchable_text()
RETURNS TRIGGER AS $$
BEGIN
    NEW.searchable_text := to_tsvector('english', COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER memories_searchable
    BEFORE INSERT OR UPDATE ON public.memories
    FOR EACH ROW EXECUTE FUNCTION update_searchable_text();

-- Function to create profile on user signup
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.profiles (id, email, username)
    VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data->>'username');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- Row Level Security (RLS)
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_embeddings ENABLE ROW LEVEL SECURITY;

-- Profiles: users can only see their own profile
CREATE POLICY "Users can view own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);

-- Collections: users can only see their own collections
CREATE POLICY "Users can view own collections" ON public.collections
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can create collections" ON public.collections
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own collections" ON public.collections
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own collections" ON public.collections
    FOR DELETE USING (auth.uid() = user_id);

-- Memories: users can only see their own memories
CREATE POLICY "Users can view own memories" ON public.memories
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can create memories" ON public.memories
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own memories" ON public.memories
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own memories" ON public.memories
    FOR DELETE USING (auth.uid() = user_id);

-- Embeddings: users can only see their own
CREATE POLICY "Users can view own embeddings" ON public.memory_embeddings
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.memories m WHERE m.id = memory_id AND m.user_id = auth.uid())
    );

CREATE POLICY "Users can create own embeddings" ON public.memory_embeddings
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM public.memories m WHERE m.id = memory_id AND m.user_id = auth.uid())
    );

CREATE POLICY "Users can delete own embeddings" ON public.memory_embeddings
    FOR DELETE USING (
        EXISTS (SELECT 1 FROM public.memories m WHERE m.id = memory_id AND m.user_id = auth.uid())
    );

-- Function for semantic search (vector similarity)
CREATE OR REPLACE FUNCTION match_memories(
    query_embedding vector(1536),
    match_count INT DEFAULT 5,
    filter_user_id UUID DEFAULT auth.uid()
) RETURNS TABLE (
    id UUID,
    title TEXT,
    content TEXT,
    similarity float
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.title,
        m.content,
        1 - (e.embedding <=> query_embedding) AS similarity
    FROM public.memory_embeddings e
    JOIN public.memories m ON m.id = e.memory_id
    WHERE m.user_id = filter_user_id
    ORDER BY e.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Function for full-text search
CREATE OR REPLACE FUNCTION search_memories(
    search_query TEXT,
    search_limit INT DEFAULT 10,
    filter_user_id UUID DEFAULT auth.uid()
) RETURNS TABLE (
    id UUID,
    title TEXT,
    content TEXT,
    rank float
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.title,
        m.content,
        ts_rank(m.searchable_text, plainto_tsquery('english', search_query)) AS rank
    FROM public.memories m
    WHERE m.user_id = filter_user_id
        AND m.searchable_text @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(m.searchable_text, plainto_tsquery('english', search_query)) DESC
    LIMIT search_limit;
END;
$$ LANGUAGE plpgsql;
