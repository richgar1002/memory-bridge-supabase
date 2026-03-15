-- Memory Bridge - Production RLS
-- Enable Row-Level Security for production

-- Enable RLS on all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_embeddings ENABLE ROW LEVEL SECURITY;

-- Drop existing policies (if any)
DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users can view own collections" ON public.collections;
DROP POLICY IF EXISTS "Users can create collections" ON public.collections;
DROP POLICY IF EXISTS "Users can update own collections" ON public.collections;
DROP POLICY IF EXISTS "Users can delete own collections" ON public.collections;
DROP POLICY IF EXISTS "Users can view own memories" ON public.memories;
DROP POLICY IF EXISTS "Users can create memories" ON public.memories;
DROP POLICY IF EXISTS "Users can update own memories" ON public.memories;
DROP POLICY IF EXISTS "Users can delete own memories" ON public.memories;
DROP POLICY IF EXISTS "Users can view own embeddings" ON public.memory_embeddings;
DROP POLICY IF EXISTS "Users can create own embeddings" ON public.memory_embeddings;
DROP POLICY IF EXISTS "Users can delete own embeddings" ON public.memory_embeddings;

-- Profiles: users can only see/edit their own profile
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
        EXISTS (
            SELECT 1 FROM public.memories m 
            WHERE m.id = memory_embeddings.memory_id 
            AND m.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can create own embeddings" ON public.memory_embeddings
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.memories m 
            WHERE m.id = memory_embeddings.memory_id 
            AND m.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete own embeddings" ON public.memory_embeddings
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM public.memories m 
            WHERE m.id = memory_embeddings.memory_id 
            AND m.user_id = auth.uid()
        )
    );

-- Function to get current user ID (for use in API)
CREATE OR REPLACE FUNCTION public.get_current_user_id()
RETURNS UUID AS $$
BEGIN
    RETURN auth.uid();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function for search (allows user to search their own memories)
CREATE OR REPLACE FUNCTION public.search_user_memories(
    search_query TEXT,
    search_limit INT DEFAULT 10
)
RETURNS TABLE (
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
    WHERE m.user_id = auth.uid()
        AND m.searchable_text @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(m.searchable_text, plainto_tsquery('english', search_query)) DESC
    LIMIT search_limit;
END;
$$ LANGUAGE plpgsql;

-- Grant execute on search function
GRANT EXECUTE ON FUNCTION public.search_user_memories TO anon, authenticated, service_role;
