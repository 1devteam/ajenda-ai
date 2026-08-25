from __future__ import annotations

import threading
import time
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.services.http_idempotency_authority import HttpIdempotencyAuthority, ReplayResponse

pytestmark = pytest.mark.integration


def _authority(pg_engine, *, claim_ttl_seconds: int = 120) -> HttpIdempotencyAuthority:
    factory = sessionmaker(bind=pg_engine, class_=Session, expire_on_commit=False, autoflush=False)
    return HttpIdempotencyAuthority(
        session_factory=factory,
        encryption_key=Fernet.generate_key(),
        claim_ttl_seconds=claim_ttl_seconds,
    )


def test_postgres_claim_allows_one_owner_across_concurrent_authorities(pg_engine) -> None:
    operation_key = uuid.uuid4().hex + uuid.uuid4().hex
    request_fingerprint = uuid.uuid4().hex + uuid.uuid4().hex
    key = Fernet.generate_key()
    factory = sessionmaker(bind=pg_engine, class_=Session, expire_on_commit=False, autoflush=False)
    authorities = [HttpIdempotencyAuthority(session_factory=factory, encryption_key=key) for _ in range(8)]
    barrier = threading.Barrier(len(authorities))
    statuses: list[str] = []
    guard = threading.Lock()

    def contender(authority: HttpIdempotencyAuthority) -> None:
        barrier.wait()
        decision = authority.claim(operation_key=operation_key, request_fingerprint=request_fingerprint)
        with guard:
            statuses.append(decision.status)

    threads = [threading.Thread(target=contender, args=(authority,)) for authority in authorities]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses.count("owner") == 1
    assert statuses.count("in_flight") == len(authorities) - 1


def test_postgres_completed_receipt_replays_across_authority_instances_and_is_encrypted(pg_engine) -> None:
    operation_key = uuid.uuid4().hex + uuid.uuid4().hex
    request_fingerprint = uuid.uuid4().hex + uuid.uuid4().hex
    key = Fernet.generate_key()
    factory = sessionmaker(bind=pg_engine, class_=Session, expire_on_commit=False, autoflush=False)
    first_authority = HttpIdempotencyAuthority(session_factory=factory, encryption_key=key)
    second_authority = HttpIdempotencyAuthority(session_factory=factory, encryption_key=key)

    claim = first_authority.claim(operation_key=operation_key, request_fingerprint=request_fingerprint)
    assert claim.status == "owner"
    assert claim.owner_token is not None
    response = ReplayResponse(
        status_code=201,
        headers=[(b"content-type", b"application/json")],
        body=b'{"access_token":"sensitive-token"}',
    )
    assert first_authority.complete(
        operation_key=operation_key,
        owner_token=claim.owner_token,
        response=response,
    ) is True

    replay = second_authority.claim(operation_key=operation_key, request_fingerprint=request_fingerprint)
    assert replay.status == "replay"
    assert replay.response == response

    with pg_engine.connect() as connection:
        ciphertext = connection.scalar(
            text("SELECT response_ciphertext FROM http_idempotency_receipts WHERE operation_key = :key"),
            {"key": operation_key},
        )
    assert isinstance(ciphertext, str)
    assert "sensitive-token" not in ciphertext


def test_postgres_same_operation_key_with_changed_request_is_conflict(pg_engine) -> None:
    authority = _authority(pg_engine)
    operation_key = uuid.uuid4().hex + uuid.uuid4().hex

    first = authority.claim(operation_key=operation_key, request_fingerprint="a" * 64)
    assert first.status == "owner"
    second = authority.claim(operation_key=operation_key, request_fingerprint="b" * 64)
    assert second.status == "payload_mismatch"


def test_postgres_abandoned_claim_can_be_recovered_after_lease_expiry(pg_engine) -> None:
    key = Fernet.generate_key()
    factory = sessionmaker(bind=pg_engine, class_=Session, expire_on_commit=False, autoflush=False)
    first_authority = HttpIdempotencyAuthority(
        session_factory=factory,
        encryption_key=key,
        claim_ttl_seconds=1,
    )
    second_authority = HttpIdempotencyAuthority(
        session_factory=factory,
        encryption_key=key,
        claim_ttl_seconds=1,
    )
    operation_key = uuid.uuid4().hex + uuid.uuid4().hex
    request_fingerprint = uuid.uuid4().hex + uuid.uuid4().hex

    first = first_authority.claim(operation_key=operation_key, request_fingerprint=request_fingerprint)
    assert first.status == "owner"
    time.sleep(1.1)
    recovered = second_authority.claim(operation_key=operation_key, request_fingerprint=request_fingerprint)
    assert recovered.status == "owner"
    assert recovered.owner_token != first.owner_token
