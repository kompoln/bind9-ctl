"""Diff utilities for DNS zones."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Tuple

from .models import Record, ZoneDiff, ZoneState


def _build_value_map(state: ZoneState) -> Dict[Tuple[str, str], dict[str, Record]]:
    """Index records by owner/type/value."""
    index: Dict[Tuple[str, str], dict[str, Record]] = defaultdict(dict)
    for record in state.records:
        if record.canonical_type() == "SOA":
            continue
        key = (record.canonical_name(), record.canonical_type())
        index[key][record.canonical_value()] = record
    return index


def diff_zones(desired: ZoneState, current: ZoneState) -> ZoneDiff:
    """Produce a diff between desired and current zone states."""
    desired_map = _build_value_map(desired)
    current_map = _build_value_map(current)
    diff = ZoneDiff()
    keys = set(desired_map) | set(current_map)

    for key in sorted(keys):
        desired_values = desired_map.get(key, {})
        current_values = current_map.get(key, {})

        for value, record in desired_values.items():
            if value not in current_values:
                diff.added.append(record)
            else:
                current_record = current_values[value]
                if current_record.ttl != record.ttl:
                    diff.ttl_changed.append((current_record, record))

        for value, record in current_values.items():
            if value not in desired_values:
                diff.removed.append(record)

    return diff

