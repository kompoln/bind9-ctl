"""Load and validate desired-state YAML files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, field_validator

from .config import AppConfig
from .models import Record, ValidationError, ZoneState

FQDN_TYPES = {"CNAME", "MX", "NS", "PTR"}


class RecordSpec(BaseModel):
    """Schema for a desired DNS record."""

    name: str
    type: str
    value: str
    ttl: int | None = None
    priority: int | None = Field(default=None, description="Priority for MX/SRV records")

    @field_validator("type")
    @classmethod
    def _uppercase_type(cls, value: str) -> str:
        """Normalise RR type to uppercase."""
        return value.upper()


class SOASpec(BaseModel):
    """Schema describing SOA overrides."""

    primary_ns: str | None = None
    admin_email: str | None = None
    serial: int | None = None
    refresh: int | None = None
    retry: int | None = None
    expire: int | None = None
    minimum: int | None = None


class ZoneSpec(BaseModel):
    """Schema for the YAML document."""

    zone: str | None = None
    default_ttl: int | None = Field(default=None, ge=0)
    records: list[RecordSpec]
    soa: SOASpec | None = None
    ignore: list[str] = Field(default_factory=list)


@dataclass
class DesiredZone:
    """Desired zone material produced from YAML."""

    state: ZoneState
    soa_overrides: SOASpec | None
    ignore: list[str]


def _ensure_absolute(name: str) -> str:
    """Return an absolute DNS name."""
    stripped = name.strip()
    if stripped in {"", "@", "."}:
        return "."
    return stripped if stripped.endswith(".") else f"{stripped}."


def _normalise_owner(name: str, origin: str) -> str:
    """Normalise record owners relative to origin."""
    if name in {"", "@", "."}:
        return origin
    if name.endswith("."):
        return name
    trimmed_origin = origin.rstrip(".")
    return f"{name}.{trimmed_origin}."


def _normalise_value(rtype: str, value: str, origin: str) -> str:
    """Return a canonical RR value."""
    cleaned = value.strip()
    if rtype in FQDN_TYPES:
        if cleaned.endswith("."):
            return cleaned
        return _normalise_owner(cleaned, origin)
    if rtype == "SRV":
        parts = cleaned.split()
        if len(parts) < 3:
            raise ValidationError("SRV record value must include weight, port, and target.")
        target = parts[-1]
        parts[-1] = _ensure_absolute(target)
        return " ".join(parts)
    return cleaned


def _render_yaml(path: Path, extra_context: dict[str, Any] | None = None) -> str:
    """Render a YAML file through Jinja2."""
    env = Environment(
        loader=FileSystemLoader(str(path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(path.name)
    context = {"env": os.environ}
    if extra_context:
        context.update(extra_context)
    return template.render(**context)


def load_desired_zone(
    path: Path,
    config: AppConfig,
    zone_hint: str | None = None,
    template_vars: dict[str, Any] | None = None,
) -> DesiredZone:
    """Load a desired zone YAML and turn it into zone state."""
    rendered = _render_yaml(path, template_vars)
    try:
        data = yaml.safe_load(rendered) or {}
    except yaml.YAMLError as exc:  # noqa: BLE001
        raise ValidationError(f"Failed to parse YAML: {exc}") from exc

    try:
        spec = ZoneSpec(**data)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"YAML validation error: {exc}") from exc

    origin = _ensure_absolute(spec.zone or zone_hint or "")
    if origin == ".":
        raise ValidationError("Zone name is required via YAML 'zone' or --zone flag.")

    default_ttl = spec.default_ttl or config.default_record_ttl
    records: list[Record] = []
    for record in spec.records:
        ttl = record.ttl or default_ttl
        owner = _normalise_owner(record.name, origin)
        value = _normalise_value(record.type, record.value, origin)
        records.append(
            Record(
                name=owner,
                type=record.type,
                ttl=ttl,
                value=value,
                priority=record.priority,
            )
        )

    state = ZoneState(origin=origin, records=records, default_ttl=default_ttl)
    return DesiredZone(state=state, soa_overrides=spec.soa, ignore=spec.ignore)

