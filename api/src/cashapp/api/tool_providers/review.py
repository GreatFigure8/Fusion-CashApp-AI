"""Chat-tool service providers for the Review board (chat-agent-tool-registry contract)."""

from typing import Any

from cashapp.api.config_deps import get_runtime_config
from cashapp.api.deps import get_uow_factory
from cashapp.api.runtime_deps import get_runtime_settings
from cashapp.api.storage_deps import get_object_store
from cashapp.services.review.upload import UploadService


async def _upload_service() -> UploadService:
    return UploadService(
        get_uow_factory(), get_object_store(get_runtime_settings()), await get_runtime_config()
    )


PROVIDERS: dict[type[Any], Any] = {UploadService: _upload_service}
