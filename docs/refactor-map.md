# Python Refactor Map

## Priority Order

1. Add `sync_links` table support
2. Add `content_hash` to memories
3. Refactor both sync files to use upsert instead of blind create
4. Add `memory_events` logging
5. Move semantic search to SQL function

---

## client_production.py

### New Methods to Add

```python
def compute_content_hash(
    title: str,
    content: str,
    metadata: dict | None = None
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
    external_id: str
) -> dict | None:
    """Look up sync link by provider and external ID."""
    response = self.client.table("sync_links").select("*").eq("provider", provider).eq("external_id", external_id).execute()
    return response.data[0] if response.data else None


def create_sync_link(
    self,
    memory_id: str,
    provider: str,
    external_id: str,
    **kwargs
) -> dict:
    """Create a new sync link."""
    data = {
        "memory_id": memory_id,
        "provider": provider,
        "external_id": external_id,
        **kwargs
    }
    response = self.client.table("sync_links").insert(data).execute()
    return response.data[0]


def update_sync_link(
    self,
    sync_link_id: str,
    **kwargs
) -> dict:
    """Update sync link fields."""
    response = self.client.table("sync_links").update(kwargs).eq("id", sync_link_id).execute()
    return response.data[0]


def upsert_memory_from_sync(
    self,
    *,
    provider: str,
    external_id: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    metadata: dict | None = None,
    external_path: str | None = None,
    remote_updated_at: str | None = None,
) -> dict:
    """
    Core sync upsert logic:
    1. Compute incoming hash
    2. Lookup sync_links by (user_id, provider, external_id)
    3. If no link: create memory + create sync_link + log events
    4. If link exists: compare hashes, update if changed, detect conflicts
    """
    from datetime import datetime

    user_id = self.client.auth.user().id
    incoming_hash = self.compute_content_hash(title, content, metadata)

    # Check for existing sync link
    existing_link = self.get_sync_link(provider, external_id)

    if not existing_link:
        # Create new memory
        memory_data = {
            "user_id": user_id,
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
        memory_response = self.client.table("memories").insert(memory_data).execute()
        memory = memory_response.data[0]

        # Create sync link
        sync_link_data = {
            "memory_id": memory["id"],
            "provider": provider,
            "external_id": external_id,
            "external_path": external_path,
            "last_synced_hash": incoming_hash,
            "last_synced_revision": 1,
            "last_synced_at": datetime.utcnow().isoformat(),
            "remote_updated_at": remote_updated_at,
        }
        self.create_sync_link(memory["id"], provider, external_id, **sync_link_data)

        # Log events
        self.log_memory_event(memory["id"], "created", "adapter", after_hash=incoming_hash)
        self.log_memory_event(memory["id"], "synced", "adapter", after_hash=incoming_hash)

        return memory

    else:
        # Existing link - check for changes
        memory_id = existing_link["memory_id"]
        last_synced_hash = existing_link.get("last_synced_hash")

        if incoming_hash == last_synced_hash:
            # No changes - no-op
            memory_response = self.client.table("memories").select("*").eq("id", memory_id).execute()
            return memory_response.data[0]

        # Fetch current memory
        memory_response = self.client.table("memories").select("*").eq("id", memory_id).execute()
        current_memory = memory_response.data[0]
        current_hash = current_memory.get("content_hash")

        # Detect conflict: both changed since last sync
        if current_hash != last_synced_hash and incoming_hash != last_synced_hash:
            # Create conflict record
            self.create_conflict(
                memory_id=memory_id,
                provider_a=provider,
                provider_b=provider,  # Simplified - would need external source tracking
                hash_a=current_hash,
                hash_b=incoming_hash,
                title_a=current_memory["title"],
                title_b=title,
                content_a=current_memory["content"],
                content_b=content,
            )
            # Update sync link to conflicted
            self.update_sync_link(existing_link["id"], sync_state="conflicted")
            self.log_memory_event(memory_id, "conflict_detected", "system",
                                  payload={"provider": provider, "external_id": external_id})

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
        self.client.table("memories").update(update_data).eq("id", memory_id).execute()

        # Update sync link
        self.update_sync_link(existing_link["id"], {
            "last_synced_hash": incoming_hash,
            "last_synced_revision": new_revision,
            "last_synced_at": datetime.utcnow().isoformat(),
            "remote_updated_at": remote_updated_at,
            "sync_state": "linked"
        })

        # Log event
        self.log_memory_event(memory_id, "updated", "adapter",
                             before_hash=current_hash, after_hash=incoming_hash)
        self.log_memory_event(memory_id, "synced", "adapter", after_hash=incoming_hash)

        # Return updated memory
        memory_response = self.client.table("memories").select("*").eq("id", memory_id).execute()
        return memory_response.data[0]


def log_memory_event(
    self,
    memory_id: str,
    event_type: str,
    actor_type: str,
    payload: dict | None = None,
    sync_link_id: str | None = None,
    before_hash: str | None = None,
    after_hash: str | None = None,
) -> None:
    """Log a memory event for audit trail."""
    import uuid
    user_id = self.client.auth.user().id
    self.client.table("memory_events").insert({
        "user_id": user_id,
        "memory_id": memory_id,
        "sync_link_id": sync_link_id,
        "event_type": event_type,
        "actor_type": actor_type,
        "payload": payload or {},
        "before_hash": before_hash,
        "after_hash": after_hash,
    }).execute()


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
) -> dict:
    """Create a conflict record."""
    user_id = self.client.auth.user().id
    response = self.client.table("sync_conflicts").insert({
        "user_id": user_id,
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
    return response.data[0]
```

---

## obsidian_sync_production.py

### Refactor to use hub model

**Before:** Create memory from file
**After:** File → sync identity → upsert

```python
def sync_vault(self, vault_path: str):
    """Sync Obsidian vault to hub."""
    from pathlib import Path

    vault = Path(vault_path)
    for note_path in vault.rglob("*.md"):
        # Skip templates, etc.
        if note_path.name.startswith("."):
            continue

        # Parse markdown
        with open(note_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract frontmatter
        title, body, frontmatter = self.parse_markdown(content)
        tags = frontmatter.get("tags", [])
        memory_id = frontmatter.get("memory_id")
        external_id = memory_id or str(note_path.relative_to(vault))

        # Get modified time
        modified_at = note_path.stat().st_mtime

        # Upsert through hub
        result = self.client.upsert_memory_from_sync(
            provider="obsidian",
            external_id=external_id,
            external_path=str(note_path.relative_to(vault)),
            title=title,
            content=body,
            tags=tags,
            metadata=frontmatter,
            remote_updated_at=datetime.fromtimestamp(modified_at).isoformat(),
        )

        # Write back memory_id to frontmatter if new
        if not memory_id and result:
            self.write_memory_id_to_frontmatter(note_path, result["id"])


def parse_markdown(self, content: str) -> tuple[str, str, dict]:
    """Parse markdown file into title, body, and frontmatter."""
    import re

    frontmatter = {}
    body = content

    # Extract YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text = parts[1]
            body = parts[2].strip()

            # Parse YAML frontmatter (simple parser)
            for line in frontmatter_text.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip()

    # Extract title from first H1 or filename
    title = frontmatter.get("title", "")
    if not title:
        h1_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = h1_match.group(1) if h1_match else "Untitled"

    return title, body, frontmatter


def write_memory_id_to_frontmatter(self, note_path: str, memory_id: str):
    """Add memory_id to frontmatter."""
    with open(note_path, "r", encoding="utf-8") as f:
        content = f.read()

    if content.startswith("---"):
        parts = content.split("---", 2)
        frontmatter = parts[1]
        body = parts[2] if len(parts) > 2 else ""

        # Add memory_id to frontmatter
        frontmatter += f"\nmemory_id: {memory_id}\n"

        content = f"---\n{frontmatter}---\n{body}"
    else:
        content = f"---\nmemory_id: {memory_id}\n---\n{content}"

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content)
```

---

## notion_sync_production.py

### Refactor to use hub model

```python
def sync_notion_pages(self):
    """Sync Notion pages to hub."""
    from notion_client import Client

    notion = Client(auth=self.notion_token)
    search_response = notion.search(
        filter={"property": "object", "value": "page"}
    )

    for page in search_response["results"]:
        page_id = page["id"]
        title = self.get_page_title(page)
        content = self.page_to_markdown(page)
        last_edited = page.get("last_edited_time")

        # Get parent info
        parent_id = page.get("parent", {}).get("page_id")
        page_url = page.get("url")

        result = self.client.upsert_memory_from_sync(
            provider="notion",
            external_id=page_id,
            title=title,
            content=content,
            metadata={
                "notion_parent": parent_id,
                "notion_url": page_url,
                "notion_properties": page.get("properties", {}),
            },
            remote_updated_at=last_edited,
        )


def get_page_title(self, page: dict) -> str:
    """Extract title from Notion page."""
    props = page.get("properties", {})
    for prop_name, prop in props.items():
        if prop.get("type") == "title":
            title_arr = prop.get("title", [])
            if title_arr:
                return title_arr[0].get("plain_text", "Untitled")
    return "Untitled"


def page_to_markdown(self, page: dict) -> str:
    """Convert Notion page blocks to markdown."""
    # Simplified - would need full block conversion
    # Use notion-to-md library for complete conversion
    return f"# {self.get_page_title(page)}\n\n[Notion content]"
```

---

## Helper Functions

### Chunking for embeddings

```python
def chunk_text(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 150
) -> list[dict]:
    """Split text into overlapping chunks with hashes."""
    import hashlib
    import json

    chunks = []
    start = 0
    text = text or ""

    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end]

        # Compute chunk hash
        chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()

        chunks.append({
            "text": chunk,
            "hash": chunk_hash,
            "index": len(chunks),
            "token_estimate": len(chunk) // 4,  # Rough estimate
        })

        if end == len(text):
            break

        start = max(0, end - overlap)

    return chunks
```

---

## Migration Checklist

- [ ] Add `compute_content_hash()` to client
- [ ] Add `get_sync_link()`, `create_sync_link()`, `update_sync_link()` methods
- [ ] Add `upsert_memory_from_sync()` - the core sync logic
- [ ] Add `log_memory_event()` for audit trail
- [ ] Add `create_conflict()` for conflict handling
- [ ] Add `chunk_text()` for embedding chunking
- [ ] Refactor `obsidian_sync_production.py` to use upsert
- [ ] Refactor `notion_sync_production.py` to use upsert
- [ ] Add memory_id to Obsidian frontmatter on create
- [ ] Test conflict detection
- [ ] Test full-text search via SQL function
- [ ] Test semantic search via SQL function
