"""Secrets stored encrypted in the database: a `SecretSource` to read them and a writer to set them.

A secret setting (`*_ref`) holds the secret's NAME. The value is written once through
`AppSecretWriter`, encrypted with the master key, and read back only at the moment of use by
`DbSecretSource`. Values are never returned by any API and never logged.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from cashapp.data.models.app_secret import AppSecret
from cashapp.data.repositories.app_secrets import AppSecretRepository
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.secrets import SecretCipher, SecretResolutionError
from cashapp.services.config import ConfigAudit, ConfigForbidden, ConfigValidationError

# 120 characters at most so "secret.<name>" fits CONFIG_CHANGE.KEY (128).
SECRET_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,119}$"  # noqa: S105
MAX_VALUE_CHARS = 16_384
AUDIT_KEY_PREFIX = "secret."


class DbSecretSource:
    """Resolves a secret name to its decrypted value, reading the row in its own unit of work."""

    def __init__(self, uow_factory: UowFactory, cipher: SecretCipher) -> None:
        self._uow_factory = uow_factory
        self._cipher = cipher

    async def resolve(self, ref: str) -> str:
        async with self._uow_factory() as uow:
            row = await uow.repo(AppSecretRepository).by_name(ref)
            # Read inside the unit of work: closing it expires the row's attributes.
            ciphertext = None if row is None else row.ciphertext
        if ciphertext is None:
            raise SecretResolutionError(ref)
        return self._cipher.decrypt(ref, ciphertext)


@dataclass(frozen=True, slots=True)
class SecretInfo:
    name: str
    version: int
    updated_at: datetime
    updated_by: str


def _info(row: AppSecret) -> SecretInfo:
    return SecretInfo(row.name, row.version, row.updated_at, row.updated_by)


def _invalid(name: str, message: str) -> ConfigValidationError:
    return ConfigValidationError(AUDIT_KEY_PREFIX + name, [{"loc": ["value"], "msg": message}])


async def list_secrets(uow: UnitOfWork) -> list[SecretInfo]:
    """Names and metadata only."""
    return [_info(row) for row in await uow.repo(AppSecretRepository).all()]


class AppSecretWriter:
    """Encrypted, audited writes. Never commits: the caller owns the transaction."""

    def __init__(self, cipher: SecretCipher, clock: Clock | None = None) -> None:
        self._cipher = cipher
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def set(
        self, uow: UnitOfWork, name: str, value: str, principal: Principal, reason: str
    ) -> SecretInfo:
        if not principal.can(Permission.CONFIG_WRITE):
            raise ConfigForbidden(f"Missing permission {Permission.CONFIG_WRITE.value}")
        if re.fullmatch(SECRET_NAME_PATTERN, name) is None:
            raise _invalid(name, "Name must be lower-case letters, digits, '.', '_' or '-'")
        if not value.strip():
            raise _invalid(name, "A value is required")
        if len(value) > MAX_VALUE_CHARS:
            raise _invalid(name, f"Value must be at most {MAX_VALUE_CHARS} characters")

        repo = uow.repo(AppSecretRepository)
        row = await repo.by_name_for_update(name)
        now = self._clock.now()
        blob = self._cipher.encrypt(name, value)
        if row is None:
            row = await repo.add(
                AppSecret(
                    name=name,
                    ciphertext=blob,
                    version=1,
                    updated_at=now,
                    updated_by=principal.subject,
                )
            )
            old: JsonValue | None = None
        else:
            row = await repo.update(
                row,
                ciphertext=blob,
                version=row.version + 1,
                updated_at=now,
                updated_by=principal.subject,
            )
            old = {"version": row.version - 1}
        # The audit row records that a value was set, never the value or its ciphertext.
        await ConfigAudit.record(
            uow,
            AUDIT_KEY_PREFIX + name,
            old,
            {"version": row.version},
            principal,
            reason,
            clock=self._clock,
        )
        return _info(row)
