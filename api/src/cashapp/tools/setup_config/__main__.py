"""``python -m cashapp.tools.setup_config``: first-run entry of settings and secrets.

Sign-in settings are themselves settings, so a fresh database cannot be configured through the
authenticated Settings page. This tool writes straight to the database with the same validated,
versioned, audited writers the API uses, as the principal ``system:setup-cli``.

    status                      list required settings that are still unset
    set KEY JSON [--reason R]   set one setting; JSON is the value (a bare word is read as text)
    secret NAME                 store a secret; the value is read from a hidden prompt
    map-group GROUP ROLE        map an identity-domain group to an app role (adds to the mapping)
"""

import argparse
import asyncio
import getpass
import json
from typing import Any

from cashapp.data.engine import create_engine
from cashapp.data.uow import make_uow_factory
from cashapp.domain.principal import Permission, Principal, Role
from cashapp.secrets import SecretCipher
from cashapp.services.app_secrets import AppSecretWriter
from cashapp.services.config import ConfigWriter, lookup_key
from cashapp.services.group_roles import GroupRoleInput, GroupRoleService
from cashapp.services.runtime_settings import build_runtime_settings
from cashapp.settings import get_settings

SETUP_PRINCIPAL = Principal(
    subject="system:setup-cli",
    display_name="Setup CLI",
    email=None,
    groups=frozenset(),
    roles=frozenset(),
    permissions=frozenset({Permission.CONFIG_WRITE}),
    is_system=True,
)


def _parse(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    atp = settings.atp
    options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
    engine = create_engine(atp.url().render_as_string(hide_password=False), **options)
    try:
        uow_factory = make_uow_factory(engine)
        if args.command == "status":
            runtime = build_runtime_settings(settings, uow_factory)
            await runtime.start(strict=False)
            print("\n".join(runtime.problems) or "All required settings are set.")
            return 0
        if args.command == "set":
            key = lookup_key(args.key)
            async with uow_factory() as uow:
                from cashapp.services.config import list_config_entries

                version = (await list_config_entries(uow, only=key.name))[0].version
                await ConfigWriter().set(
                    uow, key, _parse(args.value), SETUP_PRINCIPAL, args.reason, version
                )
                await uow.commit()
            print(f"{key.name} set (version {version + 1}).")
            return 0
        if args.command == "map-group":
            async with uow_factory() as uow:
                service = GroupRoleService()
                kept = [m for m in await service.current(uow) if m.group_name != args.group]
                kept.append(GroupRoleInput(args.group, Role(args.role)))
                await service.replace(uow, kept, SETUP_PRINCIPAL, args.reason)
                await uow.commit()
            print(f"group {args.group!r} mapped to {args.role}.")
            return 0
        master = settings.secrets.master_key
        if master is None:
            print("CASHAPP_SECRETS__MASTER_KEY is not set.")
            return 1
        value = getpass.getpass(f"Value for secret {args.name!r} (hidden): ")
        async with uow_factory() as uow:
            info = await AppSecretWriter(SecretCipher(master.get_secret_value())).set(
                uow, args.name, value, SETUP_PRINCIPAL, args.reason
            )
            await uow.commit()
        print(f"secret {info.name} stored (version {info.version}).")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    one = sub.add_parser("set")
    one.add_argument("key")
    one.add_argument("value")
    one.add_argument("--reason", default="First-run setup")
    secret = sub.add_parser("secret")
    secret.add_argument("name")
    secret.add_argument("--reason", default="First-run setup")
    group = sub.add_parser("map-group")
    group.add_argument("group")
    group.add_argument("role", choices=[r.value for r in Role])
    group.add_argument("--reason", default="First-run setup")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


main()
