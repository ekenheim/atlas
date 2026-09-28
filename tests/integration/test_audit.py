"""The audit trail: append-only in the database, hash-chained, checked by `atlas audit verify`."""

import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from atlas.audit import Actor, AuditEvent, record
from atlas.db.migrate import upgrade
from atlas.settings import Settings

GENESIS = "0" * 64
OLD = "a" * 64
NEW = "b" * 64


@pytest.fixture
def audited_url(empty_database_url: str) -> str:
    upgrade(empty_database_url)
    return empty_database_url


@pytest.fixture
def engine(audited_url: str) -> Iterator[Engine]:
    engine = create_engine(audited_url)
    yield engine
    engine.dispose()


def configured_actor(database_url: str, tmp_path: Path) -> Actor:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    settings = Settings.model_validate(
        {"database_url": database_url, "actor": "local-researcher", "archive_root": archive}
    )
    return Actor.from_settings(settings)


def record_change(connection: Connection, actor: Actor, entity_id: str) -> AuditEvent:
    return record(
        connection,
        actor,
        "assertion.review",
        entity_type="assertion",
        entity_id=entity_id,
        old_hash=OLD,
        new_hash=NEW,
    )


def audit_verify(database_url: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(archive),
    }
    return subprocess.run(
        [sys.executable, "-m", "atlas", "audit", "verify"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def tamper(engine: Engine, statement: str) -> None:
    """Rewrite history the way only the table owner could: with the triggers switched off."""
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE audit_event DISABLE TRIGGER USER"))
        connection.execute(text(statement))
        connection.execute(text("ALTER TABLE audit_event ENABLE TRIGGER USER"))


def test_events_chain_across_writes_and_the_chain_verifies(
    engine: Engine, audited_url: str, tmp_path: Path
) -> None:
    actor = configured_actor(audited_url, tmp_path)
    events: list[AuditEvent] = []
    for entity_id in ("1", "2"):
        with engine.begin() as connection:
            events.append(record_change(connection, actor, entity_id))
    with engine.begin() as connection:  # several events in one transaction
        events.extend(record_change(connection, actor, entity_id) for entity_id in ("3", "4", "5"))

    assert [event.id for event in events] == [1, 2, 3, 4, 5]
    assert events[0].prev_hash == GENESIS
    for previous, event in pairwise(events):
        assert event.prev_hash == previous.event_hash
    assert len({event.event_hash for event in events}) == 5
    assert all(event.actor == "local-researcher" for event in events)

    result = audit_verify(audited_url, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "audit chain ok: 5 events" in result.stdout
    assert events[-1].event_hash in result.stdout


def test_an_empty_trail_verifies(audited_url: str, tmp_path: Path) -> None:
    result = audit_verify(audited_url, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "audit chain ok: 0 events" in result.stdout


def test_concurrent_writers_still_form_one_chain(
    engine: Engine, audited_url: str, tmp_path: Path
) -> None:
    actor = configured_actor(audited_url, tmp_path)
    errors: list[BaseException] = []

    def writer(worker: int) -> None:
        try:
            for n in range(5):
                with engine.begin() as connection:
                    record_change(connection, actor, f"{worker}-{n}")
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(worker,)) for worker in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    result = audit_verify(audited_url, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "audit chain ok: 30 events" in result.stdout


def test_a_rolled_back_change_leaves_no_event(
    engine: Engine, audited_url: str, tmp_path: Path
) -> None:
    actor = configured_actor(audited_url, tmp_path)
    with engine.connect() as connection:
        record_change(connection, actor, "1")
        connection.rollback()
    with engine.begin() as connection:
        event = record_change(connection, actor, "2")

    assert event.id == 1
    assert event.prev_hash == GENESIS


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_event SET actor = 'mallory'",
        "DELETE FROM audit_event",
        "TRUNCATE audit_event",
    ],
)
def test_direct_changes_to_the_trail_are_rejected_by_the_database(
    engine: Engine, audited_url: str, tmp_path: Path, statement: str
) -> None:
    actor = configured_actor(audited_url, tmp_path)
    with engine.begin() as connection:
        record_change(connection, actor, "1")

    # The test role is a superuser and the table owner: the trigger still refuses.
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text(statement))

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT actor FROM audit_event")).scalars().all()
    assert rows == ["local-researcher"]


def test_replica_mode_does_not_switch_the_guard_off(
    engine: Engine, audited_url: str, tmp_path: Path
) -> None:
    actor = configured_actor(audited_url, tmp_path)
    with engine.begin() as connection:
        record_change(connection, actor, "1")

    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(text("DELETE FROM audit_event"))


def test_a_raw_insert_cannot_choose_its_place_in_the_chain(
    engine: Engine, audited_url: str, tmp_path: Path
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_event (id, occurred_at, actor, action, entity_type, entity_id,"
                " prev_hash, event_hash) VALUES (99, '2000-01-01', 'local-researcher',"
                f" 'assertion.create', 'assertion', '1', '{'c' * 64}', '{'d' * 64}')"
            )
        )
        row = connection.execute(text("SELECT id, prev_hash FROM audit_event")).one()

    assert tuple(row) == (1, GENESIS)
    result = audit_verify(audited_url, tmp_path)
    assert result.returncode == 0, result.stderr


def test_the_runtime_role_may_only_read_and_append(empty_database_url: str, tmp_path: Path) -> None:
    admin = create_engine(empty_database_url)
    with admin.begin() as connection:
        # Roles are cluster-wide, so another run may have created it already.
        connection.execute(
            text(
                "DO $$ BEGIN CREATE ROLE atlas_app NOLOGIN; "
                "EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL; END $$"
            )
        )
    admin.dispose()
    upgrade(empty_database_url)  # grants the runtime role its privileges because it exists

    engine = create_engine(empty_database_url)
    actor = configured_actor(empty_database_url, tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE atlas_app"))
            event = record_change(connection, actor, "1")
            count = connection.execute(text("SELECT count(*) FROM audit_event")).scalar_one()
        assert event.id == 1
        assert count == 1
        for statement in ("UPDATE audit_event SET actor = 'mallory'", "DELETE FROM audit_event"):
            with pytest.raises(DBAPIError, match="permission denied"), engine.begin() as connection:
                connection.execute(text("SET LOCAL ROLE atlas_app"))
                connection.execute(text(statement))
    finally:
        engine.dispose()


def test_blank_actor_is_rejected_by_the_database(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_event (actor, action, entity_type, entity_id) "
                "VALUES ('  ', 'assertion.create', 'assertion', '1')"
            )
        )


def test_verify_detects_a_tampered_event(engine: Engine, audited_url: str, tmp_path: Path) -> None:
    actor = configured_actor(audited_url, tmp_path)
    with engine.begin() as connection:
        for entity_id in ("1", "2", "3"):
            record_change(connection, actor, entity_id)

    tamper(engine, "UPDATE audit_event SET actor = 'mallory' WHERE id = 2")
    result = audit_verify(audited_url, tmp_path)

    assert result.returncode == 1
    assert "audit chain broken" in result.stderr
    assert "event 2: tampered" in result.stderr


def test_verify_detects_a_rehashed_event_by_its_broken_link(
    engine: Engine, audited_url: str, tmp_path: Path
) -> None:
    actor = configured_actor(audited_url, tmp_path)
    with engine.begin() as connection:
        for entity_id in ("1", "2", "3"):
            record_change(connection, actor, entity_id)

    # A forger who also replaces the event's own hash still breaks its successor's link.
    tamper(engine, f"UPDATE audit_event SET event_hash = '{'c' * 64}' WHERE id = 2")
    result = audit_verify(audited_url, tmp_path)

    assert result.returncode == 1
    assert "event 3: broken link" in result.stderr


def test_verify_detects_a_missing_event(engine: Engine, audited_url: str, tmp_path: Path) -> None:
    actor = configured_actor(audited_url, tmp_path)
    with engine.begin() as connection:
        for entity_id in ("1", "2", "3"):
            record_change(connection, actor, entity_id)

    tamper(engine, "DELETE FROM audit_event WHERE id = 2")
    result = audit_verify(audited_url, tmp_path)

    assert result.returncode == 1
    assert "event 3: missing event(s) before it" in result.stderr
