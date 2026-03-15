"""
Memory Bridge API - Supabase Edition
Production-ready REST API
"""
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os

from supabase import create_client, Client
import uuid

app = FastAPI(title="Memory Bridge API")

# Config
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ujfmhpbodscrzkwkynon.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Simple in-memory session for demo (replace with proper auth in production)
sessions = {}

def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

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

# Auth (simplified for demo)
def get_user_id(x_user_id: str = Header(None)) -> str:
    if not x_user_id:
        # Create anonymous user for demo
        x_user_id = str(uuid.uuid4())
    return x_user_id

# Collections

@app.post("/collections")
async def create_collection(
    request: CollectionCreate,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    result = supabase.table("collections").insert({
        "name": request.name,
        "description": request.description,
        "user_id": user_id
    }).execute()
    
    return result.data[0]

@app.get("/collections")
async def get_collections(user_id: str = Depends(get_user_id)):
    supabase = get_client()
    
    result = supabase.table("collections").select("*").eq("user_id", user_id).execute()
    return result.data

@app.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: str,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    result = supabase.table("collections").delete().eq("id", collection_id).eq("user_id", user_id).execute()
    return {"status": "deleted"}

# Memories

@app.post("/memories")
async def create_memory(
    request: MemoryCreate,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    result = supabase.table("memories").insert({
        "title": request.title,
        "content": request.content,
        "tags": request.tags,
        "source": request.source,
        "collection_id": request.collection_id,
        "user_id": user_id
    }).execute()
    
    return result.data[0]

@app.get("/memories")
async def get_memories(
    collection_id: str = None,
    limit: int = 50,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    query = supabase.table("memories").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(limit)
    
    if collection_id:
        query = query.eq("collection_id", collection_id)
    
    result = query.execute()
    return result.data

@app.get("/memories/{memory_id}")
async def get_memory(
    memory_id: str,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    result = supabase.table("memories").select("*").eq("id", memory_id).eq("user_id", user_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return result.data[0]

@app.put("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    request: MemoryUpdate,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    data = {}
    if request.title: data["title"] = request.title
    if request.content: data["content"] = request.content
    if request.tags: data["tags"] = request.tags
    
    result = supabase.table("memories").update(data).eq("id", memory_id).eq("user_id", user_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return result.data[0]

@app.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    result = supabase.table("memories").delete().eq("id", memory_id).eq("user_id", user_id).execute()
    return {"status": "deleted"}

# Search

@app.post("/search")
async def search_memories(
    request: SearchRequest,
    user_id: str = Depends(get_user_id)
):
    supabase = get_client()
    
    # Full-text search using PostgreSQL
    result = supabase.table("memories").select("*").eq("user_id", user_id).execute()
    
    # Simple search (can upgrade to use PostgreSQL search later)
    query_lower = request.query.lower()
    matches = [
        m for m in result.data 
        if query_lower in m.get("title", "").lower() 
        or query_lower in m.get("content", "").lower()
    ]
    
    return {
        "query": request.query,
        "results": matches[:request.limit],
        "count": len(matches)
    }

# Stats

@app.get("/stats")
async def get_stats(user_id: str = Depends(get_user_id)):
    supabase = get_client()
    
    memories = supabase.table("memories").select("id").eq("user_id", user_id).execute()
    collections = supabase.table("collections").select("id").eq("user_id", user_id).execute()
    
    return {
        "memories": len(memories.data),
        "collections": len(collections.data)
    }

# Health

@app.get("/health")
async def health():
    return {"status": "healthy", "supabase": SUPABASE_URL}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
