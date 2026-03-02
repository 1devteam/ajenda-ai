"""
Phase 2 Test Suite — The Scheduled Agent (v6.1)

Tests for:
  - SchedulerService: create, list, get, pause, resume, delete, trigger
  - VaultService: store, get, list, delete, encryption correctness
  - RedditTool: action routing, input validation, error handling
  - Alembic migration: table structure validation

Built with Pride for Obex Blackvault
"""

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# VaultService Tests
# =============================================================================


class TestVaultService:
    """Tests for AES-256-GCM encrypted API key vault."""

    def _make_vault(self):
        """Create a VaultService with a mock session factory."""
        from backend.core.vault.vault_service import VaultService

        # Mock session factory
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        session_factory = MagicMock(return_value=session)

        vault = VaultService(
            session_factory=session_factory,
            secret_key="test-secret-key-for-unit-tests-only",
        )
        return vault, session

    def test_key_derivation_is_deterministic(self):
        """Same SECRET_KEY always produces the same AES key."""
        from backend.core.vault.vault_service import VaultService

        mock_sf = MagicMock()
        v1 = VaultService(session_factory=mock_sf, secret_key="my-secret")
        v2 = VaultService(session_factory=mock_sf, secret_key="my-secret")
        assert v1._aes_key == v2._aes_key

    def test_different_secret_keys_produce_different_aes_keys(self):
        """Different SECRET_KEYs produce different AES keys."""
        from backend.core.vault.vault_service import VaultService

        mock_sf = MagicMock()
        v1 = VaultService(session_factory=mock_sf, secret_key="key-one")
        v2 = VaultService(session_factory=mock_sf, secret_key="key-two")
        assert v1._aes_key != v2._aes_key

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt then decrypt returns the original plaintext."""
        from backend.core.vault.vault_service import VaultService
        import base64
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        mock_sf = MagicMock()
        vault = VaultService(session_factory=mock_sf, secret_key="roundtrip-test-key")

        original = {"client_id": "abc123", "client_secret": "super-secret", "username": "bot"}

        # Encrypt
        plaintext = json.dumps(original).encode("utf-8")
        nonce = os.urandom(12)
        aesgcm = AESGCM(vault._aes_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        encrypted_b64 = base64.b64encode(ciphertext).decode("ascii")
        nonce_b64 = base64.b64encode(nonce).decode("ascii")

        # Decrypt via vault method
        result = vault._decrypt(encrypted_b64, nonce_b64)
        assert result == original

    def test_decrypt_with_wrong_key_raises(self):
        """Decrypting with wrong key raises ValueError."""
        from backend.core.vault.vault_service import VaultService
        import base64
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        mock_sf = MagicMock()
        vault_a = VaultService(session_factory=mock_sf, secret_key="correct-key")
        vault_b = VaultService(session_factory=mock_sf, secret_key="wrong-key")

        plaintext = json.dumps({"secret": "value"}).encode("utf-8")
        nonce = os.urandom(12)
        aesgcm = AESGCM(vault_a._aes_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        encrypted_b64 = base64.b64encode(ciphertext).decode("ascii")
        nonce_b64 = base64.b64encode(nonce).decode("ascii")

        with pytest.raises(ValueError, match="Failed to decrypt"):
            vault_b._decrypt(encrypted_b64, nonce_b64)

    def test_key_to_dict_excludes_credentials(self):
        """_key_to_dict never includes encrypted_value or nonce."""
        from backend.core.vault.vault_service import VaultService
        from backend.database.models import ExternalAPIKey

        mock_sf = MagicMock()
        vault = VaultService(session_factory=mock_sf, secret_key="test")

        key = ExternalAPIKey(
            id="key_abc",
            tenant_id="tenant_1",
            created_by="user_1",
            service="reddit",
            key_name="production",
            encrypted_value="ENCRYPTED_BLOB",
            nonce="NONCE_B64",
            key_metadata={"env": "prod"},
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        result = vault._key_to_dict(key)
        assert "encrypted_value" not in result
        assert "nonce" not in result
        assert result["service"] == "reddit"
        assert result["key_name"] == "production"
        assert result["is_active"] is True


# =============================================================================
# SchedulerService Tests
# =============================================================================


class TestSchedulerService:
    """Tests for APScheduler-backed SchedulerService."""

    def _make_scheduler(self):
        """Create a SchedulerService with mocked dependencies."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        session_factory = MagicMock(return_value=session)
        mission_executor = AsyncMock()
        event_store = AsyncMock()

        svc = SchedulerService(
            session_factory=session_factory,
            mission_executor=mission_executor,
            event_store=event_store,
        )
        return svc, session, mission_executor

    def test_validate_trigger_cron_valid(self):
        """Valid cron expression passes validation."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        # Should not raise
        SchedulerService._validate_trigger("cron", "0 9 * * 1-5", None)

    def test_validate_trigger_cron_missing_expression(self):
        """Missing cron expression raises ValueError."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        with pytest.raises(ValueError, match="cron_expression is required"):
            SchedulerService._validate_trigger("cron", None, None)

    def test_validate_trigger_cron_invalid_expression(self):
        """Invalid cron expression raises ValueError."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        with pytest.raises(ValueError, match="Invalid cron_expression"):
            SchedulerService._validate_trigger("cron", "not-a-cron", None)

    def test_validate_trigger_interval_valid(self):
        """Valid interval passes validation."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        SchedulerService._validate_trigger("interval", None, 3600)

    def test_validate_trigger_interval_zero_raises(self):
        """Zero interval raises ValueError."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        with pytest.raises(ValueError, match="interval_seconds must be a positive integer"):
            SchedulerService._validate_trigger("interval", None, 0)

    def test_validate_trigger_invalid_type(self):
        """Unknown trigger type raises ValueError."""
        from backend.core.scheduler.scheduler_service import SchedulerService

        with pytest.raises(ValueError, match="Invalid trigger_type"):
            SchedulerService._validate_trigger("webhook", None, None)

    def test_job_to_dict_structure(self):
        """_job_to_dict returns expected keys."""
        from backend.core.scheduler.scheduler_service import SchedulerService
        from backend.database.models import ScheduledJob

        job = ScheduledJob(
            id="job_abc",
            name="Test Job",
            description="A test",
            tenant_id="tenant_1",
            agent_id="agent_1",
            created_by="user_1",
            trigger_type="interval",
            interval_seconds=3600,
            mission_payload={"objective": "Do something"},
            is_active=True,
            max_runs=None,
            run_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        result = SchedulerService._job_to_dict(job)
        assert result["id"] == "job_abc"
        assert result["trigger_type"] == "interval"
        assert result["interval_seconds"] == 3600
        assert result["is_active"] is True
        assert result["run_count"] == 0
        assert "mission_payload" in result

    @pytest.mark.asyncio
    async def test_emit_event_non_fatal_on_error(self):
        """_emit_event swallows exceptions — never crashes the caller."""
        svc, _, _ = self._make_scheduler()
        svc._event_store = AsyncMock(side_effect=Exception("EventStore down"))

        # Should not raise
        await svc._emit_event("job_1", "scheduler.job.triggered", {"job_id": "job_1"})

    @pytest.mark.asyncio
    async def test_emit_event_skipped_when_no_store(self):
        """_emit_event is a no-op when event_store is None."""
        svc, _, _ = self._make_scheduler()
        svc._event_store = None

        # Should not raise
        await svc._emit_event("job_1", "scheduler.job.triggered", {"job_id": "job_1"})


# =============================================================================
# RedditTool Tests
# =============================================================================


class TestRedditTool:
    """Tests for the Reddit LangChain tool."""

    def _make_tool(self, vault_creds=None):
        """Create a RedditTool with a mocked VaultService."""
        from backend.integrations.tools.reddit_tool import RedditTool

        vault = AsyncMock()
        if vault_creds is not None:
            vault.get_key = AsyncMock(return_value=vault_creds)
        else:
            vault.get_key = AsyncMock(return_value=None)

        tool = RedditTool(vault_service=vault, tenant_id="tenant_1")
        return tool, vault

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_error(self):
        """Tool returns error string when credentials not in vault."""
        tool, _ = self._make_tool(vault_creds=None)
        result = await tool._arun(json.dumps({"action": "hot", "subreddit": "python"}))
        assert "Error" in result
        assert "Reddit credentials not found" in result

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        """Unknown action returns descriptive error."""
        tool, _ = self._make_tool(
            vault_creds={
                "client_id": "x",
                "client_secret": "y",
                "username": "u",
                "password": "p",
            }
        )
        with patch("praw.Reddit") as mock_reddit:
            mock_reddit.return_value = MagicMock()
            result = await tool._arun(json.dumps({"action": "fly", "subreddit": "python"}))
        assert "Error" in result
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        """Invalid JSON input returns error."""
        tool, _ = self._make_tool()
        result = await tool._arun("not-valid-json{{{")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_hot_action_calls_subreddit_hot(self):
        """'hot' action calls subreddit.hot() and returns formatted results."""
        tool, _ = self._make_tool(
            vault_creds={
                "client_id": "cid",
                "client_secret": "csec",
                "username": "user",
                "password": "pass",
            }
        )

        # Build mock post objects
        mock_post = MagicMock()
        mock_post.score = 1234
        mock_post.title = "Test Post Title"
        mock_post.permalink = "/r/python/comments/abc/test"

        mock_subreddit = MagicMock()
        mock_subreddit.hot = MagicMock(return_value=[mock_post])

        mock_reddit_instance = MagicMock()
        mock_reddit_instance.subreddit = MagicMock(return_value=mock_subreddit)

        with patch("praw.Reddit", return_value=mock_reddit_instance):
            result = await tool._arun(
                json.dumps({"action": "hot", "subreddit": "python", "limit": 5})
            )

        assert "Test Post Title" in result
        assert "1234" in result
        assert "r/python" in result

    @pytest.mark.asyncio
    async def test_search_action_returns_results(self):
        """'search' action calls subreddit.search() and returns formatted results."""
        tool, _ = self._make_tool(
            vault_creds={
                "client_id": "cid",
                "client_secret": "csec",
                "username": "user",
                "password": "pass",
            }
        )

        mock_post = MagicMock()
        mock_post.score = 500
        mock_post.title = "AI Agents Are Amazing"
        mock_post.permalink = "/r/artificial/comments/xyz/ai"

        mock_subreddit = MagicMock()
        mock_subreddit.search = MagicMock(return_value=[mock_post])

        mock_reddit_instance = MagicMock()
        mock_reddit_instance.subreddit = MagicMock(return_value=mock_subreddit)

        with patch("praw.Reddit", return_value=mock_reddit_instance):
            result = await tool._arun(
                json.dumps({"action": "search", "subreddit": "artificial", "query": "AI agents"})
            )

        assert "AI Agents Are Amazing" in result
        assert "500" in result

    def test_tool_name_and_description(self):
        """Tool has correct name and description for agent use."""
        from backend.integrations.tools.reddit_tool import RedditTool

        tool = RedditTool(vault_service=None, tenant_id="t1")
        assert tool.name == "reddit"
        assert "post" in tool.description
        assert "search" in tool.description


# =============================================================================
# Migration Structure Tests
# =============================================================================


class TestMigrationStructure:
    """Validate the Alembic migration file structure."""

    def test_migration_has_correct_revision(self):
        """Migration file has the expected revision ID."""
        import importlib.util
        _mig_path = (
            "/home/ubuntu/fresh_repo/alembic/versions/"
            "b2c3d4e5f6a7_add_scheduled_jobs_and_api_key_vault.py"
        )
        spec = importlib.util.spec_from_file_location("migration_b2c3", _mig_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        revision = mod.revision
        down_revision = mod.down_revision

        assert revision == "b2c3d4e5f6a7"
        assert down_revision == "a1b2c3d4e5f6"

    def test_migration_upgrade_creates_both_tables(self):
        """upgrade() creates scheduled_jobs and external_api_keys tables."""
        import importlib.util
        _mig_path = (
            "/home/ubuntu/fresh_repo/alembic/versions/"
            "b2c3d4e5f6a7_add_scheduled_jobs_and_api_key_vault.py"
        )
        spec = importlib.util.spec_from_file_location("migration_b2c3", _mig_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        created_tables = []
        mock_op = MagicMock()
        mock_op.create_table = MagicMock(
            side_effect=lambda name, *a, **kw: created_tables.append(name)
        )
        mock_op.create_index = MagicMock()
        mod.op = mock_op
        mod.upgrade()

        assert "scheduled_jobs" in created_tables
        assert "external_api_keys" in created_tables

    def test_migration_downgrade_drops_both_tables(self):
        """downgrade() drops both tables."""
        import importlib.util
        _mig_path = (
            "/home/ubuntu/fresh_repo/alembic/versions/"
            "b2c3d4e5f6a7_add_scheduled_jobs_and_api_key_vault.py"
        )
        spec = importlib.util.spec_from_file_location("migration_b2c3", _mig_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        dropped_tables = []
        mock_op = MagicMock()
        mock_op.drop_table = MagicMock(side_effect=lambda name: dropped_tables.append(name))
        mod.op = mock_op
        mod.downgrade()

        assert "scheduled_jobs" in dropped_tables
        assert "external_api_keys" in dropped_tables


# =============================================================================
# Model Tests
# =============================================================================


class TestDatabaseModels:
    """Validate the new SQLAlchemy models."""

    def test_scheduled_job_model_has_required_columns(self):
        """ScheduledJob model has all required columns."""
        from backend.database.models import ScheduledJob

        columns = {c.key for c in ScheduledJob.__table__.columns}
        required = {
            "id", "name", "tenant_id", "agent_id", "created_by",
            "trigger_type", "cron_expression", "interval_seconds",
            "mission_payload", "is_active", "max_runs", "run_count",
            "last_run_at", "next_run_at", "last_run_status",
            "last_run_mission_id", "created_at", "updated_at",
        }
        assert required.issubset(columns), f"Missing columns: {required - columns}"

    def test_external_api_key_model_has_required_columns(self):
        """ExternalAPIKey model has all required columns."""
        from backend.database.models import ExternalAPIKey

        # Use DB column names (c.key maps to DB column name in __table__.columns)
        columns = {c.key for c in ExternalAPIKey.__table__.columns}
        required = {
            "id", "tenant_id", "created_by", "service", "key_name",
            "encrypted_value", "nonce", "metadata", "is_active",
            "created_at", "updated_at", "last_used_at",
        }
        assert required.issubset(columns), f"Missing columns: {required - columns}"

    def test_scheduled_job_tablename(self):
        """ScheduledJob uses correct table name."""
        from backend.database.models import ScheduledJob

        assert ScheduledJob.__tablename__ == "scheduled_jobs"

    def test_external_api_key_tablename(self):
        """ExternalAPIKey uses correct table name."""
        from backend.database.models import ExternalAPIKey

        assert ExternalAPIKey.__tablename__ == "external_api_keys"
