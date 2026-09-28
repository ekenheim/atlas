"""The minimal run record (spec Part B stories 15 and 32; Phase 4 extends it).

A run records what produced its results: the code version, the Hindsight version, the bank
template version, and the LiteLLM deployment behind each alias Atlas uses, read when the run
starts, plus token totals when it finishes.
"""

import json
import uuid
from datetime import datetime

import httpx2
from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy import Engine, RowMapping, text

from atlas import __version__
from atlas.bank_template import applied_template_version
from atlas.hindsight import HindsightGateway
from atlas.llm_routes import LiteLLMRoutes, RoutedDeployment
from atlas.settings import Settings

RoutedModels = dict[str, list[RoutedDeployment]]
_ROUTED_MODELS = TypeAdapter(RoutedModels)


class RunNotStartable(Exception):
    """A run's provenance can't be recorded (e.g. no template applied to the bank yet)."""


class RunNotFound(LookupError):
    """No unfinished run with that ID."""


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: str
    code_version: str
    hindsight_version: str
    template_version: str
    routed_models: RoutedModels
    tokens_in: int
    tokens_out: int
    started_at: datetime
    finished_at: datetime | None


def code_version(settings: Settings) -> str:
    """The image's commit SHA when the build set one, else the package version."""
    return settings.code_version or __version__


class RunRecorder:
    def __init__(
        self,
        engine: Engine,
        gateway: HindsightGateway,
        routes: LiteLLMRoutes,
        *,
        aliases: list[str],
        code_version: str,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._routes = routes
        self._aliases = aliases
        self._code_version = code_version

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        engine: Engine,
        *,
        hindsight_transport: httpx2.BaseTransport | None = None,
        litellm_transport: httpx2.BaseTransport | None = None,
    ) -> "RunRecorder | None":
        """The recorder for the configured services, or None unless Hindsight and LiteLLM are."""
        gateway = HindsightGateway.from_settings(settings, transport=hindsight_transport)
        routes = LiteLLMRoutes.from_settings(settings, transport=litellm_transport)
        if gateway is None or routes is None:
            for client in (gateway, routes):
                if client is not None:
                    client.close()
            return None
        return cls(
            engine,
            gateway,
            routes,
            aliases=settings.llm_aliases(),
            code_version=code_version(settings),
        )

    def close(self) -> None:
        self._gateway.close()
        self._routes.close()

    def start(self, kind: str) -> Run:
        """Record a new run, reading Hindsight's version and the aliases' routes now.

        Raises `RunNotStartable` when the bank has no applied template, and the gateway's or
        route recorder's errors when Hindsight or LiteLLM can't answer: a run whose models
        can't be recorded doesn't start.
        """
        with self._engine.connect() as connection:
            template_version = applied_template_version(connection, self._gateway.bank_id)
        if template_version is None:
            raise RunNotStartable(
                f"no bank template applied to {self._gateway.bank_id!r};"
                " run `atlas hindsight apply-template` first"
            )
        hindsight_version = self._gateway.server_version().api_version
        routed = self._routes.routes(self._aliases)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO run (id, kind, code_version, hindsight_version,"
                        " template_version, routed_models)"
                        " VALUES (:id, :kind, :code, :hindsight, :template, CAST(:routed AS jsonb))"
                        " RETURNING *"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "kind": kind,
                        "code": self._code_version,
                        "hindsight": hindsight_version,
                        "template": template_version,
                        "routed": _ROUTED_MODELS.dump_json(routed).decode(),
                    },
                )
                .mappings()
                .one()
            )
        return _run(row)

    def finish(self, run_id: uuid.UUID, *, tokens_in: int, tokens_out: int) -> Run:
        """Record the run's token totals and finish it. Raises `RunNotFound` if it isn't open."""
        if tokens_in < 0 or tokens_out < 0:
            raise ValueError("token totals can't be negative")
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "UPDATE run SET tokens_in = :tokens_in, tokens_out = :tokens_out,"
                        " finished_at = now() WHERE id = :id AND finished_at IS NULL"
                        " RETURNING *"
                    ),
                    {"id": run_id, "tokens_in": tokens_in, "tokens_out": tokens_out},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RunNotFound(f"no unfinished run {run_id}")
        return _run(row)

    def get(self, run_id: uuid.UUID) -> Run | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(text("SELECT * FROM run WHERE id = :id"), {"id": run_id})
                .mappings()
                .one_or_none()
            )
        return None if row is None else _run(row)


def _run(row: RowMapping) -> Run:
    values = dict(row)
    routed = values["routed_models"]
    values["routed_models"] = _ROUTED_MODELS.validate_python(
        json.loads(routed) if isinstance(routed, str) else routed
    )
    return Run.model_validate(values)
