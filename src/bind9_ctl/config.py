"""Environment-driven configuration loader."""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class TsigKey:
    """Holds TSIG credentials used for AXFR."""

    name: str
    algorithm: str
    secret: str


@dataclass(frozen=True)
class AppConfig:
    """Application-wide configuration values."""

    bind_server: str
    bind_port: int
    bind_view: str
    tsig: TsigKey
    zone_output_dir: Path
    templates_dir: Path
    named_checkzone_bin: str
    rndc_bin: str
    rndc_server: str
    serial_strategy: str
    default_record_ttl: int
    git_auto_commit: bool
    git_commit_template: str
    log_level: str
    axfr_timeout: float
    apply_strategy: str


KEYFILE_PATTERN = re.compile(
    r'key\s+"(?P<name>[^"]+)"\s*\{'
    r"(?P<body>.*?)"
    r"\}",
    re.IGNORECASE | re.DOTALL,
)
ALGORITHM_PATTERN = re.compile(
    r"algorithm\s+(?P<algorithm>[\w-]+)\s*;",
    re.IGNORECASE,
)
SECRET_PATTERN = re.compile(
    r'secret\s+"(?P<secret>[^"]+)"\s*;',
    re.IGNORECASE,
)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    """Return a boolean parsed from a string."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_keyfile(encoded: str, overrides: dict[str, str | None]) -> TsigKey:
    """Decode and parse a base64-encoded BIND keyfile."""
    if not encoded:
        raise ValueError("BIND_TSIG_KEYFILE_B64 is required.")
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Failed to decode TSIG key file base64 payload.") from exc

    match = KEYFILE_PATTERN.search(decoded)
    if not match:
        raise ValueError("TSIG key file does not match expected format.")
    body = match.group("body")
    name = overrides.get("name") or match.group("name")
    algo_match = ALGORITHM_PATTERN.search(body)
    secret_match = SECRET_PATTERN.search(body)
    algorithm = overrides.get("algorithm") or (algo_match.group("algorithm") if algo_match else None)
    secret = overrides.get("secret") or (secret_match.group("secret") if secret_match else None)

    if not all([name, algorithm, secret]):
        raise ValueError("TSIG key file missing name, algorithm, or secret.")

    return TsigKey(name=name, algorithm=algorithm, secret=secret)


def load_config() -> AppConfig:
    """Load configuration values from the environment (and .env)."""
    load_dotenv()
    bind_server = os.getenv("BIND_SERVER", "127.0.0.1")
    bind_port = int(os.getenv("BIND_PORT", "53"))
    bind_view = os.getenv("BIND_VIEW", "default")
    serialized_key = os.getenv("BIND_TSIG_KEYFILE_B64", "")
    tsig = _parse_keyfile(
        serialized_key,
        overrides={
            "name": os.getenv("BIND_TSIG_NAME"),
            "algorithm": os.getenv("BIND_TSIG_ALGORITHM"),
            "secret": os.getenv("BIND_TSIG_SECRET"),
        },
    )
    zone_output_dir = Path(os.getenv("ZONE_OUTPUT_DIR", "zones")).resolve()
    zone_output_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = Path(os.getenv("TEMPLATES_DIR", "templates")).resolve()
    templates_dir.mkdir(parents=True, exist_ok=True)

    apply_strategy = os.getenv("APPLY_STRATEGY", "dynamic").lower()
    if apply_strategy not in {"dynamic", "zone"}:
        raise ValueError("APPLY_STRATEGY must be either 'dynamic' or 'zone'.")

    config = AppConfig(
        bind_server=bind_server,
        bind_port=bind_port,
        bind_view=bind_view,
        tsig=tsig,
        zone_output_dir=zone_output_dir,
        templates_dir=templates_dir,
        named_checkzone_bin=os.getenv("NAMED_CHECKZONE_BIN", "named-checkzone"),
        rndc_bin=os.getenv("RNDC_BIN", "rndc"),
        rndc_server=os.getenv("RNDC_SERVER", bind_server),
        serial_strategy=os.getenv("SERIAL_STRATEGY", "date"),
        default_record_ttl=int(os.getenv("DEFAULT_RECORD_TTL", "3600")),
        git_auto_commit=_parse_bool(os.getenv("GIT_AUTO_COMMIT", "false")),
        git_commit_template=os.getenv("GIT_COMMIT_TEMPLATE", "feat(zone): update {zone}"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        axfr_timeout=float(os.getenv("AXFR_TIMEOUT", "10")),
        apply_strategy=apply_strategy,
    )
    return config

