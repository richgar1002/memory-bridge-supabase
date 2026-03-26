"""Test fixtures and configuration."""

import os
import pytest
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")


@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[], count=0
    )
    return mock


@pytest.fixture
def mock_client(mock_supabase):
    """Mock memory client."""
    client = MagicMock()
    client.supabase = mock_supabase
    client.user_id = "test-user-id"
    return client


@pytest.fixture
def sample_memory():
    """Sample memory data."""
    return {
        "id": "memory-123",
        "user_id": "test-user-id",
        "title": "Test Memory",
        "content": "This is test content",
        "tags": ["test"],
        "content_hash": "abc123",
        "revision": 1,
    }


@pytest.fixture
def sample_obsidian_note():
    """Sample Obsidian note."""
    return {
        "id": "notes/test-note.md",
        "title": "Test Note",
        "content": "Test content",
        "metadata": {"tags": ["test"]},
        "content_hash": "def456",
    }
