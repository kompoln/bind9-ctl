"""Render zone files via Jinja2 templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import AppConfig
from .models import Record, SOAConfig, ZoneState


@dataclass
class RenderResult:
    """Holds rendered zone text and destination path."""

    text: str
    output_path: Path


def _record_to_template_data(record: Record, origin: str) -> dict[str, str | int]:
    """Convert a record into template-friendly data."""
    owner = record.owner_for_zone(origin)
    value = record.value
    if record.priority is not None and record.canonical_type() in {"MX", "SRV"}:
        value = f"{record.priority} {value}"
    return {
        "owner": owner,
        "ttl": record.ttl,
        "type": record.type,
        "value": value,
    }


def render_zone(
    config: AppConfig,
    zone_state: ZoneState,
    soa: SOAConfig,
    template_name: str = "zone.j2",
) -> RenderResult:
    """Render a zone file using the configured template directory."""
    env = Environment(
        loader=FileSystemLoader(str(config.templates_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_name)
    records = [
        _record_to_template_data(record, zone_state.origin)
        for record in zone_state.records
        if record.canonical_type() != "SOA"
    ]
    default_ttl = zone_state.default_ttl or config.default_record_ttl
    text = template.render(origin=zone_state.origin, default_ttl=default_ttl, soa=soa.__dict__, records=records)
    safe_origin = zone_state.origin.rstrip(".")
    output_path = config.zone_output_dir / f"{safe_origin}.zone"
    return RenderResult(text=text.strip() + "\n", output_path=output_path)

