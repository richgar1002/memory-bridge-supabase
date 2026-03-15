"""
Memory Client - Production Version
Comprehensive error handling, retry logic, logging
"""
import logging
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ClientError(Exception):
    """Base client error"""
    pass


class AuthenticationError(ClientError):
    """Auth failed"""
    pass


class NotFoundError(ClientError):
    """Resource not found"""
    pass


class RateLimitError(ClientError):
    """Rate limited"""
    pass


@dataclass
class ClientConfig:
    """Client configuration"""
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 30
    verbose: bool = True


class MemoryClient:
    """
    Production-ready memory client with error handling
    """
    
    def __init__(self, supabase_url: str, supabase_key: str, user_id: str = None, config: ClientConfig = None):
        from supabase import create_client
        
        self.supabase = create_client(supabase_url, supabase_key)
        self.user_id = user_id
        self.config = config or ClientConfig()
        
        logger.info(f"Memory client initialized for user: {user_id}")
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute with automatic retry"""
        last_error = None
        
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return func(*args, **kwargs)
                
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                
                # Check for specific errors
                if 'rate limit' in error_msg or '429' in error_msg:
                    logger.warning(f"Rate limited, attempt {attempt}")
                    if attempt < self.config.max_retries:
                        delay = self.config.retry_delay * (2 ** (attempt - 1))
                        time.sleep(delay)
                        continue
                        
                elif 'auth' in error_msg or 'unauthorized' in error_msg:
                    logger.error("Authentication failed")
                    raise AuthenticationError(f"Authentication failed: {e}") from e
                    
                elif 'not found' in error_msg or '404' in error_msg:
                    logger.error("Resource not found")
                    raise NotFoundError(f"Resource not found: {e}") from e
                
                else:
                    logger.warning(f"Attempt {attempt} failed: {e}")
                    if attempt < self.config.max_retries:
                        delay = self.config.retry_delay * (2 ** (attempt - 1))
                        logger.info(f"Retrying in {delay}s...")
                        time.sleep(delay)
                    else:
                        raise
        
        raise last_error
    
    # --- Collections ---
    
    def create_collection(self, name: str, description: str = None) -> Dict:
        """Create a collection with error handling"""
        try:
            def op():
                return self.supabase.table("collections").insert({
                    "name": name,
                    "description": description,
                    "user_id": self.user_id
                }).execute()
            
            result = self._retry_with_backoff(op)
            logger.info(f"Created collection: {name}")
            return result.data[0]
            
        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            raise ClientError(f"Failed to create collection: {e}") from e
    
    def get_collections(self) -> List[Dict]:
        """Get all collections"""
        try:
            def op():
                return self.supabase.table("collections").select("*").eq("user_id", self.user_id).execute()
            
            result = self._retry_with_backoff(op)
            return result.data or []
            
        except Exception as e:
            logger.error(f"Failed to get collections: {e}")
            return []
    
    def get_collection(self, collection_id: str) -> Optional[Dict]:
        """Get a specific collection"""
        try:
            def op():
                return self.supabase.table("collections").select("*").eq("id", collection_id).eq("user_id", self.user_id).execute()
            
            result = self._retry_with_backoff(op)
            return result.data[0] if result.data else None
            
        except Exception as e:
            logger.error(f"Failed to get collection: {e}")
            return None
    
    def update_collection(self, collection_id: str, name: str = None, description: str = None) -> Optional[Dict]:
        """Update a collection"""
        try:
            data = {}
            if name: data["name"] = name
            if description: data["description"] = description
            
            def op():
                return self.supabase.table("collections").update(data).eq("id", collection_id).eq("user_id", self.user_id).execute()
            
            result = self._retry_with_backoff(op)
            logger.info(f"Updated collection: {collection_id}")
            return result.data[0] if result.data else None
            
        except Exception as e:
            logger.error(f"Failed to update collection: {e}")
            raise ClientError(f"Failed to update collection: {e}") from e
    
    def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection"""
        try:
            def op():
                return self.supabase.table("collections").delete().eq("id", collection_id).eq("user_id", self.user_id).execute()
            
            self._retry_with_backoff(op)
            logger.info(f"Deleted collection: {collection_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
            return False
    
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
        try:
            def op():
                return self.supabase.table("memories").insert({
                    "title": title,
                    "content": content,
                    "tags": tags or [],
                    "source": source,
                    "collection_id": collection_id,
                    "user_id": self.user_id
                }).execute()
            
            result = self._retry_with_backoff(op)
            logger.info(f"Created memory: {title}")
            return result.data[0]
            
        except Exception as e:
            logger.error(f"Failed to create memory: {e}")
            raise ClientError(f"Failed to create memory: {e}") from e
    
    def get_memories(self, collection_id: str = None, limit: int = 50) -> List[Dict]:
        """Get memories"""
        try:
            query = self.supabase.table("memories").select("*").eq("user_id", self.user_id).order("created_at", desc=True).limit(limit)
            
            if collection_id:
                query = query.eq("collection_id", collection_id)
            
            def op():
                return query.execute()
            
            result = self._retry_with_backoff(op)
            return result.data or []
            
        except Exception as e:
            logger.error(f"Failed to get memories: {e}")
            return []
    
    def get_memory(self, memory_id: str) -> Optional[Dict]:
        """Get a specific memory"""
        try:
            def op():
                return self.supabase.table("memories").select("*").eq("id", memory_id).eq("user_id", self.user_id).execute()
            
            result = self._retry_with_backoff(op)
            return result.data[0] if result.data else None
            
        except Exception as e:
            logger.error(f"Failed to get memory: {e}")
            return None
    
    def update_memory(
        self,
        memory_id: str,
        title: str = None,
        content: str = None,
        tags: List[str] = None
    ) -> Optional[Dict]:
        """Update a memory"""
        try:
            data = {}
            if title: data["title"] = title
            if content: data["content"] = content
            if tags: data["tags"] = tags
            
            def op():
                return self.supabase.table("memories").update(data).eq("id", memory_id).eq("user_id", self.user_id).execute()
            
            result = self._retry_with_backoff(op)
            logger.info(f"Updated memory: {memory_id}")
            return result.data[0] if result.data else None
            
        except Exception as e:
            logger.error(f"Failed to update memory: {e}")
            raise ClientError(f"Failed to update memory: {e}") from e
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory"""
        try:
            def op():
                return self.supabase.table("memories").delete().eq("id", memory_id).eq("user_id", self.user_id).execute()
            
            self._retry_with_backoff(op)
            logger.info(f"Deleted memory: {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False
    
    # --- Search ---
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search memories"""
        try:
            def op():
                return self.supabase.table("memories").select("*").eq("user_id", self.user_id).execute()
            
            result = self._retry_with_backoff(op)
            
            query_lower = query.lower()
            matches = [
                m for m in (result.data or [])
                if query_lower in m.get("title", "").lower()
                or query_lower in m.get("content", "").lower()
            ]
            
            return matches[:limit]
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    # --- Stats ---
    
    def get_stats(self) -> Dict:
        """Get memory statistics"""
        try:
            memories = self._retry_with_backoff(
                lambda: self.supabase.table("memories").select("id", count="exact").eq("user_id", self.user_id).execute()
            )
            
            collections = self._retry_with_backoff(
                lambda: self.supabase.table("collections").select("id", count="exact").eq("user_id", self.user_id).execute()
            )
            
            return {
                "memories": memories.count or 0,
                "collections": collections.count or 0
            }
            
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"memories": 0, "collections": 0}


def create_memory_client(
    supabase_url: str,
    supabase_key: str,
    user_id: str = None,
    config: ClientConfig = None
) -> MemoryClient:
    """Factory function"""
    return MemoryClient(supabase_url, supabase_key, user_id, config)
