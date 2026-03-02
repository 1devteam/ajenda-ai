"""
SQLAlchemy Database Models
ORM models for PostgreSQL persistence

Built with Pride for Obex Blackvault
"""

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Float,
    Integer,
    Boolean,
    ForeignKey,
    JSON,
    Text,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.database.base import Base


class User(Base):
    """User model with authentication"""

    __tablename__ = "users"

    id = Column(String(50), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    tokens = relationship("Token", back_populates="user", cascade="all, delete-orphan")


class Token(Base):
    """Access and refresh tokens"""

    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(500), unique=True, index=True, nullable=False)
    token_type = Column(String(20), nullable=False)  # 'access' or 'refresh'
    user_id = Column(String(50), ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

    # Relationships
    user = relationship("User", back_populates="tokens")


class Tenant(Base):
    """Multi-tenant organization"""

    __tablename__ = "tenants"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    settings = Column(JSON, default=dict, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    users = relationship("User", back_populates="tenant")
    agents = relationship("Agent", back_populates="tenant")
    missions = relationship("Mission", back_populates="tenant")


class Agent(Base):
    """AI Agent model"""

    __tablename__ = "agents"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False, index=True)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    model = Column(String(100), nullable=False)
    temperature = Column(Float, default=0.7, nullable=False)
    system_prompt = Column(Text, nullable=True)
    capabilities = Column(JSON, default=list, nullable=False)
    config = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active = Column(DateTime, nullable=True)
    total_missions = Column(Integer, default=0, nullable=False)
    successful_missions = Column(Integer, default=0, nullable=False)
    failed_missions = Column(Integer, default=0, nullable=False)
    credit_balance = Column(Float, default=1000.0, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="agents")
    missions = relationship("Mission", back_populates="agent")


class Mission(Base):
    """Mission/Task model"""

    __tablename__ = "missions"

    id = Column(String(50), primary_key=True, index=True)
    objective = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    priority = Column(String(20), nullable=False, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    context = Column(JSON, default=dict, nullable=False)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    steps = Column(JSON, default=list, nullable=False)
    max_steps = Column(Integer, default=10, nullable=False)
    timeout_seconds = Column(Integer, default=300, nullable=False)
    execution_time = Column(Float, nullable=True)
    tokens_used = Column(Integer, default=0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    budget = Column(Float, nullable=True)  # Optional credit budget cap for this mission
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="missions")
    agent = relationship("Agent", back_populates="missions")


class ScheduledJob(Base):
    """
    Scheduled job model for recurring and one-off agent missions.

    Supports two trigger types:
      - ``cron``:     Standard cron expression (e.g. ``"0 9 * * 1-5"`` for weekdays at 9 AM).
      - ``interval``: Fixed interval in seconds (e.g. ``3600`` for every hour).

    The ``mission_payload`` JSON field contains the full mission specification
    that will be submitted to the MissionExecutor when the job fires.
    """

    __tablename__ = "scheduled_jobs"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Identity
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)

    # Trigger configuration
    trigger_type = Column(String(20), nullable=False)  # 'cron' | 'interval'
    cron_expression = Column(String(100), nullable=True)   # e.g. "0 9 * * 1-5"
    interval_seconds = Column(Integer, nullable=True)      # e.g. 3600

    # Mission payload — submitted to MissionExecutor on each trigger
    mission_payload = Column(JSON, nullable=False)

    # State
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    max_runs = Column(Integer, nullable=True)   # None = unlimited
    run_count = Column(Integer, default=0, nullable=False)

    # Execution tracking
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(50), nullable=True)   # 'success' | 'failed' | 'running'
    last_run_mission_id = Column(String(50), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    agent = relationship("Agent")
    creator = relationship("User", foreign_keys=[created_by])


class ExternalAPIKey(Base):
    """
    Encrypted external API key storage.

    Keys are encrypted with AES-256-GCM before storage.  The encryption key
    is derived from the application SECRET_KEY and is never stored in the DB.
    Only the ciphertext, nonce, and tag are persisted.

    Supported services: ``reddit``, ``twitter``, ``linkedin``, ``openai``, etc.
    """

    __tablename__ = "external_api_keys"

    # Primary key
    id = Column(String(50), primary_key=True, index=True)

    # Ownership
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    created_by = Column(String(50), ForeignKey("users.id"), nullable=False)

    # Key identity
    service = Column(String(100), nullable=False, index=True)   # e.g. 'reddit'
    key_name = Column(String(255), nullable=False)               # e.g. 'production'

    # Encrypted key material (AES-256-GCM)
    encrypted_value = Column(Text, nullable=False)   # base64-encoded ciphertext+tag
    nonce = Column(String(64), nullable=False)        # base64-encoded 12-byte nonce

    # Optional metadata (non-sensitive)
    # Note: 'metadata' is reserved by SQLAlchemy Declarative API — use 'key_metadata'
    key_metadata = Column("metadata", JSON, default=dict, nullable=False)

    # State
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    creator = relationship("User", foreign_keys=[created_by])
