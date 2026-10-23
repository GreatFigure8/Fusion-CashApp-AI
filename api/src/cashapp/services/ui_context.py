"""What the web shell needs to know about the environment it is running in."""

from dataclasses import dataclass

from cashapp.domain.config_keys import UI_ACCESS_REQUEST_URL, UI_SAMPLE_DATA
from cashapp.services.config import ConfigSnapshot
from cashapp.settings import Env


@dataclass(frozen=True, slots=True)
class UiContext:
    env: Env
    sample_data: bool
    access_request_url: str | None


def resolve_ui_context(env: Env, snapshot: ConfigSnapshot | None) -> UiContext:
    """Sample data is never shown in prod; an unreadable config yields the safe defaults."""
    if snapshot is None:
        return UiContext(env=env, sample_data=False, access_request_url=None)
    return UiContext(
        env=env,
        sample_data=env != "prod" and snapshot.get(UI_SAMPLE_DATA),
        access_request_url=snapshot.get(UI_ACCESS_REQUEST_URL),
    )
