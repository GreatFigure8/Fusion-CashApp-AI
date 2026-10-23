"""Builds the object store for the running environment."""

from pathlib import Path

from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.local import LocalFolderObjectStore
from cashapp.integrations.storage.oci import OciObjectStore
from cashapp.settings import Settings


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.env == "local":
        return LocalFolderObjectStore(Path(settings.intake.drop_folder) / ".objectstore")
    return OciObjectStore.from_settings(settings.object_storage)
