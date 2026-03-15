"""
Notion Sync for Memory Bridge
Two-way sync between Notion and Supabase
"""
from typing import List, Dict, Optional
from datetime import datetime

class NotionSync:
    """Sync Notion pages to/from Supabase"""
    
    def __init__(self, notion_client, memory_client):
        self.notion = notion_client
        self.client = memory_client
    
    def get_all_pages(self) -> List[Dict]:
        """Get all pages from Notion"""
        try:
            response = self.notion.databases.query(
                database_id=self.notion.database_id
            )
            return [self._parse_page(p) for p in response.get('results', [])]
        except Exception as e:
            print(f"Error fetching Notion pages: {e}")
            return []
    
    def _parse_page(self, page: dict) -> Dict:
        """Parse a Notion page"""
        page_id = page['id']
        
        # Extract title
        title = self._extract_title(page.get('properties', {}))
        
        # Get content
        content = self._get_page_content(page_id)
        
        return {
            'id': page_id,
            'title': title,
            'content': content,
            'url': page.get('url', ''),
            'created': page.get('created_time', ''),
            'edited': page.get('last_edited_time', '')
        }
    
    def _extract_title(self, properties: dict) -> str:
        """Extract title from Notion properties"""
        for prop_name, prop_value in properties.items():
            if prop_value.get('type') == 'title':
                title_array = prop_value.get('title', [])
                if title_array:
                    return title_array[0].get('plain_text', 'Untitled')
        return 'Untitled'
    
    def _get_page_content(self, page_id: str) -> str:
        """Get page content as markdown"""
        try:
            blocks = self.notion.blocks.children.list(block_id=page_id)
            content_parts = []
            
            for block in blocks.get('results', []):
                block_type = block.get('type')
                block_data = block.get(block_type, {})
                
                # Extract text
                text = self._extract_text(block_data.get('rich_text', []))
                
                if not text:
                    continue
                
                # Convert to markdown
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
            print(f"Error getting content: {e}")
            return ""
    
    def _extract_text(self, rich_text: list) -> str:
        """Extract plain text from rich text"""
        return ''.join([t.get('plain_text', '') for t in rich_text])
    
    def sync_to_supabase(self) -> Dict:
        """Sync Notion pages to Supabase"""
        pages = self.get_all_pages()
        
        synced = 0
        for page in pages:
            try:
                # Create memory from Notion page
                self.client.create_memory(
                    title=page['title'],
                    content=page['content'],
                    source=f"notion:{page['id']}",
                    tags=['notion']
                )
                synced += 1
            except Exception as e:
                print(f"Error syncing {page['id']}: {e}")
        
        return {
            'total_pages': len(pages),
            'synced': synced
        }
    
    def sync_from_supabase(self) -> Dict:
        """Sync from Supabase to Notion"""
        # Get memories from Notion source
        memories = self.client.get_memories()
        
        notion_memories = [
            m for m in memories 
            if m.get('source', '').startswith('notion:')
        ]
        
        updated = 0
        for memory in notion_memories:
            page_id = memory['source'].replace('notion:', '')
            
            try:
                # Update Notion page
                self.notion.pages.update(
                    page_id=page_id,
                    properties={
                        'title': {
                            'title': [{'text': {'content': memory['title']}}]
                        }
                    }
                )
                updated += 1
            except Exception as e:
                print(f"Error updating {page_id}: {e}")
        
        return {
            'imported': len(notion_memories),
            'updated': updated
        }


def create_notion_sync(notion_client, memory_client) -> NotionSync:
    """Factory function"""
    return NotionSync(notion_client, memory_client)
