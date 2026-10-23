"""OCI Object Storage (Ashburn) behind the ``ObjectStore`` interface.

Unverified against live until a DEV bucket probe (``-m live``) passes.
"""

import asyncio
import base64
import hashlib
import os
from collections.abc import Mapping
from typing import Any, Protocol, Self

from cashapp.integrations.storage.base import ObjectNotFound, ObjectRef
from cashapp.integrations.storage.keys import validate_key
from cashapp.settings import ObjectStorageSettings


class ObjectStorageClientLike(Protocol):
    """The slice of ``oci.object_storage.ObjectStorageClient`` this store uses."""

    def put_object(
        self, namespace_name: str, bucket_name: str, object_name: str, *args: Any, **kwargs: Any
    ) -> Any: ...

    def get_object(
        self, namespace_name: str, bucket_name: str, object_name: str, **kwargs: Any
    ) -> Any: ...

    def delete_object(
        self, namespace_name: str, bucket_name: str, object_name: str, **kwargs: Any
    ) -> Any: ...

    def head_object(
        self, namespace_name: str, bucket_name: str, object_name: str, **kwargs: Any
    ) -> Any: ...


def _sdk() -> Any:
    """The OCI SDK module, imported on first use (it ships no type stubs)."""
    import oci  # pyright: ignore[reportMissingTypeStubs]

    sdk: Any = oci
    return sdk


def _is_not_found(exc: Exception) -> bool:
    """True for an OCI ``ServiceError`` with HTTP status 404."""
    is_service_error = isinstance(exc, _sdk().exceptions.ServiceError)
    return bool(is_service_error and getattr(exc, "status", None) == 404)


class OciObjectStore:
    def __init__(self, client: ObjectStorageClientLike, *, namespace: str, bucket: str) -> None:
        self._client = client
        self._namespace = namespace
        self._bucket = bucket

    @classmethod
    def from_settings(cls, s: ObjectStorageSettings) -> Self:
        sdk = _sdk()
        client: Any
        if os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
            signer = sdk.auth.signers.get_resource_principals_signer()
            client = sdk.object_storage.ObjectStorageClient({"region": s.region}, signer=signer)
        else:
            config: dict[str, Any] = sdk.config.from_file()
            config["region"] = s.region
            client = sdk.object_storage.ObjectStorageClient(config)
        return cls(client, namespace=s.namespace, bucket=s.bucket)

    async def put(
        self, key: str, data: bytes, content_type: str, metadata: Mapping[str, str]
    ) -> ObjectRef:
        validate_key(key)
        md5 = base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode("ascii")
        response = await asyncio.to_thread(
            self._client.put_object,
            self._namespace,
            self._bucket,
            key,
            data,
            content_type=content_type,
            opc_meta=dict(metadata),
            content_md5=md5,
        )
        headers = getattr(response, "headers", None)
        etag = headers.get("etag") if headers is not None else None
        return ObjectRef(
            key=key,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            etag=etag if isinstance(etag, str) else None,
        )

    async def get(self, key: str) -> bytes:
        validate_key(key)
        try:
            response = await asyncio.to_thread(
                self._client.get_object, self._namespace, self._bucket, key
            )
        except Exception as exc:
            if _is_not_found(exc):
                raise ObjectNotFound(key) from None
            raise
        return bytes(response.data.content)

    async def delete(self, key: str) -> None:
        validate_key(key)
        try:
            await asyncio.to_thread(self._client.delete_object, self._namespace, self._bucket, key)
        except Exception as exc:
            if not _is_not_found(exc):
                raise

    async def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            await asyncio.to_thread(self._client.head_object, self._namespace, self._bucket, key)
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise
        return True
