"""The fixed question sets a replay asks (`configs/replay/question-sets.yaml`)."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class QuestionSetError(ValueError):
    """The question-set config is missing or invalid."""


class ReplayQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=1, max_length=4000)


class QuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    description: str | None = None
    questions: list[ReplayQuestion] = Field(min_length=1, max_length=10)

    @property
    def sha256(self) -> str:
        """SHA-256 of the set's canonical JSON, so an unversioned edit is still visible."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class _QuestionSets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_sets: dict[str, QuestionSet]


def load_question_sets(path: Path) -> dict[str, QuestionSet]:
    """Every question set by name; raises `QuestionSetError`."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        sets = _QuestionSets.model_validate(document).question_sets
    except OSError as error:
        raise QuestionSetError(f"{path}: {error.strerror}") from None
    except (yaml.YAMLError, ValidationError) as error:
        raise QuestionSetError(f"{path}: {error}") from None
    for name, question_set in sets.items():
        keys = [question.key for question in question_set.questions]
        if len(set(keys)) != len(keys):
            raise QuestionSetError(f"{path}: question keys must be unique in {name!r}")
    return sets
