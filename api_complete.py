"""
Memory Bridge API - Complete REST API
Production-ready API for the memory system
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
import uuid

from client_complete import create_memory_client
from obsidian_sync import create_obsidian_sync
from notion_sync import create_notion_sync

app = FastAPI(title="Memory Bridge API", version="1.0.0")

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ujfmhpbodscrzkwkynon.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# In-memory user sessions (for demo)
users = {}

def get_user_id(x_user_id: str = Header(None)) -> str:
    """Get user ID from header or create anonymous"""
    if not x_user_id:
        x_user_id = str(uuid.uuid4())
    return x_user_id

def get_client(user_id: str) -> 'MemoryClient':
    """Get memory client for user"""
    return create_memory_client(SUPABASE_URL, SUPABASE_KEY, user_id)

# Models

class MemoryCreate(BaseModel):
    title: str
    content: str
    tags: List[str] = []
    source: str = None
    collection_id: str = None

class MemoryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None

class CollectionCreate(BaseModel):
    name: str
    description: str = None

class SearchRequest(BaseModel):
    query: str
    limit: int = 10

class ObsidianSyncRequest(BaseModel):
    vault_path: str

class NotionSyncRequest(BaseModel):
    notion_token: str
    database_id: str

# Collections

@app.post("/collections")
async def create_collection(
    request: CollectionCreate,
    user_id: str = Depends(get_user_id)
):
    """Create a collection"""
    client = get_client(user_id)
    collection = client.create_collection(request.name, request.description)
    return collection

@app.get("/collections")
async def get_collections(user_id: str = Depends(get_user_id)):
    """Get all collections"""
    client = get_client(user_id)
    return client.get_collections()

@app.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: str,
    user_id: str = Depends(get_user_id)
):
    """Delete a collection"""
    client = get_client(user_id)
    client.delete_collection(collection_id)
    return {"status": "deleted"}

# Memories

@app.post("/memories")
async def create_memory(
    request: MemoryCreate,
    user_id: str = Depends(get_user_id)
):
    """Create a memory"""
    client = get_client(user_id)
    memory = client.create_memory(
        title=request.title,
        content=request.content,
        tags=request.tags,
        source=request.source,
        collection_id=request.collection_id
    )
    return memory

@app.get("/memories")
async def get_memories(
    collection_id: str = None,
    limit: int = 50,
    user_id: str = Depends(get_user_id)
):
    """Get all memories"""
    client = get_client(user_id)
    return client.get_memories(collection_id, limit)

@app.get("/memories/{memory_id}")
async def get_memory(
    memory_id: str,
    user_id: str = Depends(get_user_id)
):
    """Get a specific memory"""
    client = get_client(user_id)
    memory = client.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory

@app.put("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    request: MemoryUpdate,
    user_id: str = Depends(get_user_id)
):
    """Update a memory"""
    client = get_client(user_id)
    memory = client.update_memory(
        memory_id,
        title=request.title,
        content=request.content,
        tags=request.tags
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory

@app.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_user_id)
):
    """Delete a memory"""
    client = get_client(user_id)
    client.delete_memory(memory_id)
    return {"status": "deleted"}

# Search

@app.post("/search")
async def search_memories(
    request: SearchRequest,
    user_id: str = Depends(get_user_id)
):
    """Search memories"""
    client = get_client(user_id)
    results = client.search(request.query, request.limit)
    return {
        "query": request.query,
        "results": results,
        "count": len(results)
    }

# Sync

@app.post("/sync/obsidian")
async def sync_obsidian(
    request: ObsidianSyncRequest,
    user_id: str = Depends(get_user_id)
):
    """Sync from Obsidian vault"""
    client = get_client(user_id)
    sync = create_obsidian_sync(request.vault_path, client)
    result = sync.sync_to_supabase()
    return result

@app.post("/sync/notion")
async def sync_notion(
    request: NotionSyncRequest,
    user_id: str = Depends(get_user_id)
):
    """Sync from Notion"""
    from notion_client import Client as NotionClient
    
    notion = NotionClient(auth=request.notion_token)
    notion.database_id = request.notion_database_id
    
    client = get_client(user_id)
    result = client.sync_from_notion(notion)
    return result

# Stats

@app.get("/stats")
async def get_stats(user_id: str = Depends(get_user_id)):
    """Get memory statistics"""
    client = get_client(user_id)
    return client.get_stats()

# Health

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "supabase": SUPABASE_URL
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Memory Bridge API",
        "version": "1.0.0",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
