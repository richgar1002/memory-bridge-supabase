# Memory Bridge MVP Test Plan

## Goal
Validate that the bridge is safe enough for continued development by proving:
- sync links map correctly
- no duplicate objects are created
- unchanged content is skipped
- conflicts are detected instead of overwritten
- Notion writeback does not silently corrupt data
- Obsidian frontmatter metadata remains stable

## Test Environment
Create a dedicated test setup:
- one Supabase test project or test schema
- one Notion test database
- one Obsidian test vault

Use 3–5 test notes/pages only.

Suggested fixtures:
- note_a.md
- note_b.md
- note_conflict.md

Each should have short, obvious content.

---

## Test Cases

### 1. Obsidian edit only
**Setup:**
1. Create note_a.md in test vault with content "Original content A"
2. Run Obsidian → Supabase sync
3. Verify memory created in Supabase
4. Verify sync_link created for obsidian

**Edit:**
5. Edit note_a.md to "Edited content A"
6. Run Obsidian → Supabase sync

**Verify:**
- Memory updated (not duplicated)
- content_hash changed
- revision incremented
- sync_link updated with new hash

### 2. Notion edit only
**Setup:**
1. Create page in Notion test database with content "Original Notion"
2. Run Notion → Supabase sync
3. Verify memory created
4. Verify sync_link created for notion

**Edit:**
5. Edit page content to "Edited Notion"
6. Run Notion → Supabase sync

**Verify:**
- Memory updated (not duplicated)
- content_hash changed
- revision incremented

### 3. Both edited before sync (Conflict)
**Setup:**
1. Create note_conflict.md with content "Conflict original"
2. Sync Obsidian → Supabase
3. Note ID stored in frontmatter

**Edit BOTH simultaneously:**
4. Edit note_conflict.md to "Obsidian change"
5. Edit the same memory in Supabase dashboard to "Supabase change"
6. Run Obsidian → Supabase sync

**Verify:**
- sync_conflicts table has a new row
- sync_link shows sync_state = 'conflicted'
- Neither version was silently overwritten
- Both content_a and content_b are preserved

### 4. Notion write failure after archive
**Setup:**
1. Sync a Notion page to Supabase
2. Note the page_id

**Simulate failure:**
3. Temporarily break the Notion API key or permissions
4. Run Supabase → Notion sync

**Verify:**
- Page was NOT corrupted
- Existing blocks were archived but new ones failed to append
- Error was logged
- sync_link was NOT updated (hash unchanged)
- No silent data loss

### 5. Same note synced twice with no changes
**Setup:**
1. Create note with content "Stable content"
2. Run Obsidian → Supabase

**Sync again:**
3. Run Obsidian → Supabase again (no changes)

**Verify:**
- Second sync skipped (action = "skipped")
- revision unchanged
- No duplicate memory created
- No duplicate sync_link

---

## Debug Queries

```sql
-- Check sync_links
SELECT id, provider, external_id, memory_id, last_synced_hash, sync_state 
FROM sync_links 
ORDER BY created_at DESC;

-- Check memory revisions
SELECT id, title, content_hash, revision, updated_at 
FROM memories 
ORDER BY updated_at DESC;

-- Check for conflicts
SELECT * FROM sync_conflicts 
WHERE resolution_status = 'open';

-- Check events
SELECT memory_id, event_type, actor_type, before_hash, after_hash, created_at 
FROM memory_events 
ORDER BY created_at DESC LIMIT 20;
```

---

## Success Criteria
- [ ] Test 1: Obsidian edit creates update, not duplicate
- [ ] Test 2: Notion edit creates update, not duplicate  
- [ ] Test 3: Both-edited creates conflict record
- [ ] Test 4: Notion failure doesn't corrupt page
- [ ] Test 5: No-change sync skips correctly

If all 5 pass → Bridge is MVP-ready for continued development.
