"""Utilities to serialise zone state into declarative formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import Record, ZoneState


def _record_to_dict(record: Record, origin: str) -> dict[str, Any]:
    """Convert a record into a serialisable dictionary."""
    owner = record.owner_for_zone(origin)
    entry: dict[str, Any] = {
        "name": owner,
        "type": record.type,
        "ttl": record.ttl,
        "value": record.value,
    }
    if record.priority is not None:
        entry["priority"] = record.priority
    return entry


def zone_state_to_dict(zone_state: ZoneState, soa: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a dictionary describing the zone."""
    data: dict[str, Any] = {
        "zone": zone_state.origin,
        "records": [],
    }
    if zone_state.default_ttl:
        data["default_ttl"] = zone_state.default_ttl
    if soa:
        data["soa"] = soa
    records = [
        _record_to_dict(record, zone_state.origin)
        for record in sorted(
            zone_state.records,
            key=lambda rec: (rec.owner_for_zone(zone_state.origin), rec.type, rec.value),
        )
        if record.canonical_type() != "SOA"
    ]
    data["records"] = records
    return data


def zone_state_to_yaml(zone_state: ZoneState, soa: dict[str, Any] | None = None) -> str:
    """Return YAML representation of a zone state."""
    data = zone_state_to_dict(zone_state, soa=soa)
    return yaml.safe_dump(data, sort_keys=False)


def zone_state_to_json(zone_state: ZoneState, soa: dict[str, Any] | None = None) -> str:
    """Return JSON representation of a zone state."""
    data = zone_state_to_dict(zone_state, soa=soa)
    return json.dumps(data, indent=2)


def write_zone_state(path: Path, content: str) -> None:
    """Write content to the given path, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

