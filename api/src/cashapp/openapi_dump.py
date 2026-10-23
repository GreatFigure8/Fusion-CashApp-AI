"""Dump the API's OpenAPI document, the contract `web/` is typed from.

Pure and offline: the app is built from placeholder settings, so no environment variable, `.env`
file, Vault secret, database connection or network call is involved.

    uv run python -m cashapp.openapi_dump --out ../web/lib/api/openapi.json
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from cashapp.main import create_app
from cashapp.settings_placeholders import placeholder_settings

GENERATED_MARKER: Final = (
    "cashapp.openapi_dump. GENERATED, do not edit. "
    "On merge conflict: regenerate (npm run api:sync), never hand-merge."
)


def openapi_document() -> dict[str, Any]:
    document = dict(create_app(settings=placeholder_settings()).openapi())
    document["x-generated"] = GENERATED_MARKER
    return document


def render_openapi(doc: Mapping[str, Any]) -> str:
    """Sorted keys, two-space indent, LF newlines and one trailing newline: byte-stable."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cashapp.openapi_dump", description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    args = parser.parse_args(argv)

    payload = render_openapi(openapi_document()).encode("utf-8")
    if args.out is None:
        # Bytes, never text mode: Windows text-mode stdout would turn LF into CRLF.
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
