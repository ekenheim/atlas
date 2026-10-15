"""Where a statement is judged (atlas-beliefs ticket 23): the setting's three values, as the
callers read them. The judge itself is tested at the HTTP seam (`test_judged_at_record`)."""

import uuid
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from sqlalchemy import Engine

from atlas.judging import Judges, run_fact_judge
from atlas.roles.caller import RoleCaller
from tests.harness import make_settings

SESSION = uuid.uuid4()
type Mode = Literal["sessions", "always", "off"]


def judges(tmp_path: Path, mode: Mode) -> Judges:
    return Judges(cast(Engine, None), make_settings(tmp_path, fact_statement_judge=mode))


@pytest.mark.parametrize(
    ("mode", "session", "judged"),
    [
        ("sessions", SESSION, True),
        ("sessions", None, False),  # the pipeline's Readers, a bare POST /facts
        ("always", SESSION, True),
        ("always", None, True),
        ("off", SESSION, False),
        ("off", None, False),
    ],
)
def test_a_fact_is_judged_by_the_setting_and_its_session(
    tmp_path: Path, mode: Mode, session: uuid.UUID | None, judged: bool
) -> None:
    assert judges(tmp_path, mode).judges_fact(session) is judged
    assert judges(tmp_path, mode).judges_belief(session) is judged


def test_a_thesis_is_judged_unless_the_setting_is_off(tmp_path: Path) -> None:
    assert judges(tmp_path, "sessions").judges_session()
    assert judges(tmp_path, "always").judges_session()
    assert not judges(tmp_path, "off").judges_session()


def test_the_default_leaves_the_pipelines_readers_alone(tmp_path: Path) -> None:
    caller: Any = object()
    run_id = uuid.uuid4()
    for mode in ("sessions", "off"):
        settings = make_settings(tmp_path, fact_statement_judge=mode)
        assert run_fact_judge(cast(RoleCaller, caller), run_id, settings, "q") is None
    always = make_settings(tmp_path, fact_statement_judge="always")
    assert run_fact_judge(cast(RoleCaller, caller), run_id, always, "q") is not None


def test_the_setting_defaults_to_sessions_in_production() -> None:
    from atlas.settings import Settings

    assert Settings.model_fields["fact_statement_judge"].default == "sessions"
