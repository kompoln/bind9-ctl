"""High-level orchestration for bind9-ctl."""

from __future__ import annotations

import fnmatch
import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .axfr import fetch_zone_state
from .config import AppConfig
from .diffing import diff_zones
from .gitops import auto_commit, is_git_repo
from .models import Bind9CtlError, Record, SOAConfig, ZoneDiff, ZoneState
from .renderer import RenderResult, render_zone
from .yaml_loader import DesiredZone, load_desired_zone

LOG = logging.getLogger("bind9_ctl")


@dataclass
class PlanResult:
    """Holds everything needed to apply a change."""

    desired: ZoneState
    current: ZoneState
    diff: ZoneDiff
    soa: SOAConfig
    render: RenderResult


class ZoneController:
    """Coordinates plan/apply operations."""

    def __init__(self, config: AppConfig):
        """Store configuration for subsequent runs."""
        self.config = config

    def plan(
        self,
        desired_path: Path,
        zone: str | None = None,
        template_vars: dict[str, Any] | None = None,
    ) -> PlanResult:
        """Compute the diff between desired YAML and the current zone."""
        desired_zone = load_desired_zone(desired_path, self.config, zone_hint=zone, template_vars=template_vars)
        current_state = fetch_zone_state(desired_zone.state.origin, self.config)
        filtered_current = _filter_records(current_state, desired_zone.ignore)
        diff = diff_zones(desired_zone.state, filtered_current)
        soa = _build_soa_config(self.config, desired_zone, current_state)
        render = render_zone(self.config, desired_zone.state, soa)
        return PlanResult(
            desired=desired_zone.state,
            current=current_state,
            diff=diff,
            soa=soa,
            render=render,
        )

    def pull_state(self, zone: str) -> tuple[ZoneState, dict[str, Any] | None]:
        """Fetch the current zone state and parsed SOA."""
        zone_state = fetch_zone_state(zone, self.config)
        soa_record = zone_state.find_soa()
        soa = _parse_soa_record(soa_record) if soa_record else None
        return zone_state, soa

    def apply(self, plan_result: PlanResult, assume_yes: bool = False) -> None:
        """Write the zone file, validate it, and reload BIND."""
        if not plan_result.diff.has_changes():
            LOG.info("No changes detected; nothing to apply.")
            return
        if not assume_yes and not _confirm(plan_result.desired.origin):
            LOG.info("Apply aborted by user.")
            return
        _write_zone_file(plan_result.render)
        _maybe_run_named_checkzone(self.config, plan_result.desired.origin, plan_result.render.output_path)
        if self.config.apply_strategy == "zone":
            _reload_zone(self.config, plan_result.desired.origin)
        else:
            _apply_dynamic_updates(self.config, plan_result)
        if self.config.git_auto_commit and is_git_repo():
            message = self.config.git_commit_template.format(zone=plan_result.desired.origin.rstrip("."))
            auto_commit([plan_result.render.output_path], message)
        LOG.info("Apply complete for %s", plan_result.desired.origin)


def configure_logging(level: str) -> None:
    """Configure logging output."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _write_zone_file(render_result: RenderResult) -> None:
    """Persist the rendered zone file."""
    render_result.output_path.parent.mkdir(parents=True, exist_ok=True)
    render_result.output_path.write_text(render_result.text, encoding="utf-8")
    LOG.info("Wrote zone file to %s", render_result.output_path)


def _confirm(zone: str) -> bool:
    """Prompt the operator to confirm apply."""
    prompt = f"Apply changes to {zone}? [y/N]: "
    response = input(prompt).strip().lower()  # noqa: S322
    return response in {"y", "yes"}


def _maybe_run_named_checkzone(config: AppConfig, zone: str, zone_file: Path) -> None:
    """Invoke named-checkzone for validation if configured."""
    if not config.named_checkzone_bin:
        LOG.debug("Skipping named-checkzone validation (no binary configured).")
        return
    cmd = [config.named_checkzone_bin, zone, str(zone_file)]
    LOG.info("Running %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _reload_zone(config: AppConfig, zone: str) -> None:
    """Reload the zone via rndc."""
    if not config.rndc_bin:
        raise Bind9CtlError("RNDC binary not configured; cannot reload zone in 'zone' apply_strategy.")
    cmd = [config.rndc_bin, "-s", config.rndc_server, "reload", zone, config.bind_view]
    LOG.info("Running %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _apply_dynamic_updates(config: AppConfig, plan_result: PlanResult) -> None:
    """Send dynamic DNS updates using TSIG."""
    try:
        import dns.query
        import dns.rcode
        import dns.tsigkeyring
        import dns.update
    except ImportError as exc:  # noqa: BLE001
        raise Bind9CtlError("dnspython is required for dynamic updates.") from exc

    additions = plan_result.diff.added
    removals = plan_result.diff.removed
    ttl_changes = plan_result.diff.ttl_changed
    if not (additions or removals or ttl_changes):
        LOG.info("No record changes to send via dynamic update.")
        return

    keyring = dns.tsigkeyring.from_text({config.tsig.name: config.tsig.secret})
    update = dns.update.Update(
        plan_result.desired.origin,
        keyring=keyring,
        keyname=config.tsig.name,
        keyalgorithm=config.tsig.algorithm,
    )

    for record in removals:
        update.delete(record.name, record.type, record.value)

    for before, _ in ttl_changes:
        update.delete(before.name, before.type, before.value)

    for record in additions:
        update.add(record.name, record.ttl, record.type, record.value)

    for _, record in ttl_changes:
        update.add(record.name, record.ttl, record.type, record.value)

    LOG.info(
        "Sending dynamic update: %s additions, %s removals, %s ttl changes",
        len(additions),
        len(removals),
        len(ttl_changes),
    )
    response = dns.query.tcp(update, config.bind_server, port=config.bind_port, timeout=config.axfr_timeout)
    rcode = response.rcode()
    if rcode != dns.rcode.NOERROR:
        raise Bind9CtlError(f"Dynamic update failed with rcode {dns.rcode.to_text(rcode)}")


def _parse_soa_record(record: Record) -> dict[str, str]:
    """Parse an SOA record into a dict."""
    parts = record.value.split()
    if len(parts) < 7:
        raise Bind9CtlError("SOA record is malformed.")
    return {
        "primary_ns": parts[0],
        "admin_email": parts[1],
        "serial": int(parts[2]),
        "refresh": int(parts[3]),
        "retry": int(parts[4]),
        "expire": int(parts[5]),
        "minimum": int(parts[6]),
    }


def _suggest_serial(strategy: str, current_serial: int | None) -> int:
    """Return a serial number that satisfies the chosen strategy."""
    if strategy == "epoch":
        candidate = int(time.time())
    else:
        candidate = int(datetime.now(tz=timezone.utc).strftime("%Y%m%d00"))
    if current_serial is None:
        return candidate
    while candidate <= current_serial:
        candidate += 1
    return candidate


def _build_soa_config(config: AppConfig, desired: DesiredZone, current: ZoneState) -> SOAConfig:
    """Combine existing SOA data with overrides and serial strategy."""
    base_record = current.find_soa()
    base = _parse_soa_record(base_record) if base_record else {}
    overrides = desired.soa_overrides.dict() if desired.soa_overrides else {}
    primary_ns = overrides.get("primary_ns") or base.get("primary_ns") or f"ns.{desired.state.origin}"
    admin_email = overrides.get("admin_email") or base.get("admin_email") or f"hostmaster.{desired.state.origin}"
    serial_override = overrides.get("serial")
    current_serial = base.get("serial")
    serial = serial_override or _suggest_serial(config.serial_strategy, current_serial)

    return SOAConfig(
        primary_ns=primary_ns,
        admin_email=admin_email,
        serial=serial,
        refresh=int(overrides.get("refresh") or base.get("refresh") or 3600),
        retry=int(overrides.get("retry") or base.get("retry") or 600),
        expire=int(overrides.get("expire") or base.get("expire") or 604800),
        minimum=int(overrides.get("minimum") or base.get("minimum") or 86400),
    )


def _filter_records(state: ZoneState, ignore_patterns: list[str]) -> ZoneState:
    """Filter records that match ignore patterns."""
    if not ignore_patterns:
        return state
    filtered = [
        record
        for record in state.records
        if record.canonical_type() == "SOA" or not _matches_pattern(record.name, ignore_patterns)
    ]
    return ZoneState(origin=state.origin, records=filtered, default_ttl=state.default_ttl)


def _matches_pattern(name: str, patterns: list[str]) -> bool:
    """Return True if name matches any ignore pattern."""
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)

