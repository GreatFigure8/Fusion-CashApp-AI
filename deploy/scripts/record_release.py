#!/usr/bin/env python3
"""Maintain deploy/releases/<env>.json, the per-environment release record.

    record_release.py record <env> --action deploy|rollback --version V --sha S --run-id R [--path DIR]
    record_release.py previous <env> [--path DIR]

`record` shifts the old `current` into `previous`, makes the new entry `current` and prepends it to
`history` (newest first, capped at 20). `previous` prints the previous version, or exits 1 when
there is none. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HISTORY_LIMIT = 20
ENVIRONMENTS = ("dev", "prod")
ACTIONS = ("deploy", "rollback")
TAG_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z._-]{1,64}$")
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "releases"


def record_file(directory: Path, environment: str) -> Path:
    return directory / f"{environment}.json"


def empty_record(environment: str) -> dict[str, Any]:
    return {
        "environment": environment,
        "current": None,
        "previous": None,
        "history": [],
    }


def load_record(directory: Path, environment: str) -> dict[str, Any]:
    path = record_file(directory, environment)
    if not path.exists():
        return empty_record(environment)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("environment") != environment:
        raise ValueError(f"{path} is not a release record for {environment}")
    return data


def write_record(directory: Path, record: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = record_file(directory, str(record["environment"]))
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def new_entry(action: str, version: str, sha: str, run_id: str) -> dict[str, str]:
    return {
        "version": version,
        "sha": sha,
        "action": action,
        "run_id": run_id,
        "deployed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def record_release(
    directory: Path, environment: str, action: str, version: str, sha: str, run_id: str
) -> dict[str, Any]:
    record = load_record(directory, environment)
    entry = new_entry(action, version, sha, run_id)
    record["previous"] = record.get("current")
    record["current"] = entry
    record["history"] = [entry, *record.get("history", [])][:HISTORY_LIMIT]
    write_record(directory, record)
    return record


def previous_version(directory: Path, environment: str) -> str | None:
    previous = load_record(directory, environment).get("previous")
    if not previous:
        return None
    return str(previous["version"])


def _check(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="record a successful deploy or rollback")
    rec.add_argument("environment", choices=ENVIRONMENTS)
    rec.add_argument("--action", choices=ACTIONS, required=True)
    rec.add_argument("--version", required=True)
    rec.add_argument("--sha", required=True)
    rec.add_argument("--run-id", required=True)
    rec.add_argument("--path", type=Path, default=DEFAULT_PATH)

    prev = sub.add_parser("previous", help="print the previous version")
    prev.add_argument("environment", choices=ENVIRONMENTS)
    prev.add_argument("--path", type=Path, default=DEFAULT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "record":
            record_release(
                args.path,
                args.environment,
                args.action,
                _check(TAG_PATTERN, args.version, "version"),
                _check(SHA_PATTERN, args.sha, "sha"),
                _check(RUN_ID_PATTERN, args.run_id, "run id"),
            )
            return 0
        version = previous_version(args.path, args.environment)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"record_release: {error}", file=sys.stderr)
        return 1
    if version is None:
        print(
            f"record_release: no previous release recorded for {args.environment}",
            file=sys.stderr,
        )
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
