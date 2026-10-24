"""The API's one `RuntimeSettings`, built in the app lifespan and read through a dependency.

Until `start()` has finished the dependency refuses with 503 `settings_not_loaded`, so nothing is
served (and nothing authenticates) before the identity and other DB-stored settings are loaded.
"""

from typing import Annotated

from fastapi import Depends

from cashapp.api.errors import ApiError
from cashapp.services.runtime_settings import RuntimeSettings

_runtime: RuntimeSettings | None = None


def set_runtime_settings(runtime: RuntimeSettings | None) -> None:
    """The lifespan installs the started instance; ``None`` clears it (shutdown, tests)."""
    global _runtime
    _runtime = runtime


def peek_runtime_settings() -> RuntimeSettings | None:
    """The installed instance, started or not, or None. For code that can fall back."""
    return _runtime


def get_runtime_settings() -> RuntimeSettings:
    if _runtime is None or not _runtime.started:
        raise ApiError(503, "settings_not_loaded", "Settings are not loaded yet; retry shortly")
    return _runtime


RuntimeSettingsDep = Annotated[RuntimeSettings, Depends(get_runtime_settings)]
