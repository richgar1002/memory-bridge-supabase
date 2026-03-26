"""Tests for memory client."""

import pytest
from unittest.mock import MagicMock, patch
from client import (
    MemoryClient,
    ClientConfig,
    ClientError,
    AuthenticationError,
    NotFoundError,
)


class TestMemoryClient:
    """Test MemoryClient class."""

    @pytest.fixture
    def client(self, mock_supabase):
        """Create client with mocked supabase."""
        with patch("client.create_client") as mock_create:
            mock_create.return_value = mock_supabase
            return MemoryClient(
                supabase_url="https://test.supabase.co",
                supabase_key="test-key",
                user_id="test-user-id",
            )

    def test_init(self, client):
        """Test client initialization."""
        assert client.user_id == "test-user-id"
        assert client.config is not None

    def test_init_with_config(self, mock_supabase):
        """Test client initialization with custom config."""
        with patch("client.create_client") as mock_create:
            mock_create.return_value = mock_supabase
            config = ClientConfig(max_retries=5, retry_delay=1.0)
            client = MemoryClient("https://test.supabase.co", "test-key", "user-1", config=config)
            assert client.config.max_retries == 5
            assert client.config.retry_delay == 1.0

    def test_get_collections_empty(self, client, mock_supabase):
        """Test getting collections when empty."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[], count=0
        )
        result = client.get_collections()
        assert result == []

    def test_get_collections_with_data(self, client, mock_supabase):
        """Test getting collections with data."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "col-1", "name": "Collection 1"},
                {"id": "col-2", "name": "Collection 2"},
            ],
            count=2,
        )
        result = client.get_collections()
        assert len(result) == 2
        assert result[0]["name"] == "Collection 1"

    def test_get_memories(self, client, mock_supabase):
        """Test getting memories."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "mem-1", "title": "Memory 1"},
                {"id": "mem-2", "title": "Memory 2"},
            ]
        )
        result = client.get_memories()
        assert len(result) == 2

    def test_get_memories_with_collection_filter(self, client, mock_supabase):
        """Test getting memories filtered by collection."""
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "mem-1", "title": "Memory 1"}]
        )
        result = client.get_memories(collection_id="col-1")
        assert len(result) == 1


class TestContentHash:
    """Test content hash computation."""

    @pytest.fixture
    def client(self, mock_supabase):
        """Create client."""
        with patch("client.create_client") as mock_create:
            mock_create.return_value = mock_supabase
            return MemoryClient("https://test.supabase.co", "test-key", "test-user-id")

    def test_compute_content_hash_deterministic(self, client):
        """Test that hash is deterministic."""
        hash1 = client.compute_content_hash("Title", "Content", {"key": "value"})
        hash2 = client.compute_content_hash("Title", "Content", {"key": "value"})
        assert hash1 == hash2

    def test_compute_content_hash_different_content(self, client):
        """Test that different content produces different hash."""
        hash1 = client.compute_content_hash("Title", "Content 1")
        hash2 = client.compute_content_hash("Title", "Content 2")
        assert hash1 != hash2

    def test_compute_content_hash_empty_inputs(self, client):
        """Test hash with empty inputs."""
        hash_value = client.compute_content_hash("", "", {})
        assert len(hash_value) == 64  # SHA256 hex length

    def test_compute_content_hash_metadata_affected(self, client):
        """Test that metadata affects hash."""
        hash1 = client.compute_content_hash("Title", "Content", {"a": 1})
        hash2 = client.compute_content_hash("Title", "Content", {"b": 2})
        assert hash1 != hash2


class TestSyncLinks:
    """Test sync link methods."""

    @pytest.fixture
    def client(self, mock_supabase):
        """Create client with mocked supabase."""
        with patch("client.create_client") as mock_create:
            mock_create.return_value = mock_supabase
            return MemoryClient(
                supabase_url="https://test.supabase.co",
                supabase_key="test-key",
                user_id="test-user-id",
            )

    def test_get_sync_link_found(self, client, mock_supabase):
        """Test getting existing sync link."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "link-1", "provider": "obsidian", "external_id": "note.md"}]
        )
        result = client.get_sync_link("obsidian", "note.md")
        assert result is not None
        assert result["provider"] == "obsidian"

    def test_get_sync_link_not_found(self, client, mock_supabase):
        """Test getting non-existent sync link."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )
        result = client.get_sync_link("obsidian", "nonexistent.md")
        assert result is None

    def test_get_all_sync_links(self, client, mock_supabase):
        """Test getting all sync links."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "link-1", "provider": "obsidian"},
                {"id": "link-2", "provider": "notion"},
            ]
        )
        result = client.get_all_sync_links()
        assert len(result) == 2

    def test_get_all_sync_links_filtered(self, client, mock_supabase):
        """Test getting sync links filtered by provider."""
        mock_table = MagicMock()
        mock_supabase.table.return_value = mock_table
        mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": "link-1", "provider": "obsidian"}])
        )
        result = client.get_all_sync_links(provider="obsidian")
        assert len(result) == 1
        assert result[0]["provider"] == "obsidian"


class TestErrorHandling:
    """Test error handling."""

    @pytest.fixture
    def client(self, mock_supabase):
        """Create client."""
        with patch("client.create_client") as mock_create:
            mock_create.return_value = mock_supabase
            return MemoryClient("https://test.supabase.co", "test-key", "test-user-id")

    def test_client_error(self):
        """Test ClientError exception."""
        with pytest.raises(ClientError):
            raise ClientError("Test error")

    def test_authentication_error(self):
        """Test AuthenticationError exception."""
        with pytest.raises(AuthenticationError):
            raise AuthenticationError("Auth failed")

    def test_not_found_error(self):
        """Test NotFoundError exception."""
        with pytest.raises(NotFoundError):
            raise NotFoundError("Not found")
