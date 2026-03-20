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

    # --- Hub Model Methods ---

    def compute_content_hash(
        self,
        title: str,
        content: str,
        metadata: dict = None
    ) -> str:
        """Compute deterministic SHA256 hash of memory content."""
        import hashlib
        import json
        payload = {
            "title": title or "",
            "content": content or "",
            "metadata": metadata or {},
        }
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_sync_link(
        self,
        provider: str,
        external_id: str,
        user_id: str = None
    ) -> Optional[Dict]:
        """Look up sync link by provider and external ID."""
        uid = user_id or self.user_id
        try:
            response = self._retry_with_backoff(
                lambda: self.supabase.table("sync_links")
                .select("*")
                .eq("provider", provider)
                .eq("external_id", external_id)
                .eq("user_id", uid)
                .execute()
            )
            return response.data[0] if response.data else None
        except Exception as e:
            logger.warning(f"Error fetching sync link: {e}")
            return None

    def create_sync_link(
        self,
        memory_id: str,
        provider: str,
        external_id: str,
        user_id: str = None,
        **kwargs
    ) -> Dict:
        """Create a new sync link."""
        uid = user_id or self.user_id
        data = {
            "user_id": uid,
            "memory_id": memory_id,
            "provider": provider,
            "external_id": external_id,
            **kwargs
        }
        response = self._retry_with_backoff(
            lambda: self.supabase.table("sync_links").insert(data).execute()
        )
        return response.data[0]

    def update_sync_link(
        self,
        sync_link_id: str,
        **kwargs
    ) -> Dict:
        """Update sync link fields."""
        response = self._retry_with_backoff(
            lambda: self.supabase.table("sync_links").update(kwargs).eq("id", sync_link_id).execute()
        )
        return response.data[0]

    def upsert_memory_from_sync(
        self,
        *,
        provider: str,
        external_id: str,
        title: str,
        content: str,
        tags: List[str] = None,
        metadata: Dict = None,
        external_path: str = None,
        remote_updated_at: str = None,
        user_id: str = None
    ) -> Dict:
        """
        Core sync upsert logic:
        1. Compute incoming hash
        2. Lookup sync_links by (user_id, provider, external_id)
        3. If no link: create memory + create sync_link + log events
        4. If link exists: compare hashes, update if changed, detect conflicts
        """
        from datetime import datetime
        import uuid

        uid = user_id or self.user_id
        incoming_hash = self.compute_content_hash(title, content, metadata)

        # Check for existing sync link
        existing_link = self.get_sync_link(provider, external_id, uid)

        if not existing_link:
            # Create new memory
            memory_data = {
                "user_id": uid,
                "title": title,
                "content": content,
                "content_plain": content,
                "tags": tags or [],
                "metadata": metadata or {},
                "content_hash": incoming_hash,
                "revision": 1,
                "status": "active",
                "source_preference": provider,
            }
            memory_response = self._retry_with_backoff(
                lambda: self.supabase.table("memories").insert(memory_data).execute()
            )
            memory = memory_response.data[0]

            # Create sync link
            sync_link_data = {
                "last_synced_hash": incoming_hash,
                "last_synced_revision": 1,
                "last_synced_at": datetime.utcnow().isoformat(),
                "remote_updated_at": remote_updated_at,
            }
            if external_path:
                sync_link_data["external_path"] = external_path

            self.create_sync_link(memory["id"], provider, external_id, uid, **sync_link_data)

            # Log events
            self.log_memory_event(memory["id"], "created", "adapter", after_hash=incoming_hash, user_id=uid)
            self.log_memory_event(memory["id"], "synced", "adapter", after_hash=incoming_hash, user_id=uid)

            logger.info(f"Created new memory {memory['id']} from {provider}:{external_id}")
            return memory

        else:
            # Existing link - check for changes
            memory_id = existing_link["memory_id"]
            last_synced_hash = existing_link.get("last_synced_hash")

            if incoming_hash == last_synced_hash:
                # No changes - no-op
                memory_response = self._retry_with_backoff(
                    lambda: self.supabase.table("memories").select("*").eq("id", memory_id).execute()
                )
                logger.debug(f"No changes for {provider}:{external_id}")
                return memory_response.data[0]

            # Fetch current memory
            memory_response = self._retry_with_backoff(
                lambda: self.supabase.table("memories").select("*").eq("id", memory_id).execute()
            )
            current_memory = memory_response.data[0]
            current_hash = current_memory.get("content_hash")

            # Detect conflict: both changed since last sync
            if current_hash != last_synced_hash and incoming_hash != last_synced_hash:
                # Create conflict record
                self.create_conflict(
                    memory_id=memory_id,
                    provider_a=provider,
                    provider_b=existing_link.get("provider", provider),
                    hash_a=current_hash,
                    hash_b=incoming_hash,
                    title_a=current_memory["title"],
                    title_b=title,
                    content_a=current_memory["content"],
                    content_b=content,
                    user_id=uid
                )
                # Update sync link to conflicted
                self.update_sync_link(existing_link["id"], sync_state="conflicted")
                self.log_memory_event(
                    memory_id, "conflict_detected", "system",
                    payload={"provider": provider, "external_id": external_id},
                    user_id=uid
                )
                logger.warning(f"Conflict detected for memory {memory_id}")
                return current_memory

            # One side changed - update memory
            new_revision = current_memory.get("revision", 1) + 1
            update_data = {
                "title": title,
                "content": content,
                "content_plain": content,
                "tags": tags or current_memory.get("tags", []),
                "metadata": metadata or current_memory.get("metadata", {}),
                "content_hash": incoming_hash,
                "revision": new_revision,
            }
            self._retry_with_backoff(
                lambda: self.supabase.table("memories").update(update_data).eq("id", memory_id).execute()
            )

            # Update sync link
            self.update_sync_link(existing_link["id"], {
                "last_synced_hash": incoming_hash,
                "last_synced_revision": new_revision,
                "last_synced_at": datetime.utcnow().isoformat(),
                "remote_updated_at": remote_updated_at,
                "sync_state": "linked"
            })

            # Log events
            self.log_memory_event(
                memory_id, "updated", "adapter",
                before_hash=current_hash, after_hash=incoming_hash,
                user_id=uid
            )
            self.log_memory_event(memory_id, "synced", "adapter", after_hash=incoming_hash, user_id=uid)

            logger.info(f"Updated memory {memory_id} from {provider}:{external_id}")

            # Return updated memory
            memory_response = self._retry_with_backoff(
                lambda: self.supabase.table("memories").select("*").eq("id", memory_id).execute()
            )
            return memory_response.data[0]

    def log_memory_event(
        self,
        memory_id: str,
        event_type: str,
        actor_type: str,
        payload: Dict = None,
        sync_link_id: str = None,
        before_hash: str = None,
        after_hash: str = None,
        user_id: str = None
    ) -> None:
        """Log a memory event for audit trail."""
        uid = user_id or self.user_id
        try:
            self._retry_with_backoff(
                lambda: self.supabase.table("memory_events").insert({
                    "user_id": uid,
                    "memory_id": memory_id,
                    "sync_link_id": sync_link_id,
                    "event_type": event_type,
                    "actor_type": actor_type,
                    "payload": payload or {},
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                }).execute()
            )
        except Exception as e:
            logger.warning(f"Failed to log memory event: {e}")

    def create_conflict(
        self,
        memory_id: str,
        provider_a: str,
        provider_b: str,
        hash_a: str,
        hash_b: str,
        title_a: str,
        title_b: str,
        content_a: str,
        content_b: str,
        user_id: str = None
    ) -> Dict:
        """Create a conflict record."""
        uid = user_id or self.user_id
        response = self._retry_with_backoff(
            lambda: self.supabase.table("sync_conflicts").insert({
                "user_id": uid,
                "memory_id": memory_id,
                "provider_a": provider_a,
                "provider_b": provider_b,
                "hash_a": hash_a,
                "hash_b": hash_b,
                "title_a": title_a,
                "title_b": title_b,
                "content_a": content_a,
                "content_b": content_b,
                "resolution_status": "open",
            }).execute()
        )
        return response.data[0]

    def get_all_sync_links(
        self,
        provider: str = None,
        user_id: str = None
    ) -> List[Dict]:
        """Get all sync links for user, optionally filtered by provider."""
        uid = user_id or self.user_id
        query = self.supabase.table("sync_links").select("*").eq("user_id", uid)
        if provider:
            query = query.eq("provider", provider)
        response = self._retry_with_backoff(lambda: query.execute())
        return response.data or []

    def get_memory_by_sync_link(
        self,
        provider: str,
        external_id: str,
        user_id: str = None
    ) -> Optional[Dict]:
        """Get memory by sync link."""
        link = self.get_sync_link(provider, external_id, user_id)
        if not link:
            return None
        memory_response = self._retry_with_backoff(
            lambda: self.supabase.table("memories").select("*").eq("id", link["memory_id"]).execute()
        )
        return memory_response.data[0] if memory_response.data else None


def create_memory_client(
    supabase_url: str,
    supabase_key: str,
    user_id: str = None,
    config: ClientConfig = None
) -> MemoryClient:
    """Factory function"""
    return MemoryClient(supabase_url, supabase_key, user_id, config)
