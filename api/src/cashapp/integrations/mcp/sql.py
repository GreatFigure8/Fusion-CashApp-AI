"""The SQL guard and the data-model renderer for `run_query`.

`run_query` takes no bind parameters, so a catalog data model is rendered by literal substitution.
Substitution only ever touches code, never comments or string literals, every value is checked
against its bind's pattern first, and the result must be exactly one SELECT/WITH statement.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Literal

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError

__all__ = ["assert_single_select", "render_data_model", "sql_hash"]

_Kind = Literal["code", "literal", "comment"]
_Segment = tuple[_Kind, str]

_BIND = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_SLICES = re.compile(r"\{\{|\}\}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _refuse(message: str) -> FusionError:
    return FusionError(ErrorCode.FUSION_FAULT, message, retryable=False)


def _scan(sql: str) -> list[_Segment]:
    """Split into code, string literals (and quoted identifiers) and comments."""
    segments: list[_Segment] = []
    code: list[str] = []
    i, n = 0, len(sql)

    def flush() -> None:
        if code:
            segments.append(("code", "".join(code)))
            code.clear()

    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            flush()
            segments.append(("comment", sql[i:end]))
            i = end
        elif ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                raise _refuse("unterminated comment in SQL")
            flush()
            segments.append(("comment", sql[i : end + 2]))
            i = end + 2
        elif ch in ("'", '"'):
            j = i + 1
            while True:
                end = sql.find(ch, j)
                if end == -1:
                    raise _refuse("unterminated string literal in SQL")
                if sql.startswith(ch * 2, end):  # doubled quote is an escaped quote
                    j = end + 2
                    continue
                break
            flush()
            segments.append(("literal", sql[i : end + 1]))
            i = end + 1
        else:
            code.append(ch)
            i += 1
    flush()
    return segments


def _code_text(segments: list[_Segment]) -> str:
    return " ".join(text for kind, text in segments if kind == "code")


def assert_single_select(sql: str) -> str:
    """Return `sql` stripped of comments and one trailing `;`, or raise `FUSION_FAULT`.

    Refuses: more than one statement (a `;` anywhere but the end), anything that does not start
    with SELECT or WITH (DML, DDL, PL/SQL), and the server's `{{slices}}` placeholders.
    """
    segments = _scan(sql)
    code = _code_text(segments)
    if _SLICES.search(code):
        raise _refuse("slice placeholders are not allowed")
    body = "".join(text for kind, text in segments if kind != "comment").strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in _code_text(_scan(body)):
        raise _refuse("only one SQL statement is allowed")
    if not body or _START.match(body) is None:
        raise _refuse("only a single SELECT or WITH query is allowed")
    return body


def render_data_model(
    sql: str, params: Mapping[str, str], binds: Mapping[str, re.Pattern[str]]
) -> str:
    """Substitute every `:P_NAME` bind with an escaped Oracle literal and guard the result.

    An unknown parameter, a missing parameter or a value that does not match its bind's pattern
    raises `FUSION_FAULT`.
    """
    unknown = sorted(set(params) - set(binds))
    if unknown:
        raise _refuse(f"unknown bind parameter(s): {', '.join(unknown)}")
    pieces: list[str] = []
    for kind, text in _scan(sql):
        if kind == "comment":
            continue
        if kind == "literal":
            pieces.append(text)
            continue

        def literal(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in binds:
                raise _refuse(f"SQL uses an undeclared bind :{name}")
            if name not in params:
                raise _refuse(f"bind :{name} has no value")
            value = params[name]
            if _CONTROL.search(value) or binds[name].fullmatch(value) is None:
                raise _refuse(f"value for :{name} is not allowed")
            return "'" + value.replace("'", "''") + "'"

        pieces.append(_BIND.sub(literal, text))
    return assert_single_select("".join(pieces))


def sql_hash(sql: str) -> str:
    """sha256 hex of the SQL text: what the call log keeps instead of the text."""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()
