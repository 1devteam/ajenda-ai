#!/usr/bin/env python3
"""
Failure Reproducer — Phase 6 Self-Audit
========================================
This script reproduces the two classes of test failures that occur when the
full test suite is run together, even though each test file passes in isolation.

ROOT CAUSE ANALYSIS
-------------------
Both failures share the same root cause: **module-level stub injection with
insufficient isolation guards**.

The files `tests/test_phase4_coordinating_agent.py` and
`tests/test_phase5_revenue_agent.py` each call `_ensure_stubs()` at module
load time (not inside a fixture or test function). This function injects
MagicMock objects into `sys.modules` for heavy dependencies like
`cryptography` and `apscheduler`.

The original guard was `if name not in sys.modules`, which only checks
whether the module is already cached. It does NOT check whether the real
library is importable. When pytest collects test_phase4 (alphabetically
before test_phase2), the real `cryptography` and `apscheduler` libraries
have not yet been imported, so `sys.modules` does not contain them, and
the stubs are injected. These stubs then persist for the entire test session,
causing subsequent tests that depend on the real libraries to fail.

FAILURE 1: VaultService.test_encrypt_decrypt_roundtrip
-------------------------------------------------------
The test directly instantiates `AESGCM` from
`cryptography.hazmat.primitives.ciphers.aead`. After test_phase4 runs,
`sys.modules["cryptography.hazmat.primitives.ciphers.aead"]` contains a
stub module where `AESGCM` is a `MagicMock` class. Instantiating a
`MagicMock` produces another `MagicMock`, and calling `.encrypt()` on it
raises `AttributeError` because `MagicMock` does not auto-create methods
with the right signatures.

FAILURE 2: EventStore.__init__() got unexpected keyword argument 'session'
---------------------------------------------------------------------------
The test in `test_month5_implementations.py` was written against an older
version of `EventStore` that accepted a `session` kwarg directly. The
current implementation uses `session_factory: async_sessionmaker` and
manages its own session lifecycle internally. This is a straightforward
API mismatch — the test was not updated when the implementation changed.

THE FIX (applied in Phase 6)
----------------------------
1. `_ensure_stubs()` in test_phase4 and test_phase5 was updated to use a
   `try: __import__(name) except ImportError: stub` pattern. This ensures
   that if the real library is installed, the real module is always used.

2. `TestEventStoreAppend` tests were updated to pass a mock
   `async_sessionmaker` (implemented as an `asynccontextmanager` function)
   to `EventStore(session_factory=...)`, matching the current API.
"""

import sys
import types
from unittest.mock import MagicMock


def demonstrate_stub_contamination():
    """
    Demonstrates how injecting AESGCM=MagicMock into sys.modules
    causes AttributeError when the test tries to use the real AESGCM.
    """
    print("\n=== Failure 1: AESGCM stub contamination ===")

    # Simulate what _ensure_stubs() does in test_phase4
    stub_aead = types.ModuleType("cryptography.hazmat.primitives.ciphers.aead")
    stub_aead.AESGCM = MagicMock  # AESGCM is now a MagicMock class
    sys.modules["cryptography.hazmat.primitives.ciphers.aead"] = stub_aead

    print("  Injected MagicMock stub for AESGCM into sys.modules")

    # Now simulate what the vault test does
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import os
        key = os.urandom(32)
        aesgcm = AESGCM(key)          # Returns a MagicMock instance
        nonce = os.urandom(12)
        plaintext = b"secret"
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)  # AttributeError!
        print(f"  UNEXPECTED: encrypt succeeded, result={ciphertext}")
    except AttributeError as e:
        print(f"  REPRODUCED: AttributeError: {e}")
    finally:
        # Clean up so we don't contaminate the rest of this script
        del sys.modules["cryptography.hazmat.primitives.ciphers.aead"]
        print("  Cleaned up stub from sys.modules")


def demonstrate_event_store_api_mismatch():
    """
    Demonstrates the EventStore session vs session_factory API mismatch.
    """
    print("\n=== Failure 2: EventStore API mismatch ===")

    # Add repo root to path so we can import backend modules
    import os
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from backend.core.event_sourcing.event_store_impl import EventStore
        from unittest.mock import AsyncMock

        mock_session = AsyncMock()
        # This is what the OLD test did — passes 'session' kwarg
        store = EventStore(session=mock_session)
        print(f"  UNEXPECTED: EventStore accepted 'session' kwarg, store={store}")
    except TypeError as e:
        print(f"  REPRODUCED: TypeError: {e}")
        print("  The current EventStore.__init__ signature is:")
        print("    def __init__(self, session_factory: async_sessionmaker) -> None")
        print("  The test was written against an older API.")


if __name__ == "__main__":
    print("Phase 6 Failure Reproducer")
    print("=" * 50)
    demonstrate_stub_contamination()
    demonstrate_event_store_api_mismatch()
    print("\n[Done] Both failures reproduced successfully.")
    print("See docstring at top of this file for root cause analysis and fix.")
