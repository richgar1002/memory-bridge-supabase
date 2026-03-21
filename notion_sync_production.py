"""
Notion Sync - Improved Production Base
Bi-directional Notion <-> Supabase sync with safer writeback behavior.

Notes:
- Assumes memory_client implements:
    - upsert_memory_from_sync(...)
    - get_all_sync_links(provider: str) -> list[dict]
    - get_memory(memory_id: str) -> dict | None   (or similar)
    - log_memory_event(...)
    - create_conflict(...)
- This version uses sync_links as the source of truth for Supabase -> Notion.
- For Notion body updates, existing top-level child blocks are archived before new
  blocks are appended, which prevents duplicate-content growth.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SyncDirection(Enum):
    NOTION_TO_SUPABASE = "notion_to_supabase"
    SUPABASE_TO_NOTION = "supabase_to_notion"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    direction: SyncDirection
    status: SyncStatus
    synced: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class NotionSync:
    """
    Improved Notion <-> Supabase sync adapter.

    Design:
    - Notion pages are external objects.
    - Supabase is the hub/canonical memory layer.
    - sync_links provide durable mapping between Notion page IDs and memory IDs.
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2
    NOTION_MAX_APPEND_BLOCKS = 100
    NOTION_BLOCK_TEXT_LIMIT = 1900

    def __init__(
        self,
        notion_client,
        memory_client,
        direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
    ):
        self.notion = notion_client
        self.client = memory_client
        self.direction = direction

        # In-memory cache restored from sync_links.
        self.synced_pages: Dict[str, str] = {}  # page_id -> last_synced_hash
        self._load_sync_links()

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _reset_stats(self) -> Dict[str, Any]:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

    def _load_sync_links(self) -> None:
        """Load sync links from Supabase to restore persistent state."""
        try:
            if hasattr(self.client, "get_all_sync_links"):
                links = self.client.get_all_sync_links(provider="notion")
                for link in links:
                    external_id = link.get("external_id")
                    last_hash = link.get("last_synced_hash")
                    if external_id and last_hash:
                        self.synced_pages[external_id] = last_hash
                logger.info("Loaded %s Notion sync links from Supabase", len(links))
            else:
                logger.warning("memory_client has no get_all_sync_links(provider=...)")
        except Exception as e:
            logger.warning("Could not load sync links: %s", e)

    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute a function with retry logic."""
        last_error = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(
                    "Attempt %s/%s failed: %s",
                    attempt,
                    self.MAX_RETRIES,
                    e,
                )

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * (2 ** (attempt - 1))
                    logger.info("Retrying in %ss...", delay)
                    time.sleep(delay)

        raise last_error

    def _safe_log_event(
        self,
        memory_id: Optional[str],
        event_type: str,
        actor_type: str,
        payload: Optional[dict] = None,
        sync_link_id: Optional[str] = None,
        before_hash: Optional[str] = None,
        after_hash: Optional[str] = None,
    ) -> None:
        """Best-effort event logging."""
        try:
            if memory_id and hasattr(self.client, "log_memory_event"):
                self.client.log_memory_event(
                    memory_id=memory_id,
                    event_type=event_type,
                    actor_type=actor_type,
                    payload=payload or {},
                    sync_link_id=sync_link_id,
                    before_hash=before_hash,
                    after_hash=after_hash,
                )
        except Exception as e:
            logger.warning("Could not log memory event: %s", e)

    def _extract_title(self, properties: dict) -> str:
        """Extract title from Notion properties."""
        try:
            for _, prop_value in properties.items():
                if prop_value.get("type") == "title":
                    title_array = prop_value.get("title", [])
                    if title_array:
                        return "".join(part.get("plain_text", "") for part in title_array).strip() or "Untitled"
        except Exception as e:
            logger.error("Error extracting title: %s", e)
        return "Untitled"

    def _extract_text(self, rich_text: list) -> str:
        """Extract plain text from Notion rich_text array."""
        try:
            return "".join(t.get("plain_text", "") for t in rich_text)
        except Exception:
            return ""

    def _extract_property_metadata(self, properties: dict) -> dict:
        """Extract lightweight metadata from Notion properties."""
        metadata: dict[str, Any] = {}

        try:
            for prop_name, prop_value in properties.items():
                prop_type = prop_value.get("type")

                if prop_type == "title":
                    continue
                if prop_type == "rich_text":
                    metadata[prop_name] = self._extract_text(prop_value.get("rich_text", []))
                elif prop_type == "number":
                    metadata[prop_name] = prop_value.get("number")
                elif prop_type == "checkbox":
                    metadata[prop_name] = prop_value.get("checkbox")
                elif prop_type == "select":
                    metadata[prop_name] = (prop_value.get("select") or {}).get("name")
                elif prop_type == "multi_select":
                    metadata[prop_name] = [x.get("name") for x in prop_value.get("multi_select", [])]
                elif prop_type == "date":
                    metadata[prop_name] = prop_value.get("date")
                elif prop_type == "url":
                    metadata[prop_name] = prop_value.get("url")
                elif prop_type == "email":
                    metadata[prop_name] = prop_value.get("email")
                elif prop_type == "phone_number":
                    metadata[prop_name] = prop_value.get("phone_number")
                elif prop_type == "status":
                    metadata[prop_name] = (prop_value.get("status") or {}).get("name")
                else:
                    # Keep it lightweight; avoid huge/raw property dumps unless needed.
                    metadata[prop_name] = None
        except Exception as e:
            logger.warning("Error extracting property metadata: %s", e)

        return metadata

    def _compute_hash(self, title: str, content: str, metadata: Optional[dict] = None) -> str:
        """Compute stable content hash using title + content + metadata."""
        payload = {
            "title": title or "",
            "content": content or "",
            "metadata": metadata or {},
        }
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------------------
    # Notion block reading/writing
    # -------------------------------------------------------------------------

    def _list_all_block_children(self, block_id: str) -> List[dict]:
        """Fetch all child blocks for a block/page with pagination."""
        results: List[dict] = []
        start_cursor: Optional[str] = None

        while True:
            kwargs = {"block_id": block_id}
            if start_cursor:
                kwargs["start_cursor"] = start_cursor

            response = self._retry_with_backoff(self.notion.blocks.children.list, **kwargs)
            page_results = response.get("results", [])
            results.extend(page_results)

            if not response.get("has_more"):
                break
            start_cursor = response.get("next_cursor")

        return results

    def _flatten_blocks_to_markdown(self, blocks: Iterable[dict], depth: int = 0) -> List[str]:
        """Convert supported Notion blocks into markdown-ish text recursively."""
        parts: List[str] = []

        for block in blocks:
            block_type = block.get("type")
            block_data = block.get(block_type, {})
            text = self._extract_text(block_data.get("rich_text", []))

            if block_type == "paragraph":
                if text:
                    parts.append(text)
            elif block_type == "heading_1":
                parts.append(f"# {text}")
            elif block_type == "heading_2":
                parts.append(f"## {text}")
            elif block_type == "heading_3":
                parts.append(f"### {text}")
            elif block_type == "bulleted_list_item":
                prefix = "  " * depth + "- "
                parts.append(f"{prefix}{text}")
            elif block_type == "numbered_list_item":
                prefix = "  " * depth + "1. "
                parts.append(f"{prefix}{text}")
            elif block_type == "quote":
                parts.append(f"> {text}")
            elif block_type == "code":
                lang = block_data.get("language", "")
                parts.append(f"```{lang}\n{text}\n```")
            elif block_type == "to_do":
                checked = block_data.get("checked", False)
                checkbox = "x" if checked else " "
                parts.append(f"- [{checkbox}] {text}")
            elif block_type == "toggle":
                if text:
                    parts.append(f"<details><summary>{text}</summary>")
            else:
                # Unsupported block types are ignored rather than causing failures.
                if text:
                    parts.append(text)

            if block.get("has_children"):
                try:
                    children = self._list_all_block_children(block["id"])
                    child_parts = self._flatten_blocks_to_markdown(children, depth=depth + 1)
                    parts.extend(child_parts)
                    if block_type == "toggle":
                        parts.append("</details>")
                except Exception as e:
                    logger.warning("Could not fetch child blocks for %s: %s", block.get("id"), e)

        return parts

    def _get_page_content(self, page_id: str) -> str:
        """Get page content as markdown-ish text."""
        try:
            blocks = self._list_all_block_children(page_id)
            parts = self._flatten_blocks_to_markdown(blocks)
            return "\n\n".join(part for part in parts if part.strip())
        except Exception as e:
            logger.error("Error getting content for page %s: %s", page_id, e)
            return ""

    def _content_to_blocks(self, content: str, max_chunk_size: int = NOTION_BLOCK_TEXT_LIMIT) -> List[Dict]:
        """
        Convert memory content into simple Notion paragraph blocks.

        Keeps things intentionally conservative:
        - paragraph blocks only
        - chunk text under Notion size limits
        - max 100 blocks per append request
        """
        if not content:
            return []

        blocks: List[Dict[str, Any]] = []
        paragraphs = content.split("\n\n")

        for para in paragraphs:
            para = para.rstrip()
            if not para:
                continue

            remaining = para
            while remaining:
                chunk = remaining[:max_chunk_size]
                remaining = remaining[max_chunk_size:]

                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": chunk},
                                }
                            ]
                        },
                    }
                )

                if len(blocks) >= self.NOTION_MAX_APPEND_BLOCKS:
                    return blocks

        return blocks

    def _archive_all_top_level_blocks(self, page_id: str) -> None:
        """
        Archive all top-level child blocks on a Notion page.

        This prevents duplicate append growth. It does not recursively delete children;
        archiving the parent top-level block is usually sufficient from Notion's perspective.
        """
        blocks = self._list_all_block_children(page_id)
        for block in blocks:
            block_id = block.get("id")
            if not block_id:
                continue
            try:
                self._retry_with_backoff(
                    self.notion.blocks.update,
                    block_id=block_id,
                    archived=True,
                )
            except Exception as e:
                logger.warning("Could not archive block %s on page %s: %s", block_id, page_id, e)

    def _append_blocks_in_batches(self, page_id: str, blocks: List[Dict[str, Any]]) -> None:
        """Append blocks to a Page in batches respecting Notion's 100-child limit."""
        if not blocks:
            return

        for i in range(0, len(blocks), self.NOTION_MAX_APPEND_BLOCKS):
            batch = blocks[i : i + self.NOTION_MAX_APPEND_BLOCKS]
            self._retry_with_backoff(
                self.notion.blocks.children.append,
                block_id=page_id,
                children=batch,
            )

    # -------------------------------------------------------------------------
    # Parsing
    # -------------------------------------------------------------------------

    def _parse_page(self, page: dict) -> Optional[Dict[str, Any]]:
        """Parse a Notion page into hub-ready data."""
        try:
            page_id = page["id"]
            properties = page.get("properties", {})
            title = self._extract_title(properties)
            content = self._get_page_content(page_id)
            metadata = {
                "notion_url": page.get("url", ""),
                "notion_parent": page.get("parent"),
                "notion_properties": self._extract_property_metadata(properties),
            }

            content_hash = self._compute_hash(title=title, content=content, metadata=metadata)

            return {
                "id": page_id,
                "title": title,
                "content": content,
                "content_hash": content_hash,
                "url": page.get("url", ""),
                "created": page.get("created_time", ""),
                "edited": page.get("last_edited_time", ""),
                "metadata": metadata,
            }
        except Exception as e:
            logger.error("Error parsing page: %s", e)
            return None

    def get_all_pages(self) -> List[Dict[str, Any]]:
        """Get all Notion pages from the configured database."""
        pages: List[Dict[str, Any]] = []
        start_cursor: Optional[str] = None

        try:
            while True:
                kwargs = {"database_id": self.notion.database_id}
                if start_cursor:
                    kwargs["start_cursor"] = start_cursor

                response = self._retry_with_backoff(self.notion.databases.query, **kwargs)

                for page in response.get("results", []):
                    parsed = self._parse_page(page)
                    if parsed:
                        pages.append(parsed)

                if not response.get("has_more"):
                    break
                start_cursor = response.get("next_cursor")
        except Exception as e:
            logger.error("Error fetching Notion pages: %s", e)

        return pages

    # -------------------------------------------------------------------------
    # Sync: Notion -> Supabase
    # -------------------------------------------------------------------------

    def sync_to_supabase(self, force: bool = False) -> SyncResult:
        """Sync Notion pages into Supabase hub."""
        stats = self._reset_stats()
        start_time = time.time()
        direction = SyncDirection.NOTION_TO_SUPABASE

        logger.info("Starting sync: Notion -> Supabase")
        pages = self.get_all_pages()
        logger.info("Found %s pages in Notion", len(pages))

        for page in pages:
            page_id = page["id"]
            incoming_hash = page["content_hash"]

            try:
                existing_hash = self.synced_pages.get(page_id)

                if not force and existing_hash and existing_hash == incoming_hash:
                    stats["skipped"] += 1
                    logger.debug("Skipping unchanged page: %s", page["title"])
                    continue

                def upsert_mem():
                    return self.client.upsert_memory_from_sync(
                        provider="notion",
                        external_id=page_id,
                        title=page["title"],
                        content=page["content"],
                        tags=["notion"],
                        metadata=page.get("metadata", {}),
                        remote_updated_at=page.get("edited"),  # fixed key
                    )

                result = self._retry_with_backoff(upsert_mem)

                # Best effort interpretation of the upsert result
                # Expected patterns may vary by your client implementation.
                memory_id = None
                if isinstance(result, dict):
                    memory_id = result.get("id") or result.get("memory_id")
                    action = result.get("action")  # e.g. created / updated / skipped
                    if action == "created":
                        stats["created"] += 1
                    elif action == "updated":
                        stats["updated"] += 1
                    elif action == "skipped":
                        stats["skipped"] += 1
                    else:
                        # fallback
                        stats["updated"] += 1
                else:
                    stats["updated"] += 1

                self.synced_pages[page_id] = incoming_hash
                self._safe_log_event(
                    memory_id=memory_id,
                    event_type="synced",
                    actor_type="adapter",
                    payload={
                        "direction": direction.value,
                        "provider": "notion",
                        "external_id": page_id,
                    },
                    after_hash=incoming_hash,
                )

                logger.debug("Synced page: %s", page["title"])

            except Exception as e:
                logger.error("Error syncing page '%s': %s", page.get("title", "unknown"), e)
                stats["errors"].append(f"Sync error: {page.get('title', 'unknown')} - {e}")
                stats["failed"] += 1

        duration = time.time() - start_time
        synced_total = stats["created"] + stats["updated"]

        status = SyncStatus.SUCCESS
        if stats["failed"] and synced_total:
            status = SyncStatus.PARTIAL
        elif stats["failed"] and not synced_total:
            status = SyncStatus.FAILED
        elif synced_total == 0 and stats["skipped"] > 0:
            status = SyncStatus.SKIPPED

        return SyncResult(
            direction=direction,
            status=status,
            synced=synced_total,
            created=stats["created"],
            updated=stats["updated"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            errors=stats["errors"],
            duration_seconds=duration,
        )

    # -------------------------------------------------------------------------
    # Sync: Supabase -> Notion
    # -------------------------------------------------------------------------

    def _get_memory_by_id(self, memory_id: str) -> Optional[dict]:
        """Retrieve one memory by ID using whatever client method is available."""
        try:
            if hasattr(self.client, "get_memory"):
                return self.client.get_memory(memory_id)
            if hasattr(self.client, "get_memories"):
                memories = self.client.get_memories(limit=1000)
                for memory in memories:
                    if memory.get("id") == memory_id:
                        return memory
        except Exception as e:
            logger.error("Could not retrieve memory %s: %s", memory_id, e)
        return None

    def _build_title_property_payload(self, page_obj: dict, title: str) -> dict:
        """
        Build a pages.update property payload for the title property.

        Tries to detect the actual title property name from the page object.
        """
        properties = page_obj.get("properties", {})
        title_prop_name = None

        for prop_name, prop_value in properties.items():
            if prop_value.get("type") == "title":
                title_prop_name = prop_name
                break

        if not title_prop_name:
            # Fallback to "Name", then "title".
            title_prop_name = "Name" if "Name" in properties else "title"

        return {
            title_prop_name: {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": (title or "Untitled")[:2000]},
                    }
                ]
            }
        }

    def sync_from_supabase(self, force: bool = False) -> SyncResult:
        """
        Sync hub memories back into Notion.

        This uses sync_links(provider='notion') as the authoritative mapping,
        rather than relying on memory.source string conventions.
        """
        stats = self._reset_stats()
        start_time = time.time()
        direction = SyncDirection.SUPABASE_TO_NOTION

        logger.info("Starting sync: Supabase -> Notion")

        try:
            links = self.client.get_all_sync_links(provider="notion")
            logger.info("Found %s Notion sync links", len(links))

            for link in links:
                try:
                    sync_link_id = link.get("id")
                    memory_id = link.get("memory_id")
                    page_id = link.get("external_id")
                    last_synced_hash = link.get("last_synced_hash")

                    if not memory_id or not page_id:
                        stats["failed"] += 1
                        stats["errors"].append(f"Invalid sync_link: {link}")
                        continue

                    memory = self._get_memory_by_id(memory_id)
                    if not memory:
                        stats["failed"] += 1
                        stats["errors"].append(f"Memory not found for sync_link {sync_link_id}")
                        continue

                    title = memory.get("title", "Untitled")
                    content = memory.get("content", "") or ""
                    metadata = memory.get("metadata", {}) or {}
                    current_hash = self._compute_hash(title=title, content=content, metadata=metadata)

                    if not force and last_synced_hash and current_hash == last_synced_hash:
                        stats["skipped"] += 1
                        logger.debug("Skipping unchanged memory %s -> %s", memory_id, page_id)
                        continue

                    # Optional remote conflict check.
                    # We compare current Notion content hash to last_synced_hash before overwriting.
                    try:
                        remote_page = self._retry_with_backoff(self.notion.pages.retrieve, page_id=page_id)
                        parsed_remote = self._parse_page(remote_page)
                        remote_hash = parsed_remote["content_hash"] if parsed_remote else None

                        if (
                            not force
                            and remote_hash
                            and last_synced_hash
                            and remote_hash != last_synced_hash
                            and current_hash != last_synced_hash
                        ):
                            # Both sides changed since last sync -> conflict.
                            if hasattr(self.client, "create_conflict"):
                                self.client.create_conflict(
                                    memory_id=memory_id,
                                    provider_a="supabase",
                                    provider_b="notion",
                                    hash_a=current_hash,
                                    hash_b=remote_hash,
                                    title_a=title,
                                    title_b=(parsed_remote or {}).get("title"),
                                    content_a=content,
                                    content_b=(parsed_remote or {}).get("content"),
                                )
                            self._safe_log_event(
                                memory_id=memory_id,
                                sync_link_id=sync_link_id,
                                event_type="conflict_detected",
                                actor_type="adapter",
                                payload={
                                    "direction": direction.value,
                                    "provider": "notion",
                                    "external_id": page_id,
                                },
                                before_hash=last_synced_hash,
                                after_hash=current_hash,
                            )
                            stats["skipped"] += 1
                            logger.warning("Conflict detected for memory %s / page %s; skipped overwrite", memory_id, page_id)
                            continue
                    except Exception as e:
                        logger.warning("Remote conflict precheck failed for page %s: %s", page_id, e)
                        # If we can't verify remote state, skip unless force is True
                        if not force:
                            stats["skipped"] += 1
                            logger.warning("Skipping overwrite for %s due to failed conflict check", page_id)
                            continue

                    # Update title first
                    page_obj = self._retry_with_backoff(self.notion.pages.retrieve, page_id=page_id)
                    title_properties = self._build_title_property_payload(page_obj, title)

                    self._retry_with_backoff(
                        self.notion.pages.update,
                        page_id=page_id,
                        properties=title_properties,
                    )

                    # Replace body safely: archive existing blocks, then append fresh blocks.
                    # If this fails after archiving, we could restore but for now we log and continue.
                    new_blocks = self._content_to_blocks(content)
                    try:
                        self._archive_all_top_level_blocks(page_id)
                        self._append_blocks_in_batches(page_id, new_blocks)
                    except Exception as e:
                        logger.error("Failed to update blocks for page %s after archiving: %s", page_id, e)
                        stats["failed"] += 1
                        stats["errors"].append(f"Block update failed for {page_id}: {e}")
                        continue

                    # Persist updated sync hash
                    if hasattr(self.client, "update_sync_link"):
                        self.client.update_sync_link(
                            sync_link_id,
                            last_synced_hash=current_hash,
                            last_synced_at=datetime.utcnow().isoformat(),
                            remote_updated_at=datetime.utcnow().isoformat(),
                        )

                    self.synced_pages[page_id] = current_hash
                    stats["updated"] += 1

                    self._safe_log_event(
                        memory_id=memory_id,
                        sync_link_id=sync_link_id,
                        event_type="synced",
                        actor_type="adapter",
                        payload={
                            "direction": direction.value,
                            "provider": "notion",
                            "external_id": page_id,
                        },
                        before_hash=last_synced_hash,
                        after_hash=current_hash,
                    )

                    logger.debug("Updated Notion page %s from memory %s", page_id, memory_id)

                except Exception as e:
                    logger.error("Error updating Notion from sync_link %s: %s", link.get("id"), e)
                    stats["errors"].append(f"Update error for page {link.get('external_id')} - {e}")
                    stats["failed"] += 1

        except Exception as e:
            logger.error("Error fetching Notion sync links from Supabase: %s", e)
            stats["errors"].append(f"Supabase error: {e}")
            stats["failed"] += 1

        duration = time.time() - start_time
        synced_total = stats["created"] + stats["updated"]

        status = SyncStatus.SUCCESS
        if stats["failed"] and synced_total:
            status = SyncStatus.PARTIAL
        elif stats["failed"] and not synced_total:
            status = SyncStatus.FAILED
        elif synced_total == 0 and stats["skipped"] > 0:
            status = SyncStatus.SKIPPED

        return SyncResult(
            direction=direction,
            status=status,
            synced=synced_total,
            created=stats["created"],
            updated=stats["updated"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            errors=stats["errors"],
            duration_seconds=duration,
        )

    # -------------------------------------------------------------------------
    # Orchestration
    # -------------------------------------------------------------------------

    def sync_bidirectional(self, force: bool = False) -> Dict[str, SyncResult]:
        """Run full bi-directional sync."""
        results: Dict[str, SyncResult] = {}

        results["notion_to_supabase"] = self.sync_to_supabase(force=force)
        results["supabase_to_notion"] = self.sync_from_supabase(force=force)

        return results


def create_notion_sync(
    notion_client,
    memory_client,
    direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
) -> NotionSync:
    """Factory function."""
    return NotionSync(
        notion_client=notion_client,
        memory_client=memory_client,
        direction=direction,
    )
