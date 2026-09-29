"""Role definitions: versioned prompts from the repo, and response schemas LiteLLM can enforce."""

import hashlib
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from atlas.roles import PROMPTS_DIR, NotStrict, Prompt, Role, RoleOutput
from tests.harness import REPO

PROMPTS = REPO / "tests" / "fixtures" / "prompts"


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


class Nested(RoleOutput):
    text: str


class Strict(RoleOutput):
    answer: str
    notes: list[Nested]
    maybe: str | None


def test_a_prompt_is_loaded_by_name_and_version_with_its_hash() -> None:
    prompt = Prompt.load(PROMPTS, "example", 1)

    raw = (PROMPTS / "example.v1.md").read_bytes()
    assert (prompt.name, prompt.version) == ("example", 1)
    assert prompt.text == raw.decode("utf-8")
    assert prompt.sha256 == hashlib.sha256(raw).hexdigest()


def test_a_missing_prompt_version_fails_loudly() -> None:
    with pytest.raises(FileNotFoundError):
        Prompt.load(PROMPTS, "example", 2)


def test_role_prompts_live_in_the_package() -> None:
    assert PROMPTS_DIR == Path(__file__).resolve().parents[2] / "backend/atlas/roles/prompts"


def test_a_strict_response_model_makes_a_strict_json_schema() -> None:
    role = Role(
        name="strict", prompt=Prompt.load(PROMPTS, "example", 1), request=Request, response=Strict
    )

    schema = role.response_schema()
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["answer", "maybe", "notes"]
    assert schema["$defs"]["Nested"]["additionalProperties"] is False


class WithDefault(RoleOutput):
    answer: str
    notes: str = "none"


class Open(BaseModel):
    answer: str


@pytest.mark.parametrize("response", [WithDefault, Open])
def test_a_response_model_litellm_couldn_t_enforce_strictly_is_rejected(
    response: type[BaseModel],
) -> None:
    with pytest.raises(NotStrict):
        Role(
            name="loose",
            prompt=Prompt.load(PROMPTS, "example", 1),
            request=Request,
            response=response,  # pyright: ignore[reportArgumentType]
        )
