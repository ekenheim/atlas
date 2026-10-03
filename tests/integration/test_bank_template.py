"""Applying the research bank template through `atlas hindsight apply-template`.

Hindsight is the recorded fake, served on localhost so the CLI subprocess can reach it. The
template's import is the fake's documented derivation (tests/fakes/hindsight.py); the template
is checked against the bank-template schema Hindsight 0.10.1 served
(`spikes/hindsight/recordings/bank_templates/01-schema`).
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema.validators import validator_for
from sqlalchemy import Engine, text

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served, serve
from tests.harness import BANK, TEMPLATE

TEMPLATE_FILE: dict[str, Any] = json.loads(TEMPLATE.read_text(encoding="utf-8"))
DRY_RUN = "research_template/01-import-dry-run"
IMPORT = "research_template/02-import"
SCHEMA = cast(
    dict[str, Any], RecordedHindsight().recording("bank_templates/01-schema").response_object()
)
# Memory-quality ticket 23: the server defaults Atlas's memory relies on, pinned at the values
# the research bank ran with on 2026-10-03 (docs/research/hindsight-bank-settings.md).
PINNED: dict[str, Any] = {
    "enable_temporal_retrieval": True,
    "enable_graph_retrieval": True,
    "enable_text_search": True,
    "enable_reranking": True,
    "store_document_text": True,
    "entities_allow_free_form": True,
    "retain_extraction_mode": "concise",
    "retain_chunk_size": 3000,
    "consolidation_max_memories_per_round": 100,
}


@pytest.fixture
def hindsight() -> Iterator[tuple[RecordedHindsight, Served]]:
    """Overrides the shared fixture: nothing derived, and a request the fake can't answer
    doesn't fail the test (one here fails the dry run that way on purpose)."""
    fake = RecordedHindsight()
    with serve(fake.transport.handle_request) as served:
        yield fake, served


def apply_template(
    database_url: str, tmp_path: Path, hindsight_url: str | None, *args: str, **env: str
) -> subprocess.CompletedProcess[str]:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    base = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(archive),
        "ATLAS_HINDSIGHT_BANK_ID": BANK,
        "ATLAS_HINDSIGHT_TEMPLATE_PATH": str(TEMPLATE),
    }
    if hindsight_url:
        base["ATLAS_HINDSIGHT_URL"] = hindsight_url
    return subprocess.run(
        [sys.executable, "-m", "atlas", "hindsight", "apply-template", *args],
        cwd=tmp_path,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def applications(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT bank_id, template_version, manifest_sha256, dry_run_result, import_result"
                " FROM bank_template_application ORDER BY applied_at"
            )
        ).mappings()
        return [dict(row) for row in rows]


def audit_events(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT actor, action, entity_type, entity_id, old_hash, new_hash"
                " FROM audit_event ORDER BY id"
            )
        ).mappings()
        return [dict(row) for row in rows]


def test_the_template_is_dry_run_then_imported_and_its_version_recorded(
    database_url: str, engine: Engine, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    bank_id = fake.recording(DRY_RUN).bank_id

    result = apply_template(database_url, tmp_path, served.url)

    served.raise_errors()
    assert result.returncode == 0, result.stderr
    # The template differs from the recorded 1.0.0 only in its mental models and its bank
    # config, so the fake derives both responses from the recordings (tests/fakes/hindsight.py).
    assert fake.served == [f"{DRY_RUN} (derived)", f"{IMPORT} (derived)"]
    printed = json.loads(result.stdout)
    assert printed["bank_id"] == bank_id
    assert printed["template_version"] == TEMPLATE_FILE["template_version"]
    assert printed["dry_run"]["dry_run"] is True
    assert printed["applied"]["dry_run"] is False
    assert (
        printed["applied"]["directives_created"]
        == fake.recording(IMPORT).response_object()["directives_created"]
    )
    [application] = applications(engine)
    assert application["bank_id"] == bank_id
    assert application["template_version"] == TEMPLATE_FILE["template_version"]
    assert application["manifest_sha256"] == printed["manifest_sha256"]
    assert application["dry_run_result"]["dry_run"] is True
    assert application["import_result"]["config_applied"] is True
    model_ids = [m["id"] for m in TEMPLATE_FILE["manifest"]["mental_models"]]
    assert application["dry_run_result"]["mental_models_created"] == model_ids
    assert application["import_result"]["mental_models_created"] == model_ids
    assert audit_events(engine) == [
        {
            "actor": "local-researcher",
            "action": "bank_template.applied",
            "entity_type": "hindsight_bank",
            "entity_id": bank_id,
            "old_hash": None,
            "new_hash": printed["manifest_sha256"],
        }
    ]


def test_reapplying_records_a_second_application_chained_to_the_first(
    database_url: str, engine: Engine, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    _, served = hindsight

    first = apply_template(database_url, tmp_path, served.url)
    second = apply_template(database_url, tmp_path, served.url)

    assert (first.returncode, second.returncode) == (0, 0), second.stderr
    sha = json.loads(first.stdout)["manifest_sha256"]
    assert [a["manifest_sha256"] for a in applications(engine)] == [sha, sha]
    assert [(e["old_hash"], e["new_hash"]) for e in audit_events(engine)] == [
        (None, sha),
        (sha, sha),
    ]


def test_a_failed_dry_run_imports_and_records_nothing(
    database_url: str, engine: Engine, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    # No recording matches this template, so the served fake fails the dry run (HTTP 500).
    manifest = cast(dict[str, Any], TEMPLATE_FILE["manifest"])
    edited: dict[str, Any] = {**TEMPLATE_FILE, "manifest": {**manifest, "directives": []}}
    template = tmp_path / "edited-template.json"
    template.write_text(json.dumps(edited), encoding="utf-8")

    result = apply_template(database_url, tmp_path, served.url, "--template", str(template))

    assert result.returncode == 1
    assert "template not applied" in result.stderr
    assert "Traceback" not in result.stderr
    [call] = fake.calls
    assert (call.method, dict(call.url.params)) == ("POST", {"dry_run": "true"})
    assert applications(engine) == []
    assert audit_events(engine) == []


def test_an_unreachable_hindsight_fails_without_recording(
    database_url: str, engine: Engine, tmp_path: Path
) -> None:
    result = apply_template(database_url, tmp_path, "http://127.0.0.1:1")

    assert result.returncode == 1
    assert "template not applied" in result.stderr
    assert "Traceback" not in result.stderr
    assert applications(engine) == []


def test_hindsight_must_be_configured(database_url: str, tmp_path: Path) -> None:
    result = apply_template(database_url, tmp_path, None)

    assert result.returncode == 2
    assert "ATLAS_HINDSIGHT_URL" in result.stderr


@pytest.mark.parametrize(
    "content", ["not json", '{"manifest": {"version": "1"}}', '{"template_version": "1"}']
)
def test_an_invalid_template_file_is_rejected_before_any_call(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    content: str,
) -> None:
    fake, served = hindsight
    template = tmp_path / "bad-template.json"
    template.write_text(content, encoding="utf-8")

    result = apply_template(database_url, tmp_path, served.url, "--template", str(template))

    assert result.returncode == 2
    assert "invalid bank template" in result.stderr
    assert fake.calls == []


def test_if_changed_skips_a_template_already_applied_to_the_bank(
    database_url: str, engine: Engine, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    first = apply_template(database_url, tmp_path, served.url, "--if-changed")
    calls_after_first = len(fake.served)

    second = apply_template(database_url, tmp_path, served.url, "--if-changed")

    assert (first.returncode, second.returncode) == (0, 0), second.stderr
    assert "already applied" in second.stdout
    assert len(fake.served) == calls_after_first  # no Hindsight call: no re-import
    assert len(applications(engine)) == 1
    assert len(audit_events(engine)) == 1


# --- the pinned settings (memory-quality ticket 23) --------------------------------------------


def test_the_template_pins_the_settings_atlas_relies_on_and_imports_them(
    database_url: str, engine: Engine, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    fake, served = hindsight
    manifest = cast(dict[str, Any], TEMPLATE_FILE["manifest"])
    bank = cast(dict[str, Any], manifest["bank"])

    assert TEMPLATE_FILE["template_version"] == "1.5.0"
    assert {name: bank.get(name) for name in PINNED} == PINNED
    # Each pinned setting is a field the recorded schema names, and the manifest validates.
    assert set(PINNED) <= set(SCHEMA["$defs"]["BankTemplateConfig"]["properties"])
    assert list(validator_for(SCHEMA)(SCHEMA).iter_errors(manifest)) == []

    result = apply_template(database_url, tmp_path, served.url, "--if-changed")

    assert result.returncode == 0, result.stderr
    # Hindsight was sent the pinned values, dry run then import.
    imports = fake.requests("POST", "import")
    assert [{name: body["bank"][name] for name in PINNED} for body in imports] == [PINNED] * 2
    [application] = applications(engine)
    assert application["template_version"] == "1.5.0"


@pytest.mark.parametrize(
    ("name", "value"),
    [*((name, "left out") for name in PINNED), ("enable_temporal_retrieval", None)],
)
def test_a_template_that_leaves_a_pinned_setting_to_the_server_is_refused_before_any_call(
    database_url: str,
    engine: Engine,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    name: str,
    value: Any,
) -> None:
    fake, served = hindsight
    manifest = cast(dict[str, Any], TEMPLATE_FILE["manifest"])
    bank = dict(cast(dict[str, Any], manifest["bank"]))
    if value == "left out":
        del bank[name]
    else:
        bank[name] = value
    edited = {**TEMPLATE_FILE, "manifest": {**manifest, "bank": bank}}
    template = tmp_path / "unpinned-template.json"
    template.write_text(json.dumps(edited), encoding="utf-8")

    result = apply_template(database_url, tmp_path, served.url, "--template", str(template))

    assert result.returncode == 2
    assert "invalid bank template" in result.stderr
    assert name in result.stderr
    assert fake.calls == []
    assert applications(engine) == []
