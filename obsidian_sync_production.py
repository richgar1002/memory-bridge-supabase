"""
Obsidian Sync - Full Production Version
Bi-directional sync with comprehensive error handling
"""
import os
import frontmatter
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
    """Result of a sync operation"""
    direction: SyncDirection
    status: SyncStatus
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0


class SyncError(Exception):
    """Base sync error"""
    pass


class ObsidianParseError(SyncError):
    """Error parsing Obsidian file"""
    pass


class SupabaseError(SyncError):
    """Error communicating with Supabase"""
    pass


class ObsidianSync:
    """
    Production-ready Obsidian ↔ Supabase sync
    """
    
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    def __init__(self, vault_path: str, memory_client, direction: SyncDirection = SyncDirection.BIDIRECTIONAL):
        self.vault_path = Path(vault_path)
        self.client = memory_client
        self.direction = direction
        
        # Track sync state
        self.synced_files: Dict[str, str] = {}  # path -> content_hash
        
        # Statistics
        self.stats = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'failed': 0,
            'errors': []
        }
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute function with retry logic"""
        last_error = None
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt}/{self.MAX_RETRIES} failed: {e}")
                
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * (2 ** (attempt - 1))
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
        
        raise last_error
    
    def _parse_note(self, file_path: Path) -> Optional[Dict]:
        """Parse a markdown note with error handling"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            post = frontmatter.loads(content)
            metadata = dict(post.metadata) if post.metadata else {}
            
            title = metadata.get('title', file_path.stem)
            content_hash = hashlib.md5(post.content.encode()).hexdigest()
            
            return {
                'id': str(file_path.relative_to(self.vault_path)),
                'path': str(file_path),
                'title': title,
                'content': post.content,
                'metadata': metadata,
                'content_hash': content_hash,
                'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            self.stats['errors'].append(f"Parse error: {file_path} - {e}")
            self.stats['failed'] += 1
            return None
    
    def get_all_notes(self) -> List[Dict]:
        """Get all notes with error handling"""
        notes = []
        
        if not self.vault_path.exists():
            logger.error(f"Vault path does not exist: {self.vault_path}")
            return notes
        
        try:
            for md_file in self.vault_path.rglob("*.md"):
                # Skip hidden files and templates
                if any(part.startswith('.') for part in md_file.parts):
                    continue
                if 'templates' in md_file.parts:
                    continue
                
                note = self._parse_note(md_file)
                if note:
                    notes.append(note)
                    
        except Exception as e:
            logger.error(f"Error scanning vault: {e}")
            self.stats['errors'].append(f"Vault scan error: {e}")
        
        return notes
    
    def sync_to_supabase(self, force: bool = False) -> SyncResult:
        """Sync Obsidian vault to Supabase"""
        start_time = time.time()
        direction = SyncDirection.OBSIDIAN_TO_SUPABASE
        
        logger.info(f"Starting sync: Obsidian → Supabase")
        
        notes = self.get_all_notes()
        logger.info(f"Found {len(notes)} notes in vault")
        
        for note in notes:
            try:
                note_id = note['id']
                
                # Check if changed (skip if not forced)
                if not force and note_id in self.synced_files:
                    if self.synced_files[note_id] == note['content_hash']:
                        self.stats['skipped'] += 1
                        continue
                
                # Create memory in Supabase
                def create_mem():
                    return self.client.create_memory(
                        title=note['title'],
                        content=note['content'],
                        tags=note['metadata'].get('tags', []),
                        source=f"obsidian:{note_id}"
                    )
                
                self._retry_with_backoff(create_mem)
                
                self.synced_files[note_id] = note['content_hash']
                self.stats['created'] += 1
                logger.debug(f"Synced: {note['title']}")
                
            except Exception as e:
                logger.error(f"Error syncing {note.get('title', 'unknown')}: {e}")
                self.stats['errors'].append(f"Sync error: {note.get('title')} - {e}")
                self.stats['failed'] += 1
        
        duration = time.time() - start_time
        
        status = SyncStatus.SUCCESS
        if self.stats['failed'] > 0:
            status = SyncStatus.PARTIAL if self.stats['created'] > 0 else SyncStatus.FAILED
        
        return SyncResult(
            direction=direction,
            status=status,
            synced=self.stats['created'],
            skipped=self.stats['skipped'],
            failed=self.stats['failed'],
            errors=self.stats['errors'],
            duration_seconds=duration
        )
    
    def sync_from_supabase(self) -> SyncResult:
        """Sync from Supabase to Obsidian"""
        start_time = time.time()
        direction = SyncDirection.SUPABASE_TO_OBSIDIAN
        
        logger.info(f"Starting sync: Supabase → Obsidian")
        
        # Ensure vault directory exists
        self.vault_path.mkdir(parents=True, exist_ok=True)
        
        try:
            # Get memories from Obsidian source
            all_memories = self.client.get_memories(limit=1000)
            
            obsidian_memories = [
                m for m in all_memories 
                if m.get('source', '').startswith('obsidian:')
            ]
            
            logger.info(f"Found {len(obsidian_memories)} Obsidian memories")
            
            for memory in obsidian_memories:
                try:
                    source_id = memory['source'].replace('obsidian:', '')
                    file_path = self.vault_path / source_id
                    
                    # Create parent directories
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Build frontmatter
                    frontmatter_content = f"""---
title: {memory['title']}
tags: {memory.get('tags', [])}
source: {memory['source']}
created: {memory.get('created_at', '')}
---

{memory['content']}
"""
                    
                    # Check if file needs updating
                    should_write = True
                    if file_path.exists():
                        with open(file_path, 'r', encoding='utf-8') as f:
                            existing = f.read()
                        if existing == frontmatter_content:
                            should_write = False
                            self.stats['skipped'] += 1
                    
                    if should_write:
                        def write_file():
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(frontmatter_content)
                        
                        self._retry_with_backoff(write_file)
                        self.stats['updated'] += 1
                        logger.debug(f"Written: {memory['title']}")
                        
                except Exception as e:
                    logger.error(f"Error writing {memory.get('title', 'unknown')}: {e}")
                    self.stats['errors'].append(f"Write error: {memory.get('title')} - {e}")
                    self.stats['failed'] += 1
            
        except Exception as e:
            logger.error(f"Error fetching from Supabase: {e}")
            self.stats['errors'].append(f"Supabase error: {e}")
            self.stats['failed'] += 1
        
        duration = time.time() - start_time
        
        status = SyncStatus.SUCCESS
        if self.stats['failed'] > 0:
            status = SyncStatus.PARTIAL
        
        return SyncResult(
            direction=direction,
            status=status,
            synced=self.stats['updated'],
            skipped=self.stats['skipped'],
            failed=self.stats['failed'],
            errors=self.stats['errors'],
            duration_seconds=duration
        )
    
    def sync_bidirectional(self, force: bool = False) -> Dict[str, SyncResult]:
        """Full bi-directional sync"""
        results = {}
        
        # Reset stats
        self.stats = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0, 'errors': []}
        
        # First: Supabase → Obsidian (brings local files up to date)
        results['to_local'] = self.sync_from_supabase()
        
        # Reset for next direction
        self.stats = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0, 'errors': []}
        
        # Then: Obsidian → Supabase (backs up to cloud)
        results['to_cloud'] = self.sync_to_supabase(force=force)
        
        return results


def create_obsidian_sync(
    vault_path: str, 
    memory_client,
    direction: SyncDirection = SyncDirection.BIDIRECTIONAL
) -> ObsidianSync:
    """Factory function with error handling"""
    return ObsidianSync(vault_path, memory_client, direction)
