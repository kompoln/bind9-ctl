"""Core data models used by bind9-ctl."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence


def _ensure_absolute(name: str) -> str:
    """Return a fully qualified name with a trailing dot."""
    stripped = name.strip()
    if not stripped:
        return "."
    if stripped == "@":
        return "."
    return stripped if stripped.endswith(".") else f"{stripped}."


@dataclass(frozen=True)
class Record:
    """Canonical representation of a DNS resource record."""

    name: str
    type: str
    ttl: int
    value: str
    priority: int | None = None

    def canonical_name(self) -> str:
        """Return the canonical fully qualified owner name."""
        return _ensure_absolute(self.name).lower()

    def canonical_type(self) -> str:
        """Return the canonical RR type."""
        return self.type.upper()

    def canonical_value(self) -> str:
        """Return a canonicalised RR value for comparisons."""
        value = self.value.strip()
        canonical_type = self.canonical_type()
        if canonical_type in {"CNAME", "NS", "PTR"}:
            value = _ensure_absolute(value).lower()
        elif canonical_type == "MX":
            value = _ensure_absolute(value).lower()
        elif canonical_type == "SRV":
            parts = value.split()
            if parts:
                parts[-1] = _ensure_absolute(parts[-1]).lower()
                value = " ".join(parts)
        if self.priority is not None:
            return f"{self.priority} {value}"
        return value

    def owner_for_zone(self, origin: str) -> str:
        """Return the owner label relative to the provided origin."""
        absolute_origin = _ensure_absolute(origin).lower()
        absolute_name = self.canonical_name()
        if absolute_name == absolute_origin:
            return "@"
        if absolute_name.endswith(absolute_origin):
            relative = absolute_name[: -len(absolute_origin)]
            if relative.endswith("."):
                relative = relative[:-1]
            return relative or "@"
        return absolute_name

    def key(self) -> tuple[str, str, str]:
        """Return a tuple key used for equality checks."""
        return (self.canonical_name(), self.canonical_type(), self.canonical_value())


@dataclass
class ZoneState:
    """Represents the full state of a DNS zone."""

    origin: str
    records: list[Record] = field(default_factory=list)
    default_ttl: int | None = None

    def iter_records(self) -> Iterator[Record]:
        """Yield all records in the zone."""
        yield from self.records

    def find_soa(self) -> Record | None:
        """Return the SOA record if present."""
        for record in self.records:
            if record.canonical_type() == "SOA":
                return record
        return None

    def index(self) -> dict[tuple[str, str, str], Record]:
        """Return a dictionary keyed by record identity."""
        return {record.key(): record for record in self.records}


@dataclass(frozen=True)
class SOAConfig:
    """Configuration required to render an SOA record."""

    primary_ns: str
    admin_email: str
    serial: int
    refresh: int
    retry: int
    expire: int
    minimum: int


@dataclass(frozen=True)
class RecordDelta:
    """Represents a single record-level change."""

    before: Record | None
    after: Record | None
    reason: str


@dataclass
class ZoneDiff:
    """High-level diff between two zone states."""

    added: list[Record] = field(default_factory=list)
    removed: list[Record] = field(default_factory=list)
    ttl_changed: list[tuple[Record, Record]] = field(default_factory=list)

    def has_changes(self) -> bool:
        """Return True when the diff contains meaningful changes."""
        return bool(self.added or self.removed or self.ttl_changed)

    def total(self) -> int:
        """Return the total number of change entries."""
        return len(self.added) + len(self.removed) + len(self.ttl_changed)


class Bind9CtlError(Exception):
    """Base exception for bind9-ctl."""


class ZoneFetchError(Bind9CtlError):
    """Raised when AXFR download fails."""


class ValidationError(Bind9CtlError):
    """Raised when desired-state YAML is invalid."""

