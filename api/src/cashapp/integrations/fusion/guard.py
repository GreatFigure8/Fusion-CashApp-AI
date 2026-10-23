"""Write rails: writes are off by default and a production pod is refused outside prod."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError

if TYPE_CHECKING:
    from cashapp.integrations.fusion.client import FusionClient
    from cashapp.settings import Settings

WRITE_METHODS: frozenset[str] = frozenset(
    {
        "apply_receipt",
        "unapply_receipt",
        "set_receipt_comment",
        "attach_to_receipt",
        "rest_post",
    }
)


class WriteGuard:
    def __init__(
        self, *, write_enabled: bool, env: str, pod_name: str, pod_is_production: bool
    ) -> None:
        self._write_enabled = write_enabled
        self._env = env
        self._pod_name = pod_name
        self._pod_is_production = pod_is_production

    @classmethod
    def from_settings(cls, settings: Settings, pod_name: str) -> WriteGuard:
        pod = settings.fusion.pods[pod_name]
        return cls(
            write_enabled=settings.fusion.write_enabled,
            env=settings.env,
            pod_name=pod_name,
            pod_is_production=pod.is_production,
        )

    @classmethod
    def allow_all(cls) -> WriteGuard:
        return cls(write_enabled=True, env="local", pod_name="fake", pod_is_production=False)

    def check_source(self, method: str, environment: str | None) -> None:
        """Refuse when the MCP server says the Fusion source is production outside prod."""
        if environment == "production" and self._env != "prod":
            raise FusionError(
                ErrorCode.FUSION_WRITE_DISABLED,
                f"{method}: the MCP source is a production Fusion instance; writes are refused "
                f"outside the prod environment",
                retryable=False,
            )

    def check(self, method: str) -> None:
        if not self._write_enabled:
            raise FusionError(
                ErrorCode.FUSION_WRITE_DISABLED,
                f"{method}: Fusion writes are disabled (fusion.write_enabled is false)",
                retryable=False,
            )
        if self._pod_is_production and self._env != "prod":
            raise FusionError(
                ErrorCode.FUSION_WRITE_DISABLED,
                f"{method}: pod '{self._pod_name}' is production; writes are refused "
                f"outside the prod environment",
                retryable=False,
            )


class _ReadOnlyClient:
    """Delegates reads; every write method raises `FUSION_WRITE_DISABLED` before any I/O."""

    def __init__(self, inner: FusionClient) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name in WRITE_METHODS:
            return self._refuse(name)
        return getattr(self._inner, name)

    @staticmethod
    def _refuse(name: str) -> Any:
        async def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise FusionError(
                ErrorCode.FUSION_WRITE_DISABLED,
                f"{name}: this Fusion client is read-only",
                retryable=False,
            )

        return refuse


def read_only(client: FusionClient) -> FusionClient:
    """Wrap `client` so any write raises `FUSION_WRITE_DISABLED` (used by spikes and preflight)."""
    return cast("FusionClient", _ReadOnlyClient(client))
