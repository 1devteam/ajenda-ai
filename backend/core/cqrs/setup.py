"""
CQRS Bus Setup — Omnipath v5.0

Registers all command and query handlers on the shared CommandBus and QueryBus
singletons.  Call ``setup_cqrs()`` once during application startup (inside the
FastAPI lifespan) so that every subsequent ``bus.dispatch(command)`` call is
routed to the correct handler.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.core.cqrs.cqrs_impl import (
    CommandBus,
    QueryBus,
    # Commands
    CreateAgentCommand,
    UpdateAgentCommand,
    # Queries
    GetAgentQuery,
    ListAgentsQuery,
    # Handlers
    CreateAgentCommandHandler,
    UpdateAgentCommandHandler,
    GetAgentQueryHandler,
    ListAgentsQueryHandler,
    # Read models
    AgentReadModel,
)
from backend.core.event_sourcing.event_store_impl import EventStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — created once and reused across the application.
# ---------------------------------------------------------------------------
_command_bus: Optional[CommandBus] = None
_query_bus: Optional[QueryBus] = None


def get_command_bus() -> CommandBus:
    """Return the application-wide CommandBus.

    Raises:
        RuntimeError: If ``setup_cqrs()`` has not been called yet.
    """
    if _command_bus is None:
        raise RuntimeError(
            "CQRS buses not initialised. Call setup_cqrs() during app startup."
        )
    return _command_bus


def get_query_bus() -> QueryBus:
    """Return the application-wide QueryBus.

    Raises:
        RuntimeError: If ``setup_cqrs()`` has not been called yet.
    """
    if _query_bus is None:
        raise RuntimeError(
            "CQRS buses not initialised. Call setup_cqrs() during app startup."
        )
    return _query_bus


def setup_cqrs(event_store: EventStore) -> tuple[CommandBus, QueryBus]:
    """
    Instantiate all handlers, register them on the buses, and return the buses.

    This function is idempotent — calling it a second time replaces the
    existing registrations (safe for test teardown / re-initialisation).

    Args:
        event_store: The application's EventStore instance, injected into
                     handlers that need to persist or read domain events.

    Returns:
        A ``(command_bus, query_bus)`` tuple.
    """
    global _command_bus, _query_bus

    # ------------------------------------------------------------------
    # Read models (shared between command and query handlers)
    # ------------------------------------------------------------------
    agent_read_model = AgentReadModel(event_store=event_store)

    # ------------------------------------------------------------------
    # Command bus
    # ------------------------------------------------------------------
    command_bus = CommandBus()

    command_bus.register(
        CreateAgentCommand,
        CreateAgentCommandHandler(event_store=event_store),
    )
    command_bus.register(
        UpdateAgentCommand,
        UpdateAgentCommandHandler(event_store=event_store),
    )

    logger.info(
        "CQRS CommandBus initialised with %d handler(s).",
        len(command_bus._handlers),
    )

    # ------------------------------------------------------------------
    # Query bus
    # ------------------------------------------------------------------
    query_bus = QueryBus()

    query_bus.register(
        GetAgentQuery,
        GetAgentQueryHandler(read_model=agent_read_model),
    )
    query_bus.register(
        ListAgentsQuery,
        ListAgentsQueryHandler(read_model=agent_read_model),
    )

    logger.info(
        "CQRS QueryBus initialised with %d handler(s).",
        len(query_bus._handlers),
    )

    # ------------------------------------------------------------------
    # Store singletons
    # ------------------------------------------------------------------
    _command_bus = command_bus
    _query_bus = query_bus

    return command_bus, query_bus


def teardown_cqrs() -> None:
    """Reset the bus singletons.  Useful in tests."""
    global _command_bus, _query_bus
    _command_bus = None
    _query_bus = None
