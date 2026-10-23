"""Builds the object store for the running environment."""

from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.local import LocalFolderObjectStore
from cashapp.integrations.storage.oci import OciObjectStore
from cashapp.services.runtime_settings import RuntimeSettings
from cashapp.settings import oci_signer


def build_object_store(runtime: RuntimeSettings) -> ObjectStore:
    if runtime.env == "local":
        return LocalFolderObjectStore(runtime.intake_folder() / ".objectstore")
    return OciObjectStore.from_config(runtime.object_storage(), oci_signer(runtime.settings))
