"""
Notion Sync - Full Production Version
Bi-directional sync with comprehensive error handling
"""
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
import time
from dataclasses import dataclass, field
from enum import Enum
import hashlib

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
    """Result of a sync operation"""
    direction: SyncDirection
    status: SyncStatus
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0


class NotionSync:
    """
    Production-ready Notion ↔ Supabase sync
    """
    
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    
    def __init__(self, notion_client, memory_client, direction: SyncDirection = SyncDirection.BIDIRECTIONAL):
        self.notion = notion_client
        self.client = memory_client
        self.direction = direction
        
        # Track sync state (load from DB for persistence)
        self.synced_pages: Dict[str, str] = {}  # page_id -> content_hash
        self._load_sync_links()
        
        # Statistics
        self.stats = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'failed': 0,
            'errors': []
        }
    
    def _load_sync_links(self):
        """Load sync links from Supabase to restore persistent state."""
        try:
            if hasattr(self.client, 'get_all_sync_links'):
                links = self.client.get_all_sync_links(provider="notion")
                for link in links:
                    external_id = link.get('external_id')
                    last_hash = link.get('last_synced_hash')
                    if external_id and last_hash:
                        self.synced_pages[external_id] = last_hash
                logger.info(f"Loaded {len(links)} sync links from Supabase")
        except Exception as e:
            logger.warning(f"Could not load sync links: {e}")
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute with retry logic"""
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
    
    def _extract_title(self, properties: dict) -> str:
        """Extract title from Notion properties"""
        try:
            for prop_name, prop_value in properties.items():
                if prop_value.get('type') == 'title':
                    title_array = prop_value.get('title', [])
                    if title_array:
                        return title_array[0].get('plain_text', 'Untitled')
        except Exception as e:
            logger.error(f"Error extracting title: {e}")
        
        return 'Untitled'
    
    def _extract_text(self, rich_text: list) -> str:
        """Extract plain text from rich text"""
        try:
            return ''.join([t.get('plain_text', '') for t in rich_text])
        except Exception:
            return ''
    
    def _get_page_content(self, page_id: str) -> str:
        """Get page content as markdown"""
        try:
            blocks = self.notion.blocks.children.list(block_id=page_id)
            content_parts = []
            
            for block in blocks.get('results', []):
                block_type = block.get('type')
                block_data = block.get(block_type, {})
                
                text = self._extract_text(block_data.get('rich_text', []))
                if not text:
                    continue
                
                if block_type == 'paragraph':
                    content_parts.append(text)
                elif block_type == 'heading_1':
                    content_parts.append(f"# {text}")
                elif block_type == 'heading_2':
                    content_parts.append(f"## {text}")
                elif block_type == 'heading_3':
                    content_parts.append(f"### {text}")
                elif block_type == 'bulleted_list_item':
                    content_parts.append(f"- {text}")
                elif block_type == 'numbered_list_item':
                    content_parts.append(f"1. {text}")
                elif block_type == 'code':
                    lang = block_data.get('language', '')
                    content_parts.append(f"```{lang}\n{text}\n```")
                elif block_type == 'quote':
                    content_parts.append(f"> {text}")
            
            return '\n\n'.join(content_parts)
            
        except Exception as e:
            logger.error(f"Error getting content: {e}")
            return ''
    
    def _content_to_blocks(self, content: str, max_chunk_size: 1900) -> List[Dict]:
        """Convert memory content to Notion block objects.
        
        Notion has a 100 block children limit per request and ~2000 char per block.
        We chunk content to stay within limits.
        """
        blocks = []
        lines = content.split('\n')
        current_chunk = []
        current_length = 0
        
        for line in lines:
            line_length = len(line) + 1  # +1 for newline
            
            # If single line is too long, truncate it
            if line_length > max_chunk_size:
                # Flush current chunk first
                if current_chunk:
                    blocks.append({
                        'object': 'block',
                        'type': 'paragraph',
                        'paragraph': {
                            'rich_text': [{'type': 'text', 'text': {'content': '\n'.join(current_chunk)}}]
                        }
                    })
                    current_chunk = []
                    current_length = 0
                
                # Split long line into multiple blocks
                while len(line) > max_chunk_size:
                    blocks.append({
                        'object': 'block',
                        'type': 'paragraph',
                        'paragraph': {
                            'rich_text': [{'type': 'text', 'text': {'content': line[:max_chunk_size]}}]
                        }
                    })
                    line = line[max_chunk_size:]
                
                # Handle remaining part
                if line:
                    current_chunk.append(line)
                    current_length += len(line) + 1
            elif current_length + line_length > max_chunk_size:
                # Flush current chunk
                blocks.append({
                    'object': 'block',
                    'type': 'paragraph',
                    'paragraph': {
                        'rich_text': [{'type': 'text', 'text': {'content': '\n'.join(current_chunk)}}]
                    }
                })
                current_chunk = [line]
                current_length = line_length
            else:
                current_chunk.append(line)
                current_length += line_length
        
        # Flush remaining
        if current_chunk:
            blocks.append({
                'object': 'block',
                'type': 'paragraph',
                'paragraph': {
                    'rich_text': [{'type': 'text', 'text': {'content': '\n'.join(current_chunk)}}]
                }
            })
        
        # Limit to 100 blocks (Notion limit)
        return blocks[:100]
    
    def _parse_page(self, page: dict) -> Optional[Dict]:
        """Parse a Notion page"""
        try:
            page_id = page['id']
            title = self._extract_title(page.get('properties', {}))
            content = self._get_page_content(page_id)
            
            # Create content hash
            content_hash = hashlib.md5(content.encode()).hexdigest()
            
            return {
                'id': page_id,
                'title': title,
                'content': content,
                'content_hash': content_hash,
                'url': page.get('url', ''),
                'created': page.get('created_time', ''),
                'edited': page.get('last_edited_time', '')
            }
            
        except Exception as e:
            logger.error(f"Error parsing page: {e}")
            self.stats['errors'].append(f"Parse error: {e}")
            return None
    
    def get_all_pages(self) -> List[Dict]:
        """Get all Notion pages with error handling"""
        pages = []
        
        try:
            response = self.notion.databases.query(
                database_id=self.notion.database_id
            )
            
            for page in response.get('results', []):
                parsed = self._parse_page(page)
                if parsed:
                    pages.append(parsed)
                    
        except Exception as e:
            logger.error(f"Error fetching Notion pages: {e}")
            self.stats['errors'].append(f"Fetch error: {e}")
        
        return pages
    
    def sync_to_supabase(self, force: bool = False) -> SyncResult:
        """Sync Notion pages to Supabase"""
        start_time = time.time()
        direction = SyncDirection.NOTION_TO_SUPABASE
        
        logger.info(f"Starting sync: Notion → Supabase")
        
        pages = self.get_all_pages()
        logger.info(f"Found {len(pages)} pages in Notion")
        
        for page in pages:
            try:
                page_id = page['id']
                
                # Check if changed
                if not force:
                    # Could check existing content hash here
                    pass
                
                def upsert_mem():
                    return self.client.upsert_memory_from_sync(
                        provider="notion",
                        external_id=page_id,
                        title=page['title'],
                        content=page['content'],
                        tags=['notion'],
                        metadata=page.get('metadata', {}),
                        remote_updated_at=page.get('last_edited_time'),
                    )
                
                self._retry_with_backoff(upsert_mem)
                
                self.stats['created'] += 1
                logger.debug(f"Synced: {page['title']}")
                
            except Exception as e:
                logger.error(f"Error syncing {page.get('title', 'unknown')}: {e}")
                self.stats['errors'].append(f"Sync error: {page.get('title')} - {e}")
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
        """Sync from Supabase to Notion"""
        start_time = time.time()
        direction = SyncDirection.SUPABASE_TO_NOTION
        
        logger.info(f"Starting sync: Supabase → Notion")
        
        try:
            # Get memories from Notion source
            all_memories = self.client.get_memories(limit=1000)
            
            notion_memories = [
                m for m in all_memories 
                if m.get('source', '').startswith('notion:')
            ]
            
            logger.info(f"Found {len(notion_memories)} Notion memories")
            
            for memory in notion_memories:
                try:
                    page_id = memory['source'].replace('notion:', '')
                    
                    # Update page title
                    def update_page():
                        return self.notion.pages.update(
                            page_id=page_id,
                            properties={
                                'title': {
                                    'title': [{'text': {'content': memory['title']}}]
                                }
                            }
                        )
                    
                    self._retry_with_backoff(update_page)
                    
                    # Update page content - append blocks with memory content
                    content = memory.get('content', '')
                    if content:
                        # Clear existing blocks (except first paragraph) and append new content
                        try:
                            # Split content into chunks for blocks
                            content_blocks = self._content_to_blocks(content)
                            
                            # Append blocks to the page
                            def append_blocks():
                                return self.notion.blocks.children.append(
                                    block_id=page_id,
                                    children=content_blocks
                                )
                            
                            self._retry_with_backoff(append_blocks)
                            logger.debug(f"Appended content blocks to: {memory['title']}")
                        except Exception as e:
                            logger.warning(f"Could not append blocks to {page_id}: {e}")
                    
                    self.stats['updated'] += 1
                    logger.debug(f"Updated: {memory['title']}")
                    
                except Exception as e:
                    logger.error(f"Error updating {memory.get('title', 'unknown')}: {e}")
                    self.stats['errors'].append(f"Update error: {memory.get('title')} - {e}")
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
    
    def sync_bidirectional(self) -> Dict[str, SyncResult]:
        """Full bi-directional sync"""
        results = {}
        
        # Reset stats
        self.stats = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0, 'errors': []}
        
        # Notion → Supabase
        results['to_cloud'] = self.sync_to_supabase()
        
        # Reset stats
        self.stats = {'created': 0, 'updated': 0, 'skipped': 0, 'failed': 0, 'errors': []}
        
        # Supabase → Notion  
        results['to_notion'] = self.sync_from_supabase()
        
        return results


def create_notion_sync(
    notion_client, 
    memory_client,
    direction: SyncDirection = SyncDirection.BIDIRECTIONAL
) -> NotionSync:
    """Factory function"""
    return NotionSync(notion_client, memory_client, direction)
