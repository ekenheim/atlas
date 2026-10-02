"""Role definitions: versioned prompts from the repo, and response schemas LiteLLM can enforce."""

import hashlib
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from atlas.roles import PROMPTS_DIR, NotStrict, Prompt, Role, RoleOutput
from atlas.roles.investigator import INVESTIGATOR
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


# The Investigator's Claim, as the strict schema sent to the model has always required it
# (pilot-fixes ticket 26 changes what code accepts, never what the schema asks for).
CLAIM_FIELDS = [
    "passage_id",
    "subject_company_id",
    "predicate",
    "object_company_id",
    "object_name",
    "object_text",
    "product",
    "layer",
    "quote",
    "quote_start",
    "quote_end",
    "epistemic_type",
]


def test_the_investigator_s_strict_schema_still_requires_every_field_and_forbids_others() -> None:
    schema = INVESTIGATOR.response_schema()

    assert (schema["required"], schema["additionalProperties"]) == (["claims"], False)
    claim = schema["$defs"]["ProposedClaim"]
    assert claim["required"] == CLAIM_FIELDS
    assert list(claim["properties"]) == CLAIM_FIELDS
    assert claim["additionalProperties"] is False


def test_investigator_v9_lists_the_claim_s_fields_and_names_the_ones_it_has_not() -> None:
    prompt = INVESTIGATOR.prompt

    assert (prompt.name, prompt.version) == ("investigator", 9)
    assert b"\r\n" not in (PROMPTS_DIR / "investigator.v9.md").read_bytes()
    for field in CLAIM_FIELDS:
        assert f"`{field}`" in prompt.text
    # The two fields the fifth pilot run's answers added, by name.
    assert "`subject_name`" in prompt.text and "`claim_id`" in prompt.text
    # An analyst's question in a transcript is context, not the company's statement (ticket 22).
    assert "analyst" in prompt.text
    # v8 stays as it was committed: its recorded hash still verifies.
    assert (PROMPTS_DIR / "investigator.v8.md").exists()
