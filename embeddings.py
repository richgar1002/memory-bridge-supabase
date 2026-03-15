"""
Memory Bridge - Vector Embeddings
Add semantic search using Ollama embeddings
"""
from supabase import create_client
import requests

# Configuration
SUPABASE_URL = "https://ujfmhpbodscrzkwkynon.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVqZm1ocGJvZHNjcnprd2t5bm9uIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzUzNDU1NSwiZXhwIjoyMDg5MTEwNTU1fQ.EGaVQNXS9nMe7_09eMqUxfUluk-EMHeb6DF8ltYHYtE"

OLLAMA_URL = "http://localhost:11434"


def get_embedding(text: str, model: str = "nomic-embed-text") -> list:
    """Get embedding from Ollama"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=30
        )
        return response.json().get("embedding", [])
    except Exception as e:
        print(f"Error getting embedding: {e}")
        return []


def store_memory_with_embedding(
    supabase,
    user_id: str,
    title: str,
    content: str,
    tags: list = None,
    source: str = None,
    collection_id: str = None
):
    """Store memory with vector embedding"""
    
    # Combine title and content for embedding
    full_text = f"{title}. {content}"
    
    # Get embedding
    embedding = get_embedding(full_text)
    
    # Store in Supabase
    # First create the memory
    memory_data = {
        "title": title,
        "content": content,
        "user_id": user_id,
        "tags": tags or [],
        "source": source,
        "collection_id": collection_id
    }
    
    memory_result = supabase.table("memories").insert(memory_data).execute()
    memory_id = memory_result.data[0]["id"]
    
    # Then store the embedding
    if embedding:
        embedding_data = {
            "memory_id": memory_id,
            "embedding": embedding,
            "model": "nomic-embed-text"
        }
        supabase.table("memory_embeddings").insert(embedding_data).execute()
    
    return memory_id


def semantic_search(supabase, user_id: str, query: str, limit: int = 5):
    """Search memories using vector similarity"""
    
    # Get query embedding
    query_embedding = get_embedding(query)
    
    if not query_embedding:
        return []
    
    # Get all memories and their embeddings for this user
    memories = supabase.table("memories").select("id, title, content, tags, source").eq("user_id", user_id).execute()
    
    # Get embeddings
    results = []
    for memory in memories.data:
        emb_result = supabase.table("memory_embeddings").select("embedding").eq("memory_id", memory["id"]).execute()
        
        if emb_result.data:
            # Calculate cosine similarity
            memory_embedding = emb_result.data[0]["embedding"]
            similarity = cosine_similarity(query_embedding, memory_embedding)
            
            results.append({
                **memory,
                "similarity": similarity
            })
    
    # Sort by similarity
    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    
    return results[:limit]


def cosine_similarity(a: list, b: list) -> float:
    """Calculate cosine similarity between two vectors"""
    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sum(x * x for x in a) ** 0.5
    magnitude_b = sum(x * x for x in b) ** 0.5
    
    if magnitude_a == 0 or magnitude_b == 0:
        return 0
    
    return dot_product / (magnitude_a * magnitude_b)


def hybrid_search(supabase, user_id: str, query: str, limit: int = 5):
    """Combine keyword and semantic search"""
    
    # Get keyword matches
    all_memories = supabase.table("memories").select("*").eq("user_id", user_id).execute()
    query_lower = query.lower()
    
    keyword_matches = [
        m for m in all_memories.data
        if query_lower in m.get("title", "").lower()
        or query_lower in m.get("content", "").lower()
    ]
    
    # Get semantic matches
    semantic_matches = semantic_search(supabase, user_id, query, limit)
    
    # Combine and dedupe
    seen = set()
    combined = []
    
    for m in semantic_matches + keyword_matches:
        if m["id"] not in seen:
            seen.add(m["id"])
            combined.append(m)
    
    return combined[:limit]


# Test
if __name__ == "__main__":
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Test embedding
    print("Testing embedding...")
    emb = get_embedding("Hello world")
    print(f"Embedding length: {len(emb)}")
    
    # Test semantic search
    print("\nTesting semantic search...")
    results = semantic_search(supabase, "test-user-001", "EURUSD trading")
    print(f"Found {len(results)} results")
    for r in results:
        print(f"  - {r.get('title', 'N/A')}: {r.get('similarity', 0):.3f}")
