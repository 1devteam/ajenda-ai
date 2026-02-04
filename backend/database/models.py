"""
SQLAlchemy Database Models
ORM models for PostgreSQL persistence

Built with Pride for Obex Blackvault
"""
from sqlalchemy import Column, String, DateTime, Float, Integer, Boolean, ForeignKey, JSON, Text
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
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    priority = Column(String(20), nullable=False, index=True)
    agent_id = Column(String(50), ForeignKey("agents.id"), nullable=False, index=True)
    tenant_id = Column(String(50), ForeignKey("tenants.id"), nullable=False, index=True)
    objective = Column(Text, nullable=False)
    context = Column(JSON, default=dict, nullable=False)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    estimated_cost = Column(Float, default=0.0, nullable=False)
    actual_cost = Column(Float, default=0.0, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="missions")
    agent = relationship("Agent", back_populates="missions")
