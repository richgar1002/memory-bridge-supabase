"""
Memory Bridge - Supabase Client
Multi-user, secure, production-ready
"""
from supabase import create_client, Client
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Memory:
    """Represents a memory"""
    id: str
    user_id: str
    title: str
    content: str
    tags: List[str] = None
    source: str = None
    collection_id: str = None
    created_at: datetime = None
    updated_at: datetime = None

@dataclass
class Collection:
    """Represents a collection/folder"""
    id: str
    user_id: str
    name: str
    description: str = None
    created_at: datetime = None

class SupabaseMemoryClient:
    """Production-ready memory client with auth"""
    
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase: Client = create_client(supabase_url, supabase_key)
    
    # --- Authentication ---
    
    def sign_up(self, email: str, password: str):
        """Sign up a new user"""
        return self.supabase.auth.sign_up({"email": email, "password": password})
    
    def sign_in(self, email: str, password: str):
        """Sign in existing user"""
        return self.supabase.auth.sign_in({"email": email, "password": password})
    
    def sign_out(self):
        """Sign out current user"""
        return self.supabase.auth.sign_out()
    
    def get_current_user(self):
        """Get current authenticated user"""
        return self.supabase.auth.get_user()
    
    # --- Collections ---
    
    def create_collection(self, name: str, description: str = None) -> Collection:
        """Create a new collection"""
        response = self.supabase.table("collections").insert({
            "name": name,
            "description": description
        }).execute()
        
        return Collection(**response.data[0])
    
    def get_collections(self) -> List[Collection]:
        """Get all collections for current user"""
        response = self.supabase.table("collections").select("*").execute()
        return [Collection(**r) for r in response.data]
    
    def get_collection(self, collection_id: str) -> Collection:
        """Get a specific collection"""
        response = self.supabase.table("collections").select("*").eq("id", collection_id).execute()
        return Collection(**response.data[0]) if response.data else None
    
    def update_collection(self, collection_id: str, name: str = None, description: str = None):
        """Update a collection"""
        data = {}
        if name: data["name"] = name
        if description: data["description"] = description
        
        return self.supabase.table("collections").update(data).eq("id", collection_id).execute()
    
    def delete_collection(self, collection_id: str):
        """Delete a collection"""
        return self.supabase.table("collections").delete().eq("id", collection_id).execute()
    
    # --- Memories ---
    
    def create_memory(
        self,
        title: str,
        content: str,
        collection_id: str = None,
        tags: List[str] = None,
        source: str = None
    ) -> Memory:
        """Create a new memory"""
        response = self.supabase.table("memories").insert({
            "title": title,
            "content": content,
            "collection_id": collection_id,
            "tags": tags or [],
            "source": source
        }).execute()
        
        return Memory(**response.data[0])
    
    def get_memory(self, memory_id: str) -> Memory:
        """Get a specific memory"""
        response = self.supabase.table("memories").select("*").eq("id", memory_id).execute()
        return Memory(**response.data[0]) if response.data else None
    
    def get_memories(
        self,
        collection_id: str = None,
        limit: int = 50
    ) -> List[Memory]:
        """Get memories, optionally filtered by collection"""
        query = self.supabase.table("memories").select("*").order("created_at", desc=True).limit(limit)
        
        if collection_id:
            query = query.eq("collection_id", collection_id)
        
        response = query.execute()
        return [Memory(**r) for r in response.data]
    
    def update_memory(
        self,
        memory_id: str,
        title: str = None,
        content: str = None,
        tags: List[str] = None,
        collection_id: str = None
    ):
        """Update a memory"""
        data = {}
        if title: data["title"] = title
        if content: data["content"] = content
        if tags: data["tags"] = tags
        if collection_id: data["collection_id"] = collection_id
        
        return self.supabase.table("memories").update(data).eq("id", memory_id).execute()
    
    def delete_memory(self, memory_id: str):
        """Delete a memory"""
        return self.supabase.table("memories").delete().eq("id", memory_id).execute()
    
    # --- Search ---
    
    def search_fulltext(self, query: str, limit: int = 10) -> List[Dict]:
        """Full-text search using PostgreSQL"""
        response = self.supabase.rpc("search_memories", {
            "search_query": query,
            "search_limit": limit
        }).execute()
        
        return response.data
    
    def search_vector(self, embedding: List[float], limit: int = 5) -> List[Dict]:
        """Vector similarity search"""
        response = self.supabase.rpc("match_memories", {
            "query_embedding": embedding,
            "match_count": limit
        }).execute()
        
        return response.data
    
    def search_hybrid(self, query: str, embedding: List[float] = None, limit: int = 10) -> List[Dict]:
        """Hybrid search: full-text + vector"""
        # Get full-text results
        ft_results = self.search_fulltext(query, limit)
        
        # If no vector embedding, return full-text only
        if not embedding:
            return ft_results
        
        # Get vector results
        vec_results = self.search_vector(embedding, limit)
        
        # Merge and dedupe by ID
        seen = set()
        combined = []
        
        for r in vec_results + ft_results:
            if r["id"] not in seen:
                seen.add(r["id"])
                combined.append(r)
        
        return combined[:limit]
    
    # --- Embeddings ---
    
    def add_embedding(self, memory_id: str, embedding: List[float], model: str = "text-embedding-ada-002"):
        """Add vector embedding for a memory"""
        return self.supabase.table("memory_embeddings").insert({
            "memory_id": memory_id,
            "embedding": embedding,
            "model": model
        }).execute()
    
    def delete_embeddings(self, memory_id: str):
        """Delete embeddings for a memory"""
        return self.supabase.table("memory_embeddings").delete().eq("memory_id", memory_id).execute()
    
    # --- Bulk Operations ---
    
    def import_memories(self, memories: List[Dict]):
        """Bulk import memories"""
        data = []
        for m in memories:
            data.append({
                "title": m.get("title", ""),
                "content": m.get("content", ""),
                "tags": m.get("tags", []),
                "source": m.get("source"),
                "collection_id": m.get("collection_id")
            })
        
        return self.supabase.table("memories").insert(data).execute()
    
    def export_memories(self, collection_id: str = None) -> List[Dict]:
        """Export all memories"""
        query = self.supabase.table("memories").select("*")
        
        if collection_id:
            query = query.eq("collection_id", collection_id)
        
        response = query.execute()
        return response.data


# Factory function
def create_memory_client(supabase_url: str, supabase_key: str) -> SupabaseMemoryClient:
    """Create a Supabase memory client"""
    return SupabaseMemoryClient(supabase_url, supabase_key)
