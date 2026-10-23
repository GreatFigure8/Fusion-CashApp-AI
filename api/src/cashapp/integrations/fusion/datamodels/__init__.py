"""The catalog of SQL data models run through the MCP server's `run_query`.

These replace the BI Publisher catalog reports: no report has to be created in each tenant. The
paths are the old report paths, kept as the stable names callers use. Each model declares its
binds and a pattern every value must match before it is substituted into the SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources

__all__ = [
    "CATALOG",
    "RECEIPT_SIGNALS_PATH",
    "RELATIONSHIPS_PATH",
    "DataModel",
    "load_sql",
]

_PACKAGE = "cashapp.integrations.fusion.datamodels"
RELATIONSHIPS_PATH = "/Custom/CashApp/CashAppRelationships.xdo"
RECEIPT_SIGNALS_PATH = "/Custom/CashApp/CashAppReceiptSignals.xdo"

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ACCOUNT_LIST = re.compile(r"[\w\-./# ,]{1,4000}")


@dataclass(frozen=True, slots=True)
class DataModel:
    path: str
    sql_file: str
    binds: dict[str, re.Pattern[str]] = field(default_factory=lambda: dict[str, re.Pattern[str]]())


CATALOG: dict[str, DataModel] = {
    RELATIONSHIPS_PATH: DataModel(
        RELATIONSHIPS_PATH, "relationships.sql", {"P_ACCOUNT_NUMBERS": _ACCOUNT_LIST}
    ),
    RECEIPT_SIGNALS_PATH: DataModel(
        RECEIPT_SIGNALS_PATH,
        "receipt_signals.sql",
        {"P_DATE_FROM": _DATE, "P_DATE_TO": _DATE},
    ),
}


def load_sql(path: str) -> str:
    """The packaged SQL text of a catalog data model."""
    model = CATALOG[path]
    return resources.files(_PACKAGE).joinpath(model.sql_file).read_text(encoding="utf-8")
