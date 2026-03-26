"""Tests for Obsidian sync module."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from obsidian_sync import (
    ObsidianSync,
    SyncDirection,
    SyncStatus,
    SyncResult,
    create_obsidian_sync,
)


class TestObsidianSync:
    """Test ObsidianSync class."""

    @pytest.fixture
    def temp_vault(self, tmp_path):
        """Create temporary Obsidian vault."""
        vault = tmp_path / "vault"
        vault.mkdir()
        return str(vault)

    @pytest.fixture
    def sync_client(self, mock_client, temp_vault):
        """Create ObsidianSync with mocked client."""
        return ObsidianSync(
            vault_path=temp_vault, memory_client=mock_client, direction=SyncDirection.BIDIRECTIONAL
        )

    def test_init(self, sync_client, temp_vault):
        """Test sync initialization."""
        assert sync_client.vault_path == Path(temp_vault)
        assert sync_client.direction == SyncDirection.BIDIRECTIONAL

    def test_relative_note_id(self, sync_client, temp_vault):
        """Test relative note ID computation."""
        file_path = Path(temp_vault) / "notes" / "test.md"
        relative_id = sync_client._relative_note_id(file_path)
        assert relative_id == "notes/test.md"

    def test_relative_note_id_windows(self, sync_client, temp_vault):
        """Test relative note ID with Windows paths."""
        file_path = Path(temp_vault) / "sub" / "note.md"
        relative_id = sync_client._relative_note_id(file_path)
        assert "\\" not in relative_id
        assert relative_id == "sub/note.md"

    def test_compute_hash_deterministic(self, sync_client):
        """Test hash computation is deterministic."""
        hash1 = sync_client._compute_hash("Title", "Content", {"key": "value"})
        hash2 = sync_client._compute_hash("Title", "Content", {"key": "value"})
        assert hash1 == hash2

    def test_compute_hash_excludes_volatile_keys(self, sync_client):
        """Test that volatile metadata keys don't affect hash."""
        hash1 = sync_client._compute_hash("Title", "Content", {"last_synced_hash": "old"})
        hash2 = sync_client._compute_hash("Title", "Content", {"last_synced_hash": "new"})
        assert hash1 == hash2

    def test_normalize_metadata(self, sync_client):
        """Test metadata normalization removes volatile keys."""
        metadata = {
            "title": "Test",
            "tags": ["test"],
            "memory_id": "123",
            "bridge_provider": "obsidian",
            "last_synced_hash": "abc",
        }
        normalized = sync_client._normalize_metadata(metadata)
        assert "title" in normalized
        assert "tags" in normalized
        assert "memory_id" not in normalized
        assert "bridge_provider" not in normalized
        assert "last_synced_hash" not in normalized


class TestObsidianSyncParsing:
    """Test note parsing functionality."""

    @pytest.fixture
    def sync_client(self, mock_client, tmp_path):
        """Create ObsidianSync instance."""
        return ObsidianSync(
            vault_path=str(tmp_path),
            memory_client=mock_client,
            direction=SyncDirection.BIDIRECTIONAL,
        )

    def test_parse_note_with_frontmatter(self, sync_client, tmp_path):
        """Test parsing note with YAML frontmatter."""
        note_path = tmp_path / "test.md"
        note_path.write_text("""---
title: Test Note
tags:
  - test
---
This is the content.
""")
        result = sync_client._parse_note(note_path)
        assert result is not None
        assert result["title"] == "Test Note"
        assert result["content"] == "This is the content."
        assert result["content_hash"] is not None

    def test_parse_note_without_frontmatter(self, sync_client, tmp_path):
        """Test parsing note without frontmatter."""
        note_path = tmp_path / "test.md"
        note_path.write_text("Just plain content.")
        result = sync_client._parse_note(note_path)
        assert result is not None
        assert result["title"] == "test"  # Uses filename
        assert result["content"] == "Just plain content."

    def test_parse_note_uses_filename_stem(self, sync_client, tmp_path):
        """Test that title defaults to filename stem."""
        note_path = tmp_path / "my-note.md"
        note_path.write_text("Content without title.")
        result = sync_client._parse_note(note_path)
        assert result["title"] == "my-note"

    def test_parse_invalid_file(self, sync_client, tmp_path):
        """Test handling of invalid file."""
        # Non-existent file
        result = sync_client._parse_note(tmp_path / "nonexistent.md")
        assert result is None


class TestObsidianSyncGetAllNotes:
    """Test get_all_notes functionality."""

    @pytest.fixture
    def sync_client(self, mock_client, tmp_path):
        """Create ObsidianSync instance."""
        return ObsidianSync(
            vault_path=str(tmp_path),
            memory_client=mock_client,
            direction=SyncDirection.BIDIRECTIONAL,
        )

    def test_get_all_notes_empty_vault(self, sync_client):
        """Test getting notes from empty vault."""
        notes = sync_client.get_all_notes()
        assert notes == []

    def test_get_all_notes_with_files(self, sync_client, tmp_path):
        """Test getting notes with markdown files."""
        (tmp_path / "note1.md").write_text("---\ntitle: Note 1\n---\nContent 1")
        (tmp_path / "note2.md").write_text("---\ntitle: Note 2\n---\nContent 2")
        (tmp_path / "note3.txt").write_text("Not a markdown file")

        notes = sync_client.get_all_notes()
        assert len(notes) == 2
        titles = [n["title"] for n in notes]
        assert "Note 1" in titles
        assert "Note 2" in titles

    def test_get_all_notes_skips_hidden(self, sync_client, tmp_path):
        """Test that hidden files are skipped."""
        (tmp_path / "visible.md").write_text("---\ntitle: Visible\n---\nContent")
        (tmp_path / ".hidden.md").write_text("---\ntitle: Hidden\n---\nContent")

        notes = sync_client.get_all_notes()
        assert len(notes) == 1
        assert notes[0]["title"] == "Visible"

    def test_get_all_notes_skips_templates(self, sync_client, tmp_path):
        """Test that templates folder is skipped."""
        (tmp_path / "note.md").write_text("---\ntitle: Main\n---\nContent")
        templates = tmp_path / "templates"
        templates.mkdir()
        (templates / "template.md").write_text("---\ntitle: Template\n---\nContent")

        notes = sync_client.get_all_notes()
        assert len(notes) == 1
        assert notes[0]["title"] == "Main"


class TestSyncDirection:
    """Test SyncDirection enum."""

    def test_sync_direction_values(self):
        """Test SyncDirection enum values."""
        assert SyncDirection.OBSIDIAN_TO_SUPABASE.value == "obsidian_to_supabase"
        assert SyncDirection.SUPABASE_TO_OBSIDIAN.value == "supabase_to_obsidian"
        assert SyncDirection.BIDIRECTIONAL.value == "bidirectional"


class TestSyncStatus:
    """Test SyncStatus enum."""

    def test_sync_status_values(self):
        """Test SyncStatus enum values."""
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.FAILED.value == "failed"
        assert SyncStatus.PARTIAL.value == "partial"
        assert SyncStatus.SKIPPED.value == "skipped"


class TestSyncResult:
    """Test SyncResult dataclass."""

    def test_sync_result_defaults(self):
        """Test SyncResult default values."""
        result = SyncResult(direction=SyncDirection.BIDIRECTIONAL, status=SyncStatus.SUCCESS)
        assert result.synced == 0
        assert result.created == 0
        assert result.updated == 0
        assert result.skipped == 0
        assert result.failed == 0
        assert result.errors == []
        assert result.duration_seconds == 0.0

    def test_sync_result_custom_values(self):
        """Test SyncResult with custom values."""
        result = SyncResult(
            direction=SyncDirection.BIDIRECTIONAL,
            status=SyncStatus.SUCCESS,
            synced=5,
            created=2,
            updated=3,
            skipped=1,
            failed=0,
            errors=[],
            duration_seconds=1.5,
        )
        assert result.synced == 5
        assert result.created == 2
        assert result.updated == 3
        assert result.duration_seconds == 1.5


class TestCreateObsidianSync:
    """Test factory function."""

    def test_create_obsidian_sync(self, mock_client, tmp_path):
        """Test factory function creates correct instance."""
        sync = create_obsidian_sync(
            vault_path=str(tmp_path),
            memory_client=mock_client,
            direction=SyncDirection.BIDIRECTIONAL,
        )
        assert isinstance(sync, ObsidianSync)
        assert sync.direction == SyncDirection.BIDIRECTIONAL
