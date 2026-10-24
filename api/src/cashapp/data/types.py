"""Column types shared by every model: identity PKs, JSON documents, UTC datetimes, enums, money."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any, cast

from sqlalchemy import JSON, TIMESTAMP, BigInteger, Dialect, Identity, Integer, Numeric, String
from sqlalchemy.orm import MappedColumn, mapped_column
from sqlalchemy.sql.type_api import TypeDecorator, TypeEngine, UserDefinedType

# NUMBER(18,2) as Decimal. oracledb must also run with fetch_decimals=True (see data/engine.py).
MoneyNumeric = Numeric(18, 2, asdecimal=True)


def identity_pk() -> MappedColumn[int]:
    """An identity primary key (the SQLite variant is needed for autoincrement)."""
    return mapped_column(BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, set | frozenset):
        return sorted(cast("set[Any] | frozenset[Any]", value), key=str)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def to_jsonable(value: Any) -> Any:
    """Round-trip a value through JSON so Decimal, datetime and enums become plain JSON types."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=_json_default))


class OracleJson(UserDefinedType[Any]):
    """Native ``JSON`` column on Oracle. SQLAlchemy's Oracle dialect has no JSON type of its own."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "JSON"

    def bind_processor(self, dialect: Dialect) -> Any:
        def process(value: Any) -> str | None:
            if value is None:
                return None
            return json.dumps(value, default=_json_default)

        return process

    def result_processor(self, dialect: Dialect, coltype: Any) -> Any:
        def process(value: Any) -> Any:
            # Native JSON is already decoded (dict, list, str, number), so a str here is a JSON
            # string value, not JSON text: parsing it would fail on any plain string setting.
            return value

        return process


class JsonDoc(TypeDecorator[Any]):
    """A JSON document column: native JSON on ATP, generic JSON elsewhere. None is SQL NULL."""

    impl = JSON
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(none_as_null=True)

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "oracle":
            return dialect.type_descriptor(OracleJson())
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return to_jsonable(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        return value


class UtcDateTime(TypeDecorator[datetime]):
    """TIMESTAMP WITH TIME ZONE that only accepts aware datetimes and always returns UTC."""

    impl = TIMESTAMP
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(TIMESTAMP(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime bound to a UTC column; use an aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # SQLite drops the zone; everything we store is UTC.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StrEnumType(TypeDecorator[Any]):
    """A StrEnum stored as VARCHAR2 with no CHECK constraint, validated on bind and on load."""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[StrEnum], length: int = 40) -> None:
        super().__init__(length)
        self.enum_cls = enum_cls
        self.length = length

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return self.enum_cls(value).value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return self.enum_cls(value)
