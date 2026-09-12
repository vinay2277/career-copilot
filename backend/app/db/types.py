"""Custom SQLAlchemy column types."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class EnumStr(TypeDecorator):
    """Stores a `StrEnum` as its value and loads it back as the enum member.

    A plain `mapped_column(String(20))` annotated `Mapped[SomeStrEnum]` looks
    like it works — a `StrEnum` *is* a `str`, so writes succeed — but reads come
    back as bare strings. Everything using `==` keeps passing while everything
    using `is` silently starts failing, which is a miserable bug to find.

    SQLAlchemy's built-in `Enum` would also work, but it persists member *names*
    by default (`APPLIED`), and the analytics layer, the API schemas, and the
    frontend all speak values (`applied`). This keeps one spelling everywhere.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[StrEnum], length: int = 32, **kwargs: Any):
        self.enum_class = enum_class
        super().__init__(length=length, **kwargs)

    def process_bind_param(
        self, value: StrEnum | str | None, dialect: Any
    ) -> str | None:
        if value is None:
            return None
        # Accept a raw string so a route can pass through an already-coerced
        # value without round-tripping it via the enum first.
        return self.enum_class(value).value

    def process_result_value(
        self, value: str | None, dialect: Any
    ) -> StrEnum | None:
        if value is None:
            return None
        return self.enum_class(value)
