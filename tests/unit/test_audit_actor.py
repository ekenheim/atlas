import pytest

from atlas.audit import Actor


def test_an_actor_must_name_someone() -> None:
    with pytest.raises(ValueError, match="actor"):
        Actor(" ")


def test_an_actor_keeps_its_configured_name() -> None:
    assert Actor("local-researcher").name == "local-researcher"
