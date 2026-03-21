# Memory Bridge MVP Test Plan

## Goal
Validate that the bridge is safe enough for continued development by proving the core sync behaviors work correctly.

---

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

### Test 1 — First-time Obsidian → Supabase sync
**Setup:** Create note_a.md in Obsidian:
```markdown
---
title: Note A
tags:
  - test
---

This is note A.
```
**Action:** Run `obsidian_to_supabase`
**Expected:**
- One memory row created in Supabase
- One sync_links row created with `provider = 'obsidian'`, `external_id = note_a.md`
- Memory has correct title, content, content_hash populated
- Obsidian file frontmatter updated with: memory_id, bridge_provider, bridge_external_id, last_synced_hash
**Fail if:** Duplicate memory rows, no sync link, malformed frontmatter

---

### Test 2 — Repeat Obsidian sync with no changes
**Setup:** Use same note_a.md unchanged
**Action:** Run `obsidian_to_supabase` again
**Expected:** Result reports skipped, no new memory, revision unchanged
**Fail if:** Duplicate rows created, revision increments on no-op

---

### Test 3 — Obsidian edit only
**Setup:** Change note_a.md content to:
```markdown
---
title: Note A
tags:
  - test
---

This is note A.
This line was added locally.
```
**Action:** Run `obsidian_to_supabase`
**Expected:** Existing memory updated, same sync link reused, revision increments by 1, content_hash changes, no conflict
**Fail if:** New memory created instead of update, conflict row appears

---

### Test 4 — First-time Notion → Supabase sync
**Setup:** Create Notion page with title "Note B", body "This is note B."
**Action:** Run `notion_to_supabase`
**Expected:** One memory row, one sync link with `provider = 'notion'`, correct title/content stored
**Fail if:** Multiple rows, no sync link, missing data

---

### Test 5 — Repeat Notion sync with no changes
**Setup:** Leave Note B unchanged
**Action:** Run `notion_to_supabase` again
**Expected:** Skipped, no duplicate memory, no revision increment
**Fail if:** Duplicate rows, revision increments unexpectedly

---

### Test 6 — Supabase → Obsidian writeback
**Setup:** Edit Supabase memory for note_a, append "Cloud edit."
**Action:** Run `supabase_to_obsidian`
**Expected:** Local file updated, frontmatter preserved, last_synced_hash updated, content matches Supabase
**Fail if:** Duplicate file, frontmatter keys disappear, partial overwrite

---

### Test 7 — Supabase → Notion writeback
**Setup:** Edit Supabase memory for Note B, append "Cloud edit."
**Action:** Run `supabase_to_notion`
**Expected:** Notion page updated, title preserved, body replaced once, no duplicate block growth, sync link updated
**Fail if:** Content appended repeatedly, page blank, blocks duplicate

---

### Test 8 — Obsidian conflict detection
**Setup:** From synced note, edit Supabase memory content, separately edit local Obsidian note
**Action:** Run `supabase_to_obsidian`
**Expected:** Overwrite skipped, one sync_conflicts row created, local note intact, event logged as conflict_detected
**Fail if:** Local note overwritten, no conflict row, sync link advances anyway

---

### Test 9 — Notion conflict detection
**Setup:** From synced Notion page, edit Supabase memory, separately edit Notion page body
**Action:** Run `supabase_to_notion`
**Expected:** Overwrite skipped, sync_conflicts row created, Notion page unchanged, event logged
**Fail if:** Notion page overwritten silently, no conflict record

---

### Test 10 — Notion failure safety (CRITICAL)
**Setup:** Force Notion write failure after block archive (monkeypatch, temp permission revoke, or inject exception after `_archive_all_top_level_blocks()`)
**Action:** Run `supabase_to_notion`
**Expected:** Failure is logged, sync result is failed/partial, observe whether page content is lost
**Fail if:** Silent data loss with no clear error state
**Why this matters:** Current strategy is archive-then-append — this test tells you if design is acceptable or too risky

---

### Test 11 — Frontmatter churn test
**Setup:** Take synced Obsidian note, run sync repeatedly with no real content change
**Action:** Run `obsidian_to_supabase` → `supabase_to_obsidian` → `obsidian_to_supabase`
**Expected:** No repeated meaningless rewrites, frontmatter stable, no new conflicts, no new revisions
**Fail if:** Metadata-only changes trigger endless sync loops

---

### Test 12 — Deletion behavior sanity check
**Setup:** Delete a synced Obsidian file or Notion page
**Action:** Run sync
**Expected:** One of: item recreated, item skipped with warning, item marked orphaned/pending manually
**Fail if:** Linked memory deleted accidentally, unrelated content overwritten

---

## Assertions to Log for Every Test
For each run, capture:
- memory row count before/after
- sync_links row count before/after
- sync_conflicts row count before/after
- memory revision before/after
- content_hash before/after
- adapter result object
- any emitted errors

---

## Pass Threshold for "Safe Enough to Keep Building"
Call base acceptable if:
- ✅ Tests 1–9 pass
- ✅ Test 10 fails loudly (not silently)
- ✅ Test 11 does not produce sync loops

If that happens, the bridge is good enough for:
- Internal use
- Continued iteration
- Early alpha testing

Not broad public release yet, but definitely real.

---

## Highest-Priority Issue If Tests Fail
If only one thing fails badly, it will probably be:
**Notion destructive rewrite safety**

That is still the most fragile part of the system.

---

## Debug Queries
```sql
-- Check sync_links
SELECT id, provider, external_id, memory_id, last_synced_hash, sync_state 
FROM sync_links ORDER BY created_at DESC;

-- Check memory revisions
SELECT id, title, content_hash, revision, updated_at 
FROM memories ORDER BY updated_at DESC;

-- Check for conflicts
SELECT * FROM sync_conflicts WHERE resolution_status = 'open';

-- Check events
SELECT memory_id, event_type, actor_type, before_hash, after_hash, created_at 
FROM memory_events ORDER BY created_at DESC LIMIT 20;
```
