"""
Memory Bridge API - Production REST API
FastAPI server with JWT authentication
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
import logging

from supabase import create_client, Client
from client import create_memory_client, MemoryClient

app = FastAPI(title="Memory Bridge API", version="1.0.0")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")


def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


async def get_user_id(authorization: str = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.replace("Bearer ", "")
    supabase = get_supabase_client()

    try:
        user = supabase.auth.get_user(token)
        if not user.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user.user.id
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


def get_client(user_id: str) -> MemoryClient:
    return create_memory_client(SUPABASE_URL, SUPABASE_SERVICE_KEY, user_id)


class MemoryCreate(BaseModel):
    title: str
    content: str
    tags: List[str] = []
    source: Optional[str] = None
    collection_id: Optional[str] = None


class MemoryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str


class ObsidianSyncRequest(BaseModel):
    vault_path: str


class NotionSyncRequest(BaseModel):
    notion_token: str
    database_id: str


@app.post("/auth/login")
async def login(request: LoginRequest) -> dict:
    supabase = get_supabase_client()
    try:
        response = supabase.auth.sign_in_with_password(
            {"email": request.email, "password": request.password}
        )
        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "user_id": response.user.id,
        }
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/auth/signup")
async def signup(request: SignupRequest) -> dict:
    supabase = get_supabase_client()
    try:
        response = supabase.auth.sign_up({"email": request.email, "password": request.password})
        return {
            "user_id": response.user.id if response.user else None,
            "message": "Check email for confirmation"
            if not response.session
            else "Account created",
        }
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/collections")
async def create_collection(request: CollectionCreate, user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    collection = client.create_collection(request.name, request.description)
    return collection


@app.get("/collections")
async def get_collections(user_id: str = Depends(get_user_id)) -> List[dict]:
    client = get_client(user_id)
    return client.get_collections()


@app.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str, user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    client.delete_collection(collection_id)
    return {"status": "deleted"}


@app.post("/memories")
async def create_memory(request: MemoryCreate, user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    memory = client.create_memory(
        title=request.title,
        content=request.content,
        tags=request.tags,
        source=request.source,
        collection_id=request.collection_id,
    )
    return memory


@app.get("/memories")
async def get_memories(
    collection_id: Optional[str] = None, limit: int = 50, user_id: str = Depends(get_user_id)
) -> List[dict]:
    client = get_client(user_id)
    return client.get_memories(collection_id, limit)


@app.get("/memories/{memory_id}")
async def get_memory(memory_id: str, user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    memory = client.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@app.put("/memories/{memory_id}")
async def update_memory(
    memory_id: str, request: MemoryUpdate, user_id: str = Depends(get_user_id)
) -> dict:
    client = get_client(user_id)
    memory = client.update_memory(
        memory_id, title=request.title, content=request.content, tags=request.tags
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    client.delete_memory(memory_id)
    return {"status": "deleted"}


@app.post("/search")
async def search_memories(request: SearchRequest, user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    results = client.search(request.query, request.limit)
    return {"query": request.query, "results": results, "count": len(results)}


@app.post("/sync/obsidian")
async def sync_obsidian(request: ObsidianSyncRequest, user_id: str = Depends(get_user_id)) -> dict:
    from obsidian_sync import create_obsidian_sync, SyncDirection

    client = get_client(user_id)
    sync = create_obsidian_sync(request.vault_path, client, SyncDirection.BIDIRECTIONAL)
    result = sync.sync_bidirectional()
    return {
        "direction_a": result["obsidian_to_supabase"].direction.value,
        "direction_b": result["supabase_to_obsidian"].direction.value,
        "status": result["obsidian_to_supabase"].status.value,
    }


@app.post("/sync/notion")
async def sync_notion(request: NotionSyncRequest, user_id: str = Depends(get_user_id)) -> dict:
    from notion_sync import create_notion_sync, SyncDirection
    from notion_client import Client as NotionClient

    notion = NotionClient(auth=request.notion_token)
    notion.database_id = request.database_id

    client = get_client(user_id)
    sync = create_notion_sync(notion, client, SyncDirection.BIDIRECTIONAL)
    result = sync.sync_bidirectional()
    return {
        "direction_a": result["notion_to_supabase"].direction.value,
        "direction_b": result["supabase_to_notion"].direction.value,
        "status": result["notion_to_supabase"].status.value,
    }


@app.get("/stats")
async def get_stats(user_id: str = Depends(get_user_id)) -> dict:
    client = get_client(user_id)
    return client.get_stats()


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/")
async def root() -> dict:
    return {"name": "Memory Bridge API", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
