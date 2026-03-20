"""
Obsidian Sync - Improved Production Base
Bi-directional Obsidian <-> Supabase sync with safer conflict handling.

Assumptions about memory_client:
- upsert_memory_from_sync(...)
- get_all_sync_links(provider: str) -> list[dict]
- update_sync_link(sync_link_id, **kwargs)
- get_memory(memory_id) OR get_memories(limit=...)
- log_memory_event(...)
- create_conflict(...)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SyncDirection(Enum):
    OBSIDIAN_TO_SUPABASE = "obsidian_to_supabase"
    SUPABASE_TO_OBSIDIAN = "supabase_to_obsidian"
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


class SyncError(Exception):
    """Base sync error."""


class ObsidianParseError(SyncError):
    """Error parsing Obsidian file."""


class SupabaseError(SyncError):
    """Error communicating with Supabase."""


class ObsidianSync:
    """
    Improved Obsidian <-> Supabase sync adapter.

    Design:
    - Obsidian notes are external objects.
    - Supabase is the canonical hub.
    - sync_links are the durable mapping layer.
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(
        self,
        vault_path: str,
        memory_client,
        direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
    ):
        self.vault_path = Path(vault_path)
        self.client = memory_client
        self.direction = direction

        # In-memory cache restored from sync_links:
        # external_id (vault-relative path) -> last_synced_hash
        self.synced_files: Dict[str, str] = {}
        self._load_sync_links()

    # -------------------------------------------------------------------------
    # Helpers
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
                links = self.client.get_all_sync_links(provider="obsidian")
                for link in links:
                    external_id = link.get("external_id")
                    last_hash = link.get("last_synced_hash")
                    if external_id and last_hash:
                        self.synced_files[external_id] = last_hash
                logger.info("Loaded %s Obsidian sync links from Supabase", len(links))
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
        """Best-effort memory event logging."""
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

    def _normalize_metadata(self, metadata: Optional[dict]) -> dict:
        """Remove volatile sync keys before hashing/upsert metadata comparison."""
        metadata = dict(metadata or {})

        volatile_keys = {
            "memory_id",
            "bridge_provider",
            "bridge_external_id",
            "last_synced_hash",
            "last_synced_at",
        }
        for key in volatile_keys:
            metadata.pop(key, None)

        return metadata

    def _compute_hash(self, title: str, content: str, metadata: Optional[dict] = None) -> str:
        """Stable content hash using title + content + metadata."""
        payload = {
            "title": title or "",
            "content": content or "",
            "metadata": self._normalize_metadata(metadata),
        }
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _relative_note_id(self, file_path: Path) -> str:
        """Vault-relative path used as stable external_id."""
        return str(file_path.relative_to(self.vault_path)).replace("\\", "/")

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

    # -------------------------------------------------------------------------
    # Parsing / serialization
    # -------------------------------------------------------------------------

    def _parse_note(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Parse a markdown note with frontmatter."""
        try:
            raw = file_path.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)

            metadata = dict(post.metadata) if post.metadata else {}
            title = metadata.get("title", file_path.stem)
            content = post.content or ""

            content_hash = self._compute_hash(
                title=title,
                content=content,
                metadata=metadata,
            )

            return {
                "id": self._relative_note_id(file_path),   # stable external_id
                "path": str(file_path),
                "title": title,
                "content": content,
                "metadata": metadata,
                "content_hash": content_hash,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            }

        except Exception as e:
            logger.error("Error parsing %s: %s", file_path, e)
            return None

    def _build_frontmatter_post(
        self,
        memory: dict,
        external_id: str,
        last_synced_hash: Optional[str] = None,
    ) -> frontmatter.Post:
        """
        Build an Obsidian note with stable sync metadata in frontmatter.
        """
        metadata = dict(memory.get("metadata", {}) or {})
        metadata = self._normalize_metadata(metadata)

        metadata["title"] = memory.get("title", "Untitled")
        metadata["tags"] = memory.get("tags", [])
        metadata["memory_id"] = memory.get("id")
        metadata["bridge_provider"] = "obsidian"
        metadata["bridge_external_id"] = external_id
        metadata["last_synced_hash"] = last_synced_hash or memory.get("content_hash")
        metadata["last_synced_at"] = datetime.utcnow().isoformat()
        metadata["created"] = memory.get("created_at", metadata.get("created"))

        return frontmatter.Post(memory.get("content", "") or "", **metadata)

    def _serialize_post(self, post: frontmatter.Post) -> str:
        """Serialize frontmatter post to markdown string."""
        return frontmatter.dumps(post)

    # -------------------------------------------------------------------------
    # Vault scan
    # -------------------------------------------------------------------------

    def get_all_notes(self) -> List[Dict[str, Any]]:
        """Get all markdown notes in vault."""
        notes: List[Dict[str, Any]] = []

        if not self.vault_path.exists():
            logger.error("Vault path does not exist: %s", self.vault_path)
            return notes

        try:
            for md_file in self.vault_path.rglob("*.md"):
                # Skip hidden files/folders
                if any(part.startswith(".") for part in md_file.parts):
                    continue
                # Skip templates folders
                if any(part.lower() == "templates" for part in md_file.parts):
                    continue

                note = self._parse_note(md_file)
                if note:
                    notes.append(note)

        except Exception as e:
            logger.error("Error scanning vault: %s", e)

        return notes

    # -------------------------------------------------------------------------
    # Sync: Obsidian -> Supabase
    # -------------------------------------------------------------------------

    def sync_to_supabase(self, force: bool = False) -> SyncResult:
        """Sync Obsidian vault into Supabase hub."""
        stats = self._reset_stats()
        start_time = time.time()
        direction = SyncDirection.OBSIDIAN_TO_SUPABASE

        logger.info("Starting sync: Obsidian -> Supabase")

        notes = self.get_all_notes()
        logger.info("Found %s notes in vault", len(notes))

        for note in notes:
            note_id = note["id"]
            note_hash = note["content_hash"]

            try:
                if not force and self.synced_files.get(note_id) == note_hash:
                    stats["skipped"] += 1
                    logger.debug("Skipping unchanged note: %s", note["title"])
                    continue

                def upsert_mem():
                    return self.client.upsert_memory_from_sync(
                        provider="obsidian",
                        external_id=note_id,
                        title=note["title"],
                        content=note["content"],
                        tags=note["metadata"].get("tags", []),
                        metadata=self._normalize_metadata(note["metadata"]),
                        external_path=note["id"],          # fixed
                        remote_updated_at=note["modified"], # fixed
                    )

                result = self._retry_with_backoff(upsert_mem)

                memory_id = None
                action = None

                if isinstance(result, dict):
                    memory_id = result.get("id") or result.get("memory_id")
                    action = result.get("action")

                if action == "created":
                    stats["created"] += 1
                elif action == "updated":
                    stats["updated"] += 1
                elif action == "skipped":
                    stats["skipped"] += 1
                else:
                    # fallback if client doesn't return action
                    stats["updated"] += 1

                # Best effort: write canonical IDs back into frontmatter
                try:
                    file_path = Path(note["path"])
                    post = frontmatter.loads(file_path.read_text(encoding="utf-8"))

                    if memory_id:
                        post["memory_id"] = memory_id
                    post["bridge_provider"] = "obsidian"
                    post["bridge_external_id"] = note_id
                    post["last_synced_hash"] = note_hash
                    post["last_synced_at"] = datetime.utcnow().isoformat()

                    serialized = self._serialize_post(post)
                    current_raw = file_path.read_text(encoding="utf-8")
                    if serialized != current_raw:
                        file_path.write_text(serialized, encoding="utf-8")
                except Exception as e:
                    logger.warning("Could not write sync metadata to %s: %s", note_id, e)

                self.synced_files[note_id] = note_hash

                self._safe_log_event(
                    memory_id=memory_id,
                    event_type="synced",
                    actor_type="adapter",
                    payload={
                        "direction": direction.value,
                        "provider": "obsidian",
                        "external_id": note_id,
                    },
                    after_hash=note_hash,
                )

                logger.debug("Synced note: %s", note["title"])

            except Exception as e:
                logger.error("Error syncing %s: %s", note.get("title", "unknown"), e)
                stats["errors"].append(f"Sync error: {note.get('title', 'unknown')} - {e}")
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
    # Sync: Supabase -> Obsidian
    # -------------------------------------------------------------------------

    def sync_from_supabase(self, force: bool = False) -> SyncResult:
        """
        Sync hub memories back to Obsidian.

        Uses sync_links(provider='obsidian') instead of legacy source string logic.
        """
        stats = self._reset_stats()
        start_time = time.time()
        direction = SyncDirection.SUPABASE_TO_OBSIDIAN

        logger.info("Starting sync: Supabase -> Obsidian")

        self.vault_path.mkdir(parents=True, exist_ok=True)

        try:
            links = self.client.get_all_sync_links(provider="obsidian")
            logger.info("Found %s Obsidian sync links", len(links))

            for link in links:
                try:
                    sync_link_id = link.get("id")
                    memory_id = link.get("memory_id")
                    external_id = link.get("external_id")  # vault-relative path
                    last_synced_hash = link.get("last_synced_hash")

                    if not memory_id or not external_id:
                        stats["failed"] += 1
                        stats["errors"].append(f"Invalid sync_link: {link}")
                        continue

                    memory = self._get_memory_by_id(memory_id)
                    if not memory:
                        stats["failed"] += 1
                        stats["errors"].append(f"Memory not found for sync_link {sync_link_id}")
                        continue

                    file_path = self.vault_path / external_id
                    file_path.parent.mkdir(parents=True, exist_ok=True)

                    title = memory.get("title", "Untitled")
                    content = memory.get("content", "") or ""
                    metadata = self._normalize_metadata(memory.get("metadata", {}) or {})
                    current_hash = self._compute_hash(
                        title=title,
                        content=content,
                        metadata=metadata,
                    )

                    if not force and last_synced_hash and current_hash == last_synced_hash:
                        stats["skipped"] += 1
                        logger.debug("Skipping unchanged memory %s -> %s", memory_id, external_id)
                        continue

                    # Local conflict check:
                    # if file exists and local hash != last_synced_hash while hub hash != last_synced_hash,
                    # both changed since last sync -> conflict
                    if file_path.exists():
                        local_note = self._parse_note(file_path)
                        local_hash = local_note["content_hash"] if local_note else None

                        if (
                            not force
                            and local_hash
                            and last_synced_hash
                            and local_hash != last_synced_hash
                            and current_hash != last_synced_hash
                        ):
                            if hasattr(self.client, "create_conflict"):
                                self.client.create_conflict(
                                    memory_id=memory_id,
                                    provider_a="supabase",
                                    provider_b="obsidian",
                                    hash_a=current_hash,
                                    hash_b=local_hash,
                                    title_a=title,
                                    title_b=(local_note or {}).get("title"),
                                    content_a=content,
                                    content_b=(local_note or {}).get("content"),
                                )

                            self._safe_log_event(
                                memory_id=memory_id,
                                sync_link_id=sync_link_id,
                                event_type="conflict_detected",
                                actor_type="adapter",
                                payload={
                                    "direction": direction.value,
                                    "provider": "obsidian",
                                    "external_id": external_id,
                                },
                                before_hash=last_synced_hash,
                                after_hash=current_hash,
                            )

                            stats["skipped"] += 1
                            logger.warning(
                                "Conflict detected for memory %s / note %s; skipped overwrite",
                                memory_id,
                                external_id,
                            )
                            continue

                    post = self._build_frontmatter_post(
                        memory=memory,
                        external_id=external_id,
                        last_synced_hash=current_hash,
                    )
                    new_content = self._serialize_post(post)

                    should_write = True
                    if file_path.exists():
                        existing_content = file_path.read_text(encoding="utf-8")
                        if existing_content == new_content:
                            should_write = False
                            stats["skipped"] += 1

                    if should_write:
                        def write_file():
                            file_path.write_text(new_content, encoding="utf-8")

                        self._retry_with_backoff(write_file)
                        stats["updated"] += 1
                        logger.debug("Written: %s", external_id)

                    if hasattr(self.client, "update_sync_link"):
                        self.client.update_sync_link(
                            sync_link_id,
                            last_synced_hash=current_hash,
                            last_synced_at=datetime.utcnow().isoformat(),
                            remote_updated_at=datetime.utcnow().isoformat(),
                            external_path=external_id,
                        )

                    self.synced_files[external_id] = current_hash

                    self._safe_log_event(
                        memory_id=memory_id,
                        sync_link_id=sync_link_id,
                        event_type="synced",
                        actor_type="adapter",
                        payload={
                            "direction": direction.value,
                            "provider": "obsidian",
                            "external_id": external_id,
                        },
                        before_hash=last_synced_hash,
                        after_hash=current_hash,
                    )

                except Exception as e:
                    logger.error("Error writing sync_link %s: %s", link.get("id"), e)
                    stats["errors"].append(f"Write error for {link.get('external_id')} - {e}")
                    stats["failed"] += 1

        except Exception as e:
            logger.error("Error fetching from Supabase: %s", e)
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

        # Pull hub -> local first
        results["supabase_to_obsidian"] = self.sync_from_supabase(force=force)

        # Then push local -> hub
        results["obsidian_to_supabase"] = self.sync_to_supabase(force=force)

        return results


def create_obsidian_sync(
    vault_path: str,
    memory_client,
    direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
) -> ObsidianSync:
    """Factory function."""
    return ObsidianSync(
        vault_path=vault_path,
        memory_client=memory_client,
        direction=direction,
    )
