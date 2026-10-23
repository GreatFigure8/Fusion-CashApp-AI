"""Declarative base with an upper-snake, Oracle-safe naming convention."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "pk": "PK_%(table_name)s",
    "fk": "FK_%(table_name)s_%(column_0_name)s",
    "uq": "UQ_%(table_name)s_%(column_0_name)s",
    "ix": "IX_%(table_name)s_%(column_0_name)s",
    "ck": "CK_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
