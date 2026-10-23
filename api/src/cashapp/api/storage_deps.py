"""FastAPI dependency for the object store. Defined once; routers import ``ObjectStoreDep``."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.factory import build_object_store
from cashapp.settings import get_settings


@lru_cache
def get_object_store() -> ObjectStore:
    """One object store per process, built from settings. Tests override this dependency."""
    return build_object_store(get_settings())


ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]
