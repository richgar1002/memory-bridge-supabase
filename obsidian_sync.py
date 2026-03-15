"""
Obsidian Sync for Memory Bridge
Two-way sync between Obsidian vault and Supabase
"""
import os
import frontmatter
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import hashlib

class ObsidianSync:
    """Sync Obsidian vault to/from Supabase"""
    
    def __init__(self, vault_path: str, memory_client):
        self.vault_path = Path(vault_path)
        self.client = memory_client
        
        # Track sync state
        self.synced_files = {}  # file_path -> last_modified_hash
    
    def get_all_notes(self) -> List[Dict]:
        """Get all markdown notes from vault"""
        notes = []
        
        for md_file in self.vault_path.rglob("*.md"):
            # Skip hidden files and templates
            if any(part.startswith('.') for part in md_file.parts):
                continue
            if 'templates' in md_file.parts:
                continue
            
            try:
                note = self._parse_note(md_file)
                if note:
                    notes.append(note)
            except Exception as e:
                print(f"Error parsing {md_file}: {e}")
        
        return notes
    
    def _parse_note(self, file_path: Path) -> Optional[Dict]:
        """Parse a markdown note"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse frontmatter
            post = frontmatter.loads(content)
            metadata = dict(post.metadata) if post.metadata else {}
            
            # Get title
            title = metadata.get('title', file_path.stem)
            
            # Calculate content hash
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
            print(f"Error reading {file_path}: {e}")
            return None
    
    def sync_to_supabase(self) -> Dict:
        """Sync vault to Supabase"""
        notes = self.get_all_notes()
        
        synced = 0
        skipped = 0
        
        for note in notes:
            # Check if changed
            note_id = note['id']
            
            if note_id in self.synced_files:
                if self.synced_files[note_id] == note['content_hash']:
                    skipped += 1
                    continue
            
            # Create memory
            try:
                memory = self.client.create_memory(
                    title=note['title'],
                    content=note['content'],
                    tags=note['metadata'].get('tags', []),
                    source=f"obsidian:{note['id']}"
                )
                
                self.synced_files[note_id] = note['content_hash']
                synced += 1
                
            except Exception as e:
                print(f"Error syncing {note_id}: {e}")
        
        return {
            'total_notes': len(notes),
            'synced': synced,
            'skipped': skipped
        }
    
    def sync_from_supabase(self, collection_name: str = "Obsidian Imports"):
        """Sync from Supabase to Obsidian"""
        # Get or create collection
        collections = self.client.get_collections()
        collection = None
        
        for c in collections:
            if c.get('name') == collection_name:
                collection = c
                break
        
        if not collection:
            collection = self.client.create_collection(collection_name)
        
        # Get memories from Obsidian source
        memories = self.client.get_memories()
        
        obsidian_memories = [
            m for m in memories 
            if m.get('source', '').startswith('obsidian:')
        ]
        
        # Write to vault
        for memory in obsidian_memories:
            source_id = memory['source'].replace('obsidian:', '')
            file_path = self.vault_path / source_id
            
            # Create directory if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Build frontmatter
            frontmatter_content = f"""---
title: {memory['title']}
tags: {memory.get('tags', [])}
source: {memory.get('source', '')}
created: {memory.get('created_at', '')}
---

{memory['content']}
"""
            
            # Write file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(frontmatter_content)
        
        return {
            'imported': len(obsidian_memories)
        }
    
    def watch_for_changes(self):
        """Watch for file changes (for live sync)"""
        # Could use watchdog library for live sync
        pass


def create_obsidian_sync(vault_path: str, memory_client) -> ObsidianSync:
    """Factory function"""
    return ObsidianSync(vault_path, memory_client)
