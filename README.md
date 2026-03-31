# Ajenda AI

Ajenda AI Phase 1 foundation build.

This repository contains the Phase 1 foundational spine for a fresh Ajenda AI implementation:
- canonical runtime objects
- canonical state vocabularies
- foundational module and repository boundaries
- migration-built schema
- minimal health and readiness surface
- foundational control services

## Local development

1. Copy `.env.example` to `.env`
2. Start infrastructure with Docker Compose
3. Run migrations
4. Start the API

## Commands

```bash
alembic upgrade head
uvicorn backend.main:app --reload
pytest
```
