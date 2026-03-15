"""
Memory Bridge - Complete Client with Sync
All features in one client
"""
from supabase import create_client, Client
from typing import List, Dict, Optional
import uuid

class MemoryClient:
    """Complete memory client with all features"""
    
    def __init__(self, supabase_url: str, supabase_key: str, user_id: str = None):
        self.supabase: Client = create_client(supabase_url, supabase_key)
        self.user_id = user_id or str(uuid.uuid4())
    
    # --- Collections ---
    
    def create_collection(self, name: str, description: str = None) -> Dict:
        """Create a collection"""
        result = self.supabase.table("collections").insert({
            "name": name,
            "description": description,
            "user_id": self.user_id
        }).execute()
        return result.data[0]
    
    def get_collections(self) -> List[Dict]:
        """Get all collections"""
        result = self.supabase.table("collections").select("*").eq("user_id", self.user_id).execute()
        return result.data
    
    def delete_collection(self, collection_id: str):
        """Delete a collection"""
        return self.supabase.table("collections").delete().eq("id", collection_id).eq("user_id", self.user_id).execute()
    
    # --- Memories ---
    
    def create_memory(
        self,
        title: str,
        content: str,
        tags: List[str] = None,
        source: str = None,
        collection_id: str = None
    ) -> Dict:
        """Create a memory"""
        result = self.supabase.table("memories").insert({
            "title": title,
            "content": content,
            "tags": tags or [],
            "source": source,
            "collection_id": collection_id,
            "user_id": self.user_id
        }).execute()
        return result.data[0]
    
    def get_memories(self, collection_id: str = None, limit: int = 50) -> List[Dict]:
        """Get memories"""
        query = self.supabase.table("memories").select("*").eq("user_id", self.user_id).order("created_at", desc=True).limit(limit)
        
        if collection_id:
            query = query.eq("collection_id", collection_id)
        
        result = query.execute()
        return result.data
    
    def get_memory(self, memory_id: str) -> Optional[Dict]:
        """Get a specific memory"""
        result = self.supabase.table("memories").select("*").eq("id", memory_id).eq("user_id", self.user_id).execute()
        return result.data[0] if result.data else None
    
    def update_memory(self, memory_id: str, title: str = None, content: str = None, tags: List[str] = None) -> Dict:
        """Update a memory"""
        data = {}
        if title: data["title"] = title
        if content: data["content"] = content
        if tags: data["tags"] = tags
        
        result = self.supabase.table("memories").update(data).eq("id", memory_id).eq("user_id", self.user_id).execute()
        return result.data[0] if result.data else None
    
    def delete_memory(self, memory_id: str):
        """Delete a memory"""
        return self.supabase.table("memories").delete().eq("id", memory_id).eq("user_id", self.user_id).execute()
    
    # --- Search ---
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search memories (keyword)"""
        result = self.supabase.table("memories").select("*").eq("user_id", self.user_id).execute()
        
        query_lower = query.lower()
        matches = [
            m for m in result.data 
            if query_lower in m.get("title", "").lower() 
            or query_lower in m.get("content", "").lower()
        ]
        
        return matches[:limit]
    
    def get_stats(self) -> Dict:
        """Get memory stats"""
        memories = self.supabase.table("memories").select("id", count="exact").eq("user_id", self.user_id).execute()
        collections = self.supabase.table("collections").select("id", count="exact").eq("user_id", self.user_id).execute()
        
        return {
            "memories": memories.count or 0,
            "collections": collections.count or 0
        }
    
    # --- Sync ---
    
    def sync_from_notion(self, notion_client):
        """Sync from Notion to memory"""
        from notion_sync import create_notion_sync
        sync = create_notion_sync(notion_client, self)
        return sync.sync_to_supabase()
    
    def sync_from_obsidian(self, vault_path: str):
        """Sync from Obsidian to memory"""
        from obsidian_sync import create_obsidian_sync
        sync = create_obsidian_sync(vault_path, self)
        return sync.sync_to_supabase()


def create_memory_client(
    supabase_url: str,
    supabase_key: str,
    user_id: str = None
) -> MemoryClient:
    """Factory function"""
    return MemoryClient(supabase_url, supabase_key, user_id)
