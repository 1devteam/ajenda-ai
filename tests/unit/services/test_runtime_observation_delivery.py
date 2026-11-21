from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.services.runtime_observation_delivery import observe_after_commit


def test_only_committed_observations_are_delivered() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session, patch("backend.services.runtime_observation_delivery._EXECUTOR") as executor:
        session.execute(text("select 1"))

        def observe_parent(db: Session) -> None:
            pass

        def observe_committed_child(db: Session) -> None:
            pass

        def observe_rolled_back_child(db: Session) -> None:
            pass

        observe_after_commit(session, tenant_id="tenant", write=observe_parent)
        with session.begin_nested():
            observe_after_commit(session, tenant_id="tenant", write=observe_committed_child)
        rolled_back = session.begin_nested()
        observe_after_commit(session, tenant_id="tenant", write=observe_rolled_back_child)
        rolled_back.rollback()
        executor.submit.assert_not_called()
        session.commit()
        calls = executor.submit.call_args_list
        assert [call.args[-1][1] for call in calls] == [observe_parent, observe_committed_child]
        # In this test the fake executor never invokes the delivery and releases the slots.
        for call in calls:
            call.args[0](*call.args[1:])


def test_observer_error_cannot_undo_source_commit() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session, patch("backend.services.runtime_observation_delivery._EXECUTOR") as executor:
        session.execute(text("create table source (value integer)"))
        session.execute(text("insert into source values (1)"))

        def fail_observation(db: Session) -> None:
            raise RuntimeError("diagnostic persistence unavailable")

        observe_after_commit(session, tenant_id="tenant", write=fail_observation)
        session.commit()
        call = executor.submit.call_args
        call.args[0](*call.args[1:])
        assert session.scalar(text("select value from source")) == 1
