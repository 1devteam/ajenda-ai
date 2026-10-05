"""Compatibility facade for the modular semantic lattice.

New code should import resolution from ``semantic_lattice.resolver`` and
definitions/contracts from ``semantic_lattice.definitions``. This facade keeps
historical imports stable during the migration and exposes no runtime authority.
"""

from backend.services.mission_composition.semantic_lattice.definitions import *  # noqa: F403
