"""Shared FastAPI dependencies. Each is defined once and imported by every router."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.data.engine import create_engine
from cashapp.data.uow import UowFactory, make_uow_factory
from cashapp.settings import get_settings


@lru_cache
def get_uow_factory() -> UowFactory:
    """One engine and unit-of-work factory per process, built from the ATP settings."""
    atp = get_settings().atp
    # create_engine already sets pool_pre_ping; passing it twice would be a TypeError.
    options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
    engine = create_engine(atp.url().render_as_string(hide_password=False), **options)
    return make_uow_factory(engine)


UowFactoryDep = Annotated[UowFactory, Depends(get_uow_factory)]
