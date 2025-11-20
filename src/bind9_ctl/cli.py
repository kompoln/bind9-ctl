"""Command-line entry point for bind9-ctl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import AppConfig, load_config
from .controller import PlanResult, ZoneController, configure_logging
from .models import Bind9CtlError
from .exporter import zone_state_to_json, zone_state_to_yaml, write_zone_state


def _build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description="Manage BIND9 zones declaratively.")
    parser.add_argument("--log-level", help="Override log level (default from config).")

    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="Show diff between desired and current state.")
    _register_common_arguments(plan_parser)
    plan_parser.add_argument("--json", help="Optional path to write diff JSON.")

    apply_parser = subparsers.add_parser("apply", help="Apply changes to the zone.")
    _register_common_arguments(apply_parser)
    apply_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")

    pull_parser = subparsers.add_parser("pull", help="Fetch current zone state from BIND.")
    pull_parser.add_argument("--zone", required=True, help="Zone name to pull.")
    pull_parser.add_argument("--output", help="Path to write the exported state (default stdout).")
    pull_parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Serialization format for the exported state.",
    )

    return parser


def _register_common_arguments(subparser: argparse.ArgumentParser) -> None:
    """Register arguments shared by plan/apply."""
    subparser.add_argument("--desired", required=True, help="Path to the desired-state YAML file.")
    subparser.add_argument("--zone", help="Zone name (overrides YAML).")
    subparser.add_argument(
        "-e",
        "--var",
        action="append",
        help="Template variable in KEY=VALUE form. Can be repeated.",
    )


def _parse_template_vars(values: list[str] | None) -> dict[str, str]:
    """Convert KEY=VALUE pairs into a dict."""
    result: dict[str, str] = {}
    if not values:
        return result
    for value in values:
        if "=" not in value:
            raise Bind9CtlError(f"Invalid template var '{value}', expected KEY=VALUE.")
        key, val = value.split("=", 1)
        result[key] = val
    return result


def _serialize_record(record) -> dict[str, str | int | None]:
    """Convert a record into JSON-serialisable data."""
    return {
        "name": record.name,
        "type": record.type,
        "ttl": record.ttl,
        "value": record.value,
        "priority": record.priority,
    }


def _emit_diff(plan: PlanResult, json_path: str | None = None) -> None:
    """Print a human-friendly diff, optionally writing JSON."""
    diff = plan.diff
    print(f"Zone: {plan.desired.origin}")
    print(f"Added: {len(diff.added)}")
    for record in diff.added:
        print(f" + {record.type} {record.name} -> {record.value} (ttl {record.ttl})")
    print(f"Removed: {len(diff.removed)}")
    for record in diff.removed:
        print(f" - {record.type} {record.name} -> {record.value}")
    print(f"TTL changes: {len(diff.ttl_changed)}")
    for before, after in diff.ttl_changed:
        print(
            f" ~ {before.type} {before.name} {before.ttl} -> {after.ttl} value {before.value}",
        )
    if json_path:
        payload = {
            "zone": plan.desired.origin,
            "added": [_serialize_record(r) for r in diff.added],
            "removed": [_serialize_record(r) for r in diff.removed],
            "ttl_changed": [
                {"before": _serialize_record(b), "after": _serialize_record(a)} for b, a in diff.ttl_changed
            ],
            "serial": plan.soa.serial,
        }
        Path(json_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote diff JSON to {json_path}")


def _run_plan(controller: ZoneController, args: argparse.Namespace) -> PlanResult:
    """Execute the plan command."""
    desired_path = Path(args.desired)
    template_vars = _parse_template_vars(args.var)
    plan_result = controller.plan(desired_path, zone=args.zone, template_vars=template_vars)
    json_path = getattr(args, "json", None)
    _emit_diff(plan_result, json_path)
    if not plan_result.diff.has_changes():
        print("No changes detected.")
    return plan_result


def _run_apply(controller: ZoneController, args: argparse.Namespace) -> None:
    """Execute the apply command."""
    plan_result = _run_plan(controller, args)
    controller.apply(plan_result, assume_yes=args.yes)


def _run_pull(controller: ZoneController, args: argparse.Namespace) -> None:
    """Execute the pull command."""
    zone_state, soa = controller.pull_state(args.zone)
    if args.format == "json":
        content = zone_state_to_json(zone_state, soa=soa)
    else:
        content = zone_state_to_yaml(zone_state, soa=soa)
    if args.output:
        write_zone_state(Path(args.output), content)
        print(f"Wrote zone state to {args.output}")
    else:
        print(content)


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    try:
        config = load_config()
        configure_logging(args.log_level or config.log_level)
        controller = ZoneController(config)
        if args.command == "plan":
            _run_plan(controller, args)
        elif args.command == "apply":
            _run_apply(controller, args)
        elif args.command == "pull":
            _run_pull(controller, args)
        else:  # pragma: no cover - argparse ensures we never reach here
            parser.error(f"Unsupported command {args.command}")
    except Bind9CtlError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()

