"""
Database Initialization Script
Creates all tables and indexes

Built with Pride for Obex Blackvault
"""
from backend.database.base import Base
from backend.database.session import engine
from backend.database.models import User, Token, Tenant, Agent, Mission


def init_database():
    """
    Initialize database schema
    Creates all tables defined in models
    """
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully")


def drop_database():
    """
    Drop all database tables
    WARNING: This will delete all data!
    """
    print("⚠️  Dropping all database tables...")
    Base.metadata.drop_all(bind=engine)
    print("✅ Database tables dropped")


if __name__ == "__main__":
    init_database()
