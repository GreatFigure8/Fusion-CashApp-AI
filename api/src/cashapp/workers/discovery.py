"""Role discovery: every module under the role packages that exposes ROLE or ROLES is a role."""

import importlib
import pkgutil
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Final

from cashapp.pipeline.roles import RoleSpec

ROLE_PACKAGES: Final[tuple[str, ...]] = ("cashapp.stations", "cashapp.pollers")
PIPELINE_MODULE: Final = "cashapp.pipeline"


class RoleDiscoveryError(Exception):
    """A module exposes a malformed role, or two modules expose the same role name."""


class UnknownRoleError(Exception):
    def __init__(self, unknown: Sequence[str], valid: Sequence[str]) -> None:
        self.unknown: tuple[str, ...] = tuple(unknown)
        self.valid: tuple[str, ...] = tuple(valid)
        super().__init__(
            f"Unknown role(s): {', '.join(self.unknown)}. Valid roles: {', '.join(self.valid)}"
        )


def _specs_of(module: ModuleType) -> list[RoleSpec]:
    found: list[RoleSpec] = []
    single: object = getattr(module, "ROLE", None)
    many: object = getattr(module, "ROLES", None)
    if single is not None:
        if not isinstance(single, RoleSpec):
            raise RoleDiscoveryError(f"{module.__name__}.ROLE is not a RoleSpec")
        found.append(single)
    if many is not None:
        if not isinstance(many, list | tuple):
            raise RoleDiscoveryError(f"{module.__name__}.ROLES is not a list of RoleSpec")
        entries: list[object] = list(many)  # pyright: ignore[reportUnknownArgumentType]
        for entry in entries:
            if not isinstance(entry, RoleSpec):
                raise RoleDiscoveryError(f"{module.__name__}.ROLES holds a non-RoleSpec value")
            found.append(entry)
    return found


def discover_roles(
    packages: Sequence[str] = ROLE_PACKAGES, *, include_pipeline: bool = True
) -> dict[str, RoleSpec]:
    """Import the direct children of each role package and collect their roles, by name."""
    modules: list[ModuleType] = []
    for package_name in packages:
        package = importlib.import_module(package_name)
        for info in pkgutil.iter_modules(package.__path__):
            modules.append(importlib.import_module(f"{package_name}.{info.name}"))
    if include_pipeline:
        modules.append(importlib.import_module(PIPELINE_MODULE))

    roles: dict[str, RoleSpec] = {}
    owner: dict[str, str] = {}
    for module in modules:
        for spec in _specs_of(module):
            if spec.name in roles:
                raise RoleDiscoveryError(
                    f"Role {spec.name!r} is defined by both {owner[spec.name]} "
                    f"and {module.__name__}"
                )
            roles[spec.name] = spec
            owner[spec.name] = module.__name__
    return dict(sorted(roles.items()))


def select_roles(available: Mapping[str, RoleSpec], spec: str) -> list[RoleSpec]:
    """``all`` selects every role; otherwise a comma-separated list of names, deduplicated."""
    if spec.strip() == "all":
        return list(available.values())
    names: list[str] = []
    for part in spec.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    unknown = [name for name in names if name not in available]
    if unknown:
        raise UnknownRoleError(unknown, sorted(available))
    return [available[name] for name in names]
