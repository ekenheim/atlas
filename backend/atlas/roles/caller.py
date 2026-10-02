"""The role caller: how every research role calls the LLM (spec Phase 4, "Roles"; §7.2-§7.5).

One call of a role is:

1. **Budget.** The run's tokens so far (every chat completion of every role in the run) are
   compared with the per-run token budget; at or over it, `TokenBudgetExhausted` is raised
   and no request is made. Each request's `max_tokens` is the smaller of the role's cap and
   the budget left, so a call can overshoot only by its prompt.
2. **Request.** `POST /chat/completions` on LiteLLM with Atlas's key: the configured model
   (MiniMax-M3), the configured extra body (thinking disabled), a strict `json_schema`
   `response_format` from the role's response model, and `metadata` naming the run and the
   role. The system message is the fixed directives plus the role's versioned prompt; the
   user message is a JSON object whose `request` is the role's request and whose
   `retrieved_data` is the quoted, low-trust retrieved text. Retrieved text never enters the
   system message.
3. **Validation.** The answer (a leading `<think>...</think>` block and a code fence are
   stripped, as the dev probe needed) is validated with the role's Pydantic model. A field
   the model does not name is dropped and recorded on the attempt (`ignored_fields`), never an
   error (pilot-fixes ticket 26: the strict schema still forbids it, but a model that adds one
   anyway is not asked for a whole new answer). If validation fails, one repair is asked for
   in the same conversation, with the validation errors.
   If that fails too, the call is **quarantined**: its outputs stay visible in the record,
   `RoleOutputQuarantined` is raised, and nothing is returned for use. An answer that fails
   validation because the model stopped at the output cap (the completion's finish reason
   is `length`, or the tokens it used reach the cap) is **truncated** instead: no repair is
   asked for (it would be cut at the same cap), the call is recorded `truncated` and
   `RoleOutputTruncated` (a kind of quarantine, so every role's failure path stays as it
   was) is raised. A caller may give one call a larger cap (`max_output_tokens`).
4. **Failures.** A quota failure (HTTP 429, LiteLLM's `budget_exceeded` for the key's
   maxBudget) or an outage (HTTP 502-504, a 5xx naming one, a connection failure) raises
   `TransientFailure`, which pauses the queue for a pausable job kind and requeues the job
   (atlas.jobs.pacing). Anything else raises `RoleCallFailed`, an ordinary failed attempt.

Every call is recorded (`role_call`), and every chat completion LiteLLM answered with its
routed model and tokens (`llm_call`), whether or not its output was used.
"""

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any, Self, cast

import httpx2
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import Engine, text

from atlas.jobs.pacing import TransientFailure, classify_error_text, classify_status
from atlas.roles.contract import DIRECTIVES, REPAIR_DIRECTIVE, QuotedText, Role
from atlas.roles.records import RoleCallStatus, run_usage
from atlas.settings import Settings

MAX_ATTEMPTS = 2  # the call and one repair
_ERROR_TEXT_LIMIT = 500

type _Path = list[str | int]  # a field's place in an answer: keys and list indices


class RoleCallFailed(Exception):
    """A role call failed for a reason that isn't quota or an outage (an ordinary failure)."""


class RoleOutputQuarantined(RoleCallFailed):
    """The role's output failed validation twice; it is recorded but must never be used."""

    def __init__(self, role_call_id: uuid.UUID, role: str) -> None:
        self.role_call_id = role_call_id
        self.role = role
        super().__init__(
            f"{role} output quarantined after a failed repair (role call {role_call_id})"
        )


class RoleOutputTruncated(RoleOutputQuarantined):
    """The model stopped at the output cap before its answer was complete; it is recorded
    but never used, and no repair was asked for."""

    def __init__(self, role_call_id: uuid.UUID, role: str, max_tokens: int) -> None:
        self.role_call_id = role_call_id
        self.role = role
        self.max_tokens = max_tokens
        RoleCallFailed.__init__(
            self,
            f"{role} output cut off at its {max_tokens}-token output cap"
            f" (role call {role_call_id})",
        )


class TokenBudgetExhausted(Exception):
    """The run has spent its token budget; no further LLM call is made for it."""

    def __init__(self, run_id: uuid.UUID, spent: int, budget: int) -> None:
        self.run_id = run_id
        self.spent = spent
        self.budget = budget
        super().__init__(f"run {run_id} has spent {spent} of its {budget}-token budget")


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str | None = None


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _Message
    finish_reason: str | None = None


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class _Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    choices: list[_Choice] = Field(min_length=1)
    usage: _Usage


class _ErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str = ""
    type: str | None = None


class _ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    error: _ErrorBody


class RoleCaller:
    def __init__(
        self,
        engine: Engine,
        base_url: str,
        api_key: str,
        *,
        model: str,
        extra_body: dict[str, JsonValue],
        token_budget: int,
        timeout: float,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._engine = engine
        self._model = model
        self._extra_body = extra_body
        self._token_budget = token_budget
        self._client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, engine: Engine, *, transport: httpx2.BaseTransport | None = None
    ) -> "RoleCaller | None":
        """The caller for the configured LiteLLM, or None when LiteLLM is disabled."""
        if not settings.litellm_url or not settings.litellm_api_key:
            return None
        return cls(
            engine,
            settings.litellm_url,
            settings.litellm_api_key,
            model=settings.llm_role_model,
            extra_body=settings.llm_role_extra_body,
            token_budget=settings.run_token_budget,
            timeout=settings.llm_role_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def call[RequestT: BaseModel, ResponseT: BaseModel](
        self,
        role: Role[RequestT, ResponseT],
        request: RequestT,
        *,
        run_id: uuid.UUID,
        retrieved: Sequence[QuotedText] = (),
    ) -> ResponseT:
        """Call `role` within run `run_id` and return its validated output (see the module)."""
        return self.call_recorded(role, request, run_id=run_id, retrieved=retrieved)[0]

    def call_recorded[RequestT: BaseModel, ResponseT: BaseModel](
        self,
        role: Role[RequestT, ResponseT],
        request: RequestT,
        *,
        run_id: uuid.UUID,
        retrieved: Sequence[QuotedText] = (),
        max_output_tokens: int | None = None,
    ) -> tuple[ResponseT, uuid.UUID]:
        """`call`, also returning the ID of the `role_call` row that recorded it. With
        `max_output_tokens`, this call's output cap instead of the role's."""
        cap = role.max_output_tokens if max_output_tokens is None else max_output_tokens
        if cap <= 0:
            raise ValueError("max_output_tokens must be positive")
        request_json = request.model_dump(mode="json")
        quoted = [each.model_dump(mode="json") for each in retrieved]
        role_call_id = self._open(role, run_id, request_json, quoted)
        user = json.dumps({"request": request_json, "retrieved_data": quoted}, ensure_ascii=False)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": f"{DIRECTIVES}\n\n{role.prompt.text}"},
            {"role": "user", "content": user},
        ]
        for attempt in range(1, MAX_ATTEMPTS + 1):
            with self._engine.connect() as connection:
                spent = run_usage(connection, run_id).total
            if spent >= self._token_budget:
                error = TokenBudgetExhausted(run_id, spent, self._token_budget)
                self._close(role_call_id, "budget_exhausted", error=str(error))
                raise error
            max_tokens = min(cap, self._token_budget - spent)
            try:
                completion, model_id = self._complete(role, messages, run_id, max_tokens)
            except (TransientFailure, RoleCallFailed) as error:
                self._close(role_call_id, "failed", error=str(error))
                raise
            content = completion.choices[0].message.content or ""
            output, errors, ignored = _validate(role.response, content)
            self._record_attempt(
                role_call_id, run_id, attempt, completion, model_id, content, errors, ignored
            )
            if output is not None:
                self._close(role_call_id, "accepted", output=output.model_dump(mode="json"))
                return output, role_call_id
            if _cut_off(completion, max_tokens):
                truncated = RoleOutputTruncated(role_call_id, role.name, max_tokens)
                self._close(role_call_id, "truncated", error=str(truncated))
                raise truncated
            messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"{REPAIR_DIRECTIVE}\n\n{json.dumps(errors)}"},
            ]
        quarantined = RoleOutputQuarantined(role_call_id, role.name)
        self._close(role_call_id, "quarantined", error=str(quarantined))
        raise quarantined

    def _complete(
        self,
        role: Role[Any, Any],
        messages: list[dict[str, str]],
        run_id: uuid.UUID,
        max_tokens: int,
    ) -> tuple[_Completion, str | None]:
        body: dict[str, Any] = {
            **self._extra_body,
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": role.name,
                    "strict": True,
                    "schema": role.response_schema(),
                },
            },
            "max_tokens": max_tokens,
            "metadata": {"run_id": str(run_id), "role": role.name},
        }
        try:
            response = self._client.post("/chat/completions", json=body)
        except httpx2.TransportError as error:
            raise TransientFailure(
                "unavailable", f"LiteLLM chat completion: {type(error).__name__}: {error}"
            ) from error
        if not response.is_success:
            envelope = _error(response)
            message = f"LiteLLM chat completion: HTTP {response.status_code}: {envelope.message}"
            failure = classify_status(response.status_code)
            if failure is None and envelope.type == "budget_exceeded":
                failure = "quota"  # the `atlas` key's maxBudget: it resets, like a quota
            if failure is None and response.status_code >= 500:
                failure = classify_error_text(envelope.message)
            if failure is not None:
                raise TransientFailure(failure, message)
            raise RoleCallFailed(message)
        try:
            completion = _Completion.model_validate_json(response.content)
        except ValidationError as error:
            raise RoleCallFailed(f"LiteLLM chat completion: unexpected response: {error}") from None
        return completion, response.headers.get("x-litellm-model-id")

    def _open(
        self,
        role: Role[Any, Any],
        run_id: uuid.UUID,
        request: dict[str, Any],
        quoted: list[dict[str, Any]],
    ) -> uuid.UUID:
        role_call_id = uuid.uuid4()
        with self._engine.begin() as connection:
            open_run = connection.execute(
                text("SELECT 1 FROM run WHERE id = :run AND finished_at IS NULL FOR SHARE"),
                {"run": run_id},
            ).one_or_none()
            if open_run is None:
                raise RoleCallFailed(f"no unfinished run {run_id}")
            connection.execute(
                text(
                    "INSERT INTO role_call (id, run_id, role, prompt_name, prompt_version,"
                    " prompt_sha256, model, request, retrieved) VALUES (:id, :run, :role,"
                    " :prompt_name, :prompt_version, :prompt_sha256, :model,"
                    " CAST(:request AS jsonb), CAST(:retrieved AS jsonb))"
                ),
                {
                    "id": role_call_id,
                    "run": run_id,
                    "role": role.name,
                    "prompt_name": role.prompt.name,
                    "prompt_version": role.prompt.version,
                    "prompt_sha256": role.prompt.sha256,
                    "model": self._model,
                    "request": json.dumps(request),
                    "retrieved": json.dumps(quoted),
                },
            )
        return role_call_id

    def _record_attempt(
        self,
        role_call_id: uuid.UUID,
        run_id: uuid.UUID,
        attempt: int,
        completion: _Completion,
        model_id: str | None,
        content: str,
        errors: list[dict[str, JsonValue]] | None,
        ignored: list[_Path],
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO llm_call (id, role_call_id, run_id, attempt, response_model,"
                    " model_id, tokens_in, tokens_out, content, validation_errors,"
                    " ignored_fields) VALUES (:id, :role_call, :run, :attempt, :model,"
                    " :model_id, :tokens_in, :tokens_out, :content, CAST(:errors AS jsonb),"
                    " CAST(:ignored AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "role_call": role_call_id,
                    "run": run_id,
                    "attempt": attempt,
                    "model": completion.model,
                    "model_id": model_id,
                    "tokens_in": completion.usage.prompt_tokens,
                    "tokens_out": completion.usage.completion_tokens,
                    "content": content,
                    "errors": None if errors is None else json.dumps(errors),
                    "ignored": json.dumps(ignored),
                },
            )

    def _close(
        self,
        role_call_id: uuid.UUID,
        status: RoleCallStatus,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE role_call SET status = :status, output = CAST(:output AS jsonb),"
                    " error = :error, finished_at = now() WHERE id = :id"
                ),
                {
                    "id": role_call_id,
                    "status": status,
                    "output": None if output is None else json.dumps(output),
                    "error": None if error is None else error[:_ERROR_TEXT_LIMIT],
                },
            )


def _cut_off(completion: _Completion, max_tokens: int) -> bool:
    """Whether the model stopped at the output cap rather than at the end of its answer."""
    return (
        completion.choices[0].finish_reason == "length"
        or completion.usage.completion_tokens >= max_tokens
    )


_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(?P<body>.*)\n\s*```$", re.DOTALL)


def _json_text(content: str) -> str:
    """The JSON in `content`, past a leading `<think>` block and out of a code fence."""
    stripped = content.strip()
    if not stripped.startswith("{") and "</think>" in stripped:
        stripped = stripped.split("</think>", 1)[1].strip()
    fenced = _FENCE.match(stripped)
    return fenced["body"].strip() if fenced else stripped


def _validate[ResponseT: BaseModel](
    model: type[ResponseT], content: str
) -> tuple[ResponseT | None, list[dict[str, JsonValue]] | None, list[_Path]]:
    """The answer validated, or why not, and the unknown fields dropped from it.

    A field the response model does not name (pydantic's `extra_forbidden`) is no error: it is
    removed from the answer, recorded, and the rest validated again. The strict schema sent to
    the model still forbids it; code only stops asking for a whole new answer because of it.
    A missing or malformed field stays an error."""
    answer = _json_text(content)
    ignored: list[_Path] = []
    while True:
        try:
            return model.model_validate_json(answer), None, ignored
        except ValidationError as error:
            details = error.errors(include_url=False, include_input=False, include_context=False)
            extra: list[_Path] = [list(e["loc"]) for e in details if e["type"] == "extra_forbidden"]
            stripped = _without(answer, extra) if extra else None
            if stripped is None:
                errors: list[dict[str, JsonValue]] = [
                    {"type": each["type"], "loc": list(each["loc"]), "msg": each["msg"]}
                    for each in details
                ]
                return None, errors, ignored
            ignored.extend(extra)
            answer = stripped


def _without(answer: str, paths: list[_Path]) -> str | None:
    """`answer` with the fields at `paths` removed, or None if one of them can't be found
    there (a location pydantic names through a union or a validator, say)."""
    try:
        parsed: Any = json.loads(answer)
    except ValueError:
        return None
    for path in paths:
        node: Any = parsed
        for step in path[:-1]:
            if isinstance(node, dict) and isinstance(step, str):
                mapping = cast(dict[str, Any], node)
                if step not in mapping:
                    return None
                node = mapping[step]
            elif isinstance(node, list) and isinstance(step, int):
                items = cast(list[Any], node)
                if not 0 <= step < len(items):
                    return None
                node = items[step]
            else:
                return None
        last = path[-1] if path else None
        if not isinstance(node, dict) or not isinstance(last, str):
            return None
        holder = cast(dict[str, Any], node)
        if last not in holder:
            return None
        del holder[last]
    return json.dumps(parsed, ensure_ascii=False)


def _error(response: httpx2.Response) -> _ErrorBody:
    try:
        body = _ErrorEnvelope.model_validate_json(response.content).error
    except ValidationError:
        return _ErrorBody(message=response.reason_phrase)
    return _ErrorBody(message=body.message[:_ERROR_TEXT_LIMIT], type=body.type)
