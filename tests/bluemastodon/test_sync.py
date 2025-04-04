"""Tests for the sync module."""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, mock_open, patch

from bluemastodon.models import SyncRecord
from bluemastodon.sync import SyncManager

# Tests need pytest fixtures


class TestSyncManager:
    """Test the SyncManager class."""

    def test_init(self, sample_config):
        """Test initialization of SyncManager."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky,
            patch("bluemastodon.sync.MastodonClient") as mock_masto,
            patch("bluemastodon.sync.os.path.exists", return_value=False),
        ):

            # Create manager with default state file
            manager = SyncManager(sample_config)

            # Check initialization
            assert manager.config == sample_config
            assert manager.synced_posts == set()
            assert manager.sync_records == []
            mock_bsky.assert_called_once_with(sample_config.bluesky)
            mock_masto.assert_called_once_with(sample_config.mastodon)

            # Create manager with custom state file
            custom_state_file = "/tmp/custom_state.json"
            manager = SyncManager(sample_config, custom_state_file)
            assert manager.state_file == custom_state_file

    def test_load_state_no_file(self, sample_config):
        """Test _load_state when file doesn't exist."""
        with (
            patch("bluemastodon.sync.os.path.exists", return_value=False),
            patch("bluemastodon.sync.BlueskyClient"),
            patch("bluemastodon.sync.MastodonClient"),
        ):

            manager = SyncManager(sample_config)

            # Check that state is empty
            assert manager.synced_posts == set()
            assert manager.sync_records == []

    def test_load_state_with_file(self, sample_config, sample_sync_state_file):
        """Test _load_state with existing state file."""
        with (
            patch("bluemastodon.sync.BlueskyClient"),
            patch("bluemastodon.sync.MastodonClient"),
        ):

            # Create manager with sample state file
            manager = SyncManager(sample_config, sample_sync_state_file)

            # Check that state was loaded correctly
            assert manager.synced_posts == {"existing1", "existing2"}
            assert len(manager.sync_records) == 2

            # Check record properties
            record1 = manager.sync_records[0]
            assert record1.source_id == "existing1"
            assert record1.source_platform == "bluesky"
            assert record1.target_id == "target1"
            assert record1.target_platform == "mastodon"
            assert record1.success is True
            assert record1.error_message is None

    def test_load_state_with_invalid_file(self, sample_config):
        """Test _load_state with invalid state file."""
        # Create an invalid JSON file
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("this is not valid json")
            invalid_state_file = temp_file.name

        try:
            with (
                patch("bluemastodon.sync.BlueskyClient"),
                patch("bluemastodon.sync.MastodonClient"),
            ):

                # Create manager with invalid state file
                manager = SyncManager(sample_config, invalid_state_file)

                # Check that state is empty
                assert manager.synced_posts == set()
                assert manager.sync_records == []

        finally:
            # Clean up
            if os.path.exists(invalid_state_file):
                os.unlink(invalid_state_file)

    def test_load_state_with_invalid_record(self, sample_config):
        """Test _load_state with invalid record in state file."""
        # Create a file with an invalid record
        invalid_record_file = None
        try:
            # Create a state file with invalid record format
            state_content = {
                "synced_posts": ["post1"],
                "sync_records": [
                    {
                        "source_id": "post1",
                        # Missing required fields
                        "synced_at": datetime.now().isoformat(),
                    }
                ],
            }

            with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
                json.dump(state_content, temp_file)
                invalid_record_file = temp_file.name

            with (
                patch("bluemastodon.sync.BlueskyClient"),
                patch("bluemastodon.sync.MastodonClient"),
                patch("bluemastodon.sync.logger") as mock_logger,
            ):

                # Create manager with invalid record file
                manager = SyncManager(sample_config, invalid_record_file)

                # Check that synced_posts were loaded but invalid record was skipped
                assert manager.synced_posts == {"post1"}
                assert manager.sync_records == []

                # Verify warning was logged
                mock_logger.warning.assert_called_once()
                assert (
                    "Could not parse sync record" in mock_logger.warning.call_args[0][0]
                )

        finally:
            # Clean up
            if invalid_record_file and os.path.exists(invalid_record_file):
                os.unlink(invalid_record_file)

    def test_save_state(self, sample_config):
        """Test _save_state method."""
        # Setup mock for open and json.dump
        mock_file = MagicMock()
        m_open = mock_open(mock=mock_file)

        with (
            patch("bluemastodon.sync.BlueskyClient"),
            patch("bluemastodon.sync.MastodonClient"),
            patch("bluemastodon.sync.open", m_open),
            patch("bluemastodon.sync.json.dump") as mock_dump,
            patch("bluemastodon.sync.os.makedirs") as mock_makedirs,
        ):

            # Create manager
            manager = SyncManager(sample_config, "/tmp/state.json")

            # Add some state
            manager.synced_posts = {"post1", "post2"}

            now = datetime.now()
            record = SyncRecord(
                source_id="post1",
                source_platform="bluesky",
                target_id="toot1",
                target_platform="mastodon",
                synced_at=now,
                success=True,
            )
            manager.sync_records = [record]

            # Call _save_state
            manager._save_state()

            # Verify directory was created
            mock_makedirs.assert_called_once_with(
                os.path.dirname("/tmp/state.json"), exist_ok=True
            )

            # Verify file was opened
            m_open.assert_called_once_with("/tmp/state.json", "w")

            # Verify json.dump was called with correct data
            # Extract the data argument from the call
            call_args = mock_dump.call_args[0]
            data = call_args[0]

            # Check state content
            assert isinstance(data, dict)
            assert set(data["synced_posts"]) == {"post1", "post2"}
            assert len(data["sync_records"]) == 1
            assert data["sync_records"][0]["source_id"] == "post1"
            assert data["sync_records"][0]["target_id"] == "toot1"

    def test_find_mastodon_id_for_bluesky_post(self, sample_config):
        """Test find_mastodon_id_for_bluesky_post method."""
        with (
            patch("bluemastodon.sync.BlueskyClient"),
            patch("bluemastodon.sync.MastodonClient"),
        ):
            # Create manager
            manager = SyncManager(sample_config)

            # Setup test sync records
            record1 = SyncRecord(
                source_id="bluesky1",
                source_platform="bluesky",
                target_id="mastodon1",
                target_platform="mastodon",
                synced_at=datetime.now(),
                success=True,
            )
            record2 = SyncRecord(
                source_id="bluesky2",
                source_platform="bluesky",
                target_id="mastodon2",
                target_platform="mastodon",
                synced_at=datetime.now(),
                success=True,
            )
            record3 = SyncRecord(
                source_id="other1",
                source_platform="other",
                target_id="mastodon3",
                target_platform="mastodon",
                synced_at=datetime.now(),
                success=True,
            )
            manager.sync_records = [record1, record2, record3]

            # Test finding existing records
            assert manager.find_mastodon_id_for_bluesky_post("bluesky1") == "mastodon1"
            assert manager.find_mastodon_id_for_bluesky_post("bluesky2") == "mastodon2"

            # Test record from different platform
            assert manager.find_mastodon_id_for_bluesky_post("other1") is None

            # Test non-existent record
            assert manager.find_mastodon_id_for_bluesky_post("nonexistent") is None

    def test_save_state_error(self, sample_config):
        """Test _save_state error handling."""
        with (
            patch("bluemastodon.sync.BlueskyClient"),
            patch("bluemastodon.sync.MastodonClient"),
            patch("bluemastodon.sync.open", side_effect=OSError("Failed to open file")),
            patch("bluemastodon.sync.logger") as mock_logger,
            patch("bluemastodon.sync.os.makedirs"),
        ):

            # Create manager
            manager = SyncManager(sample_config, "/tmp/state.json")

            # Call _save_state
            manager._save_state()

            # Verify error was logged
            mock_logger.error.assert_called_once()
            assert "Failed to save sync state" in mock_logger.error.call_args[0][0]

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_sync_post_success(
        self, mock_save_state, sample_config, sample_bluesky_post
    ):
        """Test _sync_post success case."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock mastodon post response
            mock_mastodon_post = MagicMock()
            mock_mastodon_post.id = "toot123"
            mock_masto.post.return_value = mock_mastodon_post

            # Create manager
            manager = SyncManager(sample_config)

            # Call _sync_post
            result = manager._sync_post(sample_bluesky_post)

            # Check the result
            assert isinstance(result, SyncRecord)
            assert result.source_id == sample_bluesky_post.id
            assert result.source_platform == "bluesky"
            assert result.target_id == "toot123"
            assert result.target_platform == "mastodon"
            assert result.success is True
            assert result.error_message is None

            # Check state was updated
            assert sample_bluesky_post.id in manager.synced_posts
            assert result in manager.sync_records

            # Verify mock calls
            mock_masto.post.assert_called_once()
            args, kwargs = mock_masto.post.call_args
            assert args[0] == sample_bluesky_post
            assert "in_reply_to_id" in kwargs and kwargs["in_reply_to_id"] is None
            # _save_state is now called immediately after successful posting
            mock_save_state.assert_called_once()

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_sync_post_failure(
        self, mock_save_state, sample_config, sample_bluesky_post
    ):
        """Test _sync_post when posting fails."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock post to return None (failure)
            mock_masto.post.return_value = None

            # Create manager
            manager = SyncManager(sample_config)

            # Call _sync_post
            result = manager._sync_post(sample_bluesky_post)

            # Check the result
            assert isinstance(result, SyncRecord)
            assert result.source_id == sample_bluesky_post.id
            assert result.source_platform == "bluesky"
            assert result.target_id == ""
            assert result.target_platform == "mastodon"
            assert result.success is False
            assert result.error_message is not None

            # Check state was updated (record added, but synced_posts not updated)
            assert sample_bluesky_post.id not in manager.synced_posts
            assert result in manager.sync_records

            # Verify mock calls
            mock_masto.post.assert_called_once()
            args, kwargs = mock_masto.post.call_args
            assert args[0] == sample_bluesky_post
            assert "in_reply_to_id" in kwargs
            mock_save_state.assert_not_called()

    @patch("bluemastodon.sync.SyncManager._sync_post")
    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_run_sync_success(self, mock_save_state, mock_sync_post, sample_config):
        """Test run_sync success case."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock authentication
            mock_bsky.ensure_authenticated.return_value = True
            mock_masto.ensure_authenticated.return_value = True

            # Mock recent posts
            post1 = MagicMock()
            post1.id = "post1"
            post2 = MagicMock()
            post2.id = "post2"
            post3 = MagicMock()
            post3.id = "already_synced"
            mock_bsky.get_recent_posts.return_value = [post1, post2, post3]

            # Mock sync_post results
            record1 = MagicMock()
            record2 = MagicMock()
            mock_sync_post.side_effect = [record1, record2]

            # Create manager with one post already synced
            manager = SyncManager(sample_config)
            manager.synced_posts = {"already_synced"}

            # Mock find_mastodon_id_for_bluesky_post to always return None
            manager.find_mastodon_id_for_bluesky_post = MagicMock(return_value=None)

            # Call run_sync
            result = manager.run_sync()

            # Check the result
            assert result == [record1, record2]

            # Verify mock calls
            mock_bsky.ensure_authenticated.assert_called_once()
            mock_masto.ensure_authenticated.assert_called_once()
            mock_bsky.get_recent_posts.assert_called_once_with(
                hours_back=sample_config.lookback_hours,
                limit=sample_config.max_posts_per_run,
                include_threads=sample_config.include_threads,
            )

            # Should only sync new posts, not the already synced one
            assert mock_sync_post.call_count == 2
            mock_sync_post.assert_any_call(post1)
            mock_sync_post.assert_any_call(post2)

            # Should save state after syncing
            mock_save_state.assert_called_once()

    def test_run_sync_bluesky_auth_failure(self, sample_config):
        """Test run_sync when Bluesky authentication fails."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock authentication failure
            mock_bsky.ensure_authenticated.return_value = False

            # Create manager
            manager = SyncManager(sample_config)

            # Call run_sync
            result = manager.run_sync()

            # Check the result
            assert result == []

            # Verify mock calls
            mock_bsky.ensure_authenticated.assert_called_once()
            mock_masto.ensure_authenticated.assert_not_called()
            mock_bsky.get_recent_posts.assert_not_called()

    def test_run_sync_mastodon_auth_failure(self, sample_config):
        """Test run_sync when Mastodon authentication fails."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock authentication
            mock_bsky.ensure_authenticated.return_value = True
            mock_masto.ensure_authenticated.return_value = False

            # Create manager
            manager = SyncManager(sample_config)

            # Call run_sync
            result = manager.run_sync()

            # Check the result
            assert result == []

            # Verify mock calls
            mock_bsky.ensure_authenticated.assert_called_once()
            mock_masto.ensure_authenticated.assert_called_once()
            mock_bsky.get_recent_posts.assert_not_called()

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_run_sync_no_new_posts(self, mock_save_state, sample_config):
        """Test run_sync when there are no new posts to sync."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock authentication
            mock_bsky.ensure_authenticated.return_value = True
            mock_masto.ensure_authenticated.return_value = True

            # Return empty list of recent posts
            mock_bsky.get_recent_posts.return_value = []

            # Create manager
            manager = SyncManager(sample_config)

            # Call run_sync
            result = manager.run_sync()

            # Check the result
            assert result == []

            # Verify mock calls
            mock_bsky.ensure_authenticated.assert_called_once()
            mock_masto.ensure_authenticated.assert_called_once()
            mock_bsky.get_recent_posts.assert_called_once()
            # State is only saved if there are new records
            mock_save_state.assert_not_called()

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_sync_post_exception(
        self, mock_save_state, sample_config, sample_bluesky_post
    ):
        """Test _sync_post with an exception during posting."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
            patch("bluemastodon.sync.logger") as mock_logger,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock post to raise an exception
            mock_masto.post.side_effect = Exception(
                "Unexpected error during cross-posting"
            )

            # Create manager
            manager = SyncManager(sample_config)

            # Call _sync_post
            result = manager._sync_post(sample_bluesky_post)

            # Check the result
            assert isinstance(result, SyncRecord)
            assert result.source_id == sample_bluesky_post.id
            assert result.source_platform == "bluesky"
            assert result.target_id == ""
            assert result.target_platform == "mastodon"
            assert result.success is False
            assert "Unexpected error during cross-posting" in result.error_message

            # Verify the error was logged
            # Not marked as synced (error doesn't contain "posted to mastodon")
            assert sample_bluesky_post.id not in manager.synced_posts
            # Verify save_state is called for the error
            mock_save_state.assert_called_once()
            mock_logger.error.assert_called_once()
            error_msg = f"Error syncing post {sample_bluesky_post.id}"
            assert error_msg in mock_logger.error.call_args[0][0]

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_sync_post_partial_success_exception(
        self, mock_save_state, sample_config, sample_bluesky_post
    ):
        """Test _sync_post with an exception that suggests post was successful."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
            patch("bluemastodon.sync.logger") as mock_logger,
        ):

            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Make mastodon post raise an exception that includes "Posted to Mastodon"
            error_msg = "Error after posted to mastodon: conversion failed"
            mock_masto.post.side_effect = Exception(error_msg)

            # Create manager
            manager = SyncManager(sample_config)

            # Call _sync_post
            result = manager._sync_post(sample_bluesky_post)

            # Check the result
            assert isinstance(result, SyncRecord)
            assert result.source_id == sample_bluesky_post.id
            assert result.source_platform == "bluesky"
            assert result.target_id == ""
            assert result.target_platform == "mastodon"
            assert result.success is False
            assert error_msg in result.error_message

            # Check state WAS updated for the post ID despite the error
            assert sample_bluesky_post.id in manager.synced_posts
            assert result in manager.sync_records

            # Verify save_state is called twice - once for marking as synced
            # and once for recording the error
            assert mock_save_state.call_count == 2

            # Verify warning was logged
            mock_logger.warning.assert_called_with(
                "Post may have succeeded despite error. "
                "Marking as synced to prevent duplication."
            )

            # Verify the record was added to sync_records
            assert result in manager.sync_records

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_sync_post_thread_with_parent(
        self, mock_save_state, sample_config, sample_bluesky_reply_post
    ):
        """Test _sync_post with a self-reply post where the parent ID IS found."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
            patch("bluemastodon.sync.logger") as mock_logger,
        ):
            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock mastodon post response
            mock_mastodon_post = MagicMock()
            mock_mastodon_post.id = "toot456"
            mock_masto.post.return_value = mock_mastodon_post

            # Create manager
            manager = SyncManager(sample_config)

            # Mock find_mastodon_id_for_bluesky_post to return a valid parent ID
            manager.find_mastodon_id_for_bluesky_post = MagicMock(
                return_value="parent_toot_123"
            )

            # Call _sync_post
            result = manager._sync_post(sample_bluesky_reply_post)

            # Check the result
            assert isinstance(result, SyncRecord)
            assert result.source_id == sample_bluesky_reply_post.id
            assert result.source_platform == "bluesky"
            assert result.target_id == "toot456"
            assert result.target_platform == "mastodon"
            assert result.success is True
            assert result.error_message is None

            # Check state was updated
            assert sample_bluesky_reply_post.id in manager.synced_posts
            assert result in manager.sync_records

            # Verify mock calls
            mock_masto.post.assert_called_once()
            args, kwargs = mock_masto.post.call_args
            assert args[0] == sample_bluesky_reply_post
            assert (
                kwargs["in_reply_to_id"] == "parent_toot_123"
            )  # Should use the parent ID

            # Verify info log message about finding parent
            mock_logger.info.assert_any_call(
                f"Found Mastodon parent ID: parent_toot_123 "
                f"for Bluesky parent: {sample_bluesky_reply_post.reply_parent}"
            )

            # _save_state is called immediately after successful posting
            mock_save_state.assert_called_once()

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_sync_post_thread_without_parent(
        self, mock_save_state, sample_config, sample_bluesky_reply_post
    ):
        """Test _sync_post with a self-reply post where the parent ID can't be found."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
            patch("bluemastodon.sync.logger") as mock_logger,
        ):
            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock mastodon post response
            mock_mastodon_post = MagicMock()
            mock_mastodon_post.id = "toot456"
            mock_masto.post.return_value = mock_mastodon_post

            # Create manager
            manager = SyncManager(sample_config)

            # Ensure find_mastodon_id_for_bluesky_post returns None (parent not found)
            manager.find_mastodon_id_for_bluesky_post = MagicMock(return_value=None)

            # Call _sync_post
            result = manager._sync_post(sample_bluesky_reply_post)

            # Check the result
            assert isinstance(result, SyncRecord)
            assert result.source_id == sample_bluesky_reply_post.id
            assert result.source_platform == "bluesky"
            assert result.target_id == "toot456"
            assert result.target_platform == "mastodon"
            assert result.success is True
            assert result.error_message is None

            # Check state was updated
            assert sample_bluesky_reply_post.id in manager.synced_posts
            assert result in manager.sync_records

            # Verify mock calls
            mock_masto.post.assert_called_once()
            args, kwargs = mock_masto.post.call_args
            assert args[0] == sample_bluesky_reply_post
            assert (
                kwargs["in_reply_to_id"] is None
            )  # Should be None when parent not found

            # Verify warning was logged about not finding parent
            mock_logger.warning.assert_called_with(
                f"Could not find Mastodon parent ID for Bluesky parent: "
                f"{sample_bluesky_reply_post.reply_parent}"
            )

            # _save_state is called immediately after successful posting
            mock_save_state.assert_called_once()

    @patch("bluemastodon.sync.SyncManager._save_state")
    def test_run_sync_with_new_posts(
        self, mock_save_state, sample_config, sample_bluesky_post
    ):
        """Test run_sync with new posts to sync."""
        with (
            patch("bluemastodon.sync.BlueskyClient") as mock_bsky_class,
            patch("bluemastodon.sync.MastodonClient") as mock_masto_class,
        ):
            # Setup mocks
            mock_bsky = MagicMock()
            mock_masto = MagicMock()
            mock_bsky_class.return_value = mock_bsky
            mock_masto_class.return_value = mock_masto

            # Mock authentication
            mock_bsky.ensure_authenticated.return_value = True
            mock_masto.ensure_authenticated.return_value = True

            # Return list with one post
            mock_bsky.get_recent_posts.return_value = [sample_bluesky_post]

            # Create manager and patch _sync_post to return a success record
            manager = SyncManager(sample_config)

            with patch.object(manager, "_sync_post") as mock_sync_post:
                # Create a mock record
                mock_record = SyncRecord(
                    source_id=sample_bluesky_post.id,
                    source_platform="bluesky",
                    target_id="toot123",
                    target_platform="mastodon",
                    synced_at=datetime.now(),
                    success=True,
                )
                mock_sync_post.return_value = mock_record

                # Call run_sync
                result = manager.run_sync()

                # Check the result
                assert len(result) == 1
                assert result[0] == mock_record

                # Verify mock calls
                mock_bsky.ensure_authenticated.assert_called_once()
                mock_masto.ensure_authenticated.assert_called_once()
                mock_bsky.get_recent_posts.assert_called_once()
                mock_sync_post.assert_called_once_with(sample_bluesky_post)

                # Verify final state save
                mock_save_state.assert_called_once()
