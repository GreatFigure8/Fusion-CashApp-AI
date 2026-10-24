"""FastAPI dependency for the object store. Defined once; routers import ``ObjectStoreDep``."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.factory import build_object_store
from cashapp.services.runtime_settings import RuntimeSettings


@lru_cache
def _store_for(runtime: RuntimeSettings) -> ObjectStore:
    return build_object_store(runtime)


def get_object_store(runtime: RuntimeSettingsDep) -> ObjectStore:
    """One object store per process, built from settings. Tests override this dependency."""
    return _store_for(runtime)


ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]
