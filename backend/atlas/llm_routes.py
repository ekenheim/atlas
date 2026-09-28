"""The LLM route recorder: which LiteLLM deployment backs each alias Atlas uses.

Aliases (`atlas-extract`, `atlas-reflect`) can be re-pointed in LiteLLM at any time, so each run
records what they resolve to when it starts. The only call is `GET /model/info` with Atlas's
key; it never calls a model, so it costs no tokens.

Assumed response shape (a list of deployments, secrets masked or omitted):

    {"data": [{"model_name": "atlas-extract",
               "litellm_params": {"model": "minimax/MiniMax-M3", "api_base": "..."},
               "model_info": {"id": "<deployment hash>", "db_model": false, ...}}]}

Sources: LiteLLM's Model Management docs ("GET /model/info returns the full model list with API
keys masked"), the `/model/info` response quoted in BerriAI/litellm issue #5524, and the
2026-09-28 dev probe (`docs/research/litellm-dev-probe.md`), whose `x-litellm-model-id` response
header is the same deployment hash. The `{"data": [...]}` wrapper is what the proxy's
`model_info_v1` returns. A virtual key sees only the models it may call. None of this has been
checked against a live response yet; the CI fake (`tests/fakes/litellm.py`) serves this shape.
"""

from collections.abc import Sequence
from typing import Self

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from atlas.settings import Settings

# /model/info is a database read in LiteLLM; a readiness probe must not hang on it.
DEFAULT_TIMEOUT = 10.0


class LiteLLMError(Exception):
    """Base class for route-recorder errors."""


class LiteLLMUnavailable(LiteLLMError):
    """LiteLLM could not be reached, refused Atlas's key, or answered with an error."""


class AliasNotRouted(LiteLLMError):
    """An alias Atlas uses is not visible to Atlas's key, so no call to it could succeed."""

    def __init__(self, aliases: Sequence[str]) -> None:
        self.aliases = list(aliases)
        super().__init__(f"no LiteLLM deployment for alias(es): {', '.join(self.aliases)}")


class RoutedDeployment(BaseModel):
    """One deployment behind an alias: the provider model and LiteLLM's deployment ID."""

    model_config = ConfigDict(frozen=True)

    model: str
    model_id: str | None


class _Params(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str


class _Info(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None


class _Deployment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model_name: str
    litellm_params: _Params
    model_info: _Info = _Info()


class _ModelInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: list[_Deployment]


class LiteLLMRoutes:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        transport: httpx2.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx2.BaseTransport | None = None
    ) -> "LiteLLMRoutes | None":
        """The recorder for the configured LiteLLM, or None when LiteLLM is disabled."""
        if not settings.litellm_url or not settings.litellm_api_key:
            return None
        return cls(settings.litellm_url, settings.litellm_api_key, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def routes(self, aliases: Sequence[str]) -> dict[str, list[RoutedDeployment]]:
        """The deployments behind each alias. Raises `AliasNotRouted` if any alias has none."""
        deployments = self._model_info()
        routed: dict[str, list[RoutedDeployment]] = {}
        for alias in aliases:
            found = sorted(
                {
                    (each.litellm_params.model, each.model_info.id)
                    for each in deployments
                    if each.model_name == alias
                },
                key=lambda pair: (pair[0], pair[1] or ""),
            )
            routed[alias] = [RoutedDeployment(model=m, model_id=i) for m, i in found]
        missing = [alias for alias, found in routed.items() if not found]
        if missing:
            raise AliasNotRouted(missing)
        return routed

    def _model_info(self) -> list[_Deployment]:
        try:
            response = self._client.get("/model/info")
        except httpx2.TransportError as error:
            raise LiteLLMUnavailable(f"GET /model/info: {error}") from error
        if not response.is_success:
            # The body can echo request details; the status is enough to act on.
            raise LiteLLMUnavailable(f"GET /model/info: HTTP {response.status_code}")
        try:
            return _ModelInfo.model_validate_json(response.content).data
        except ValidationError as error:
            raise LiteLLMUnavailable(f"GET /model/info: unexpected response: {error}") from error
