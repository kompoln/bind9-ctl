"""AXFR helpers built on dnspython."""

from __future__ import annotations

from typing import List

from .config import AppConfig
from .models import Record, ZoneFetchError, ZoneState


def fetch_zone_state(zone_name: str, config: AppConfig) -> ZoneState:
    """Return the current zone state from the authoritative server."""
    try:
        import dns.query
        import dns.tsigkeyring
        import dns.zone
        import dns.rdatatype
    except ImportError as exc:  # noqa: BLE001
        raise ZoneFetchError("dnspython is required for AXFR operations.") from exc

    keyring = dns.tsigkeyring.from_text({config.tsig.name: config.tsig.secret})

    try:
        xfr = dns.query.xfr(
            where=config.bind_server,
            zone=zone_name,
            port=config.bind_port,
            keyring=keyring,
            keyname=config.tsig.name,
            relativize=False,
            timeout=config.axfr_timeout,
        )
        zone = dns.zone.from_xfr(xfr, relativize=False)
    except Exception as exc:  # noqa: BLE001
        raise ZoneFetchError(f"AXFR failed for zone {zone_name}: {exc}") from exc

    origin = zone.origin.to_text() if zone.origin else zone_name
    records: List[Record] = []
    for name, node in zone.nodes.items():
        owner = name.to_text()
        for rdataset in node.rdatasets:
            rtype = dns.rdatatype.to_text(rdataset.rdtype)
            ttl = rdataset.ttl
            for rdata in rdataset:
                priority = None
                value_text = rdata.to_text()
                if rtype == "MX":
                    pref = getattr(rdata, "preference", None)
                    if pref is None:
                        pref = getattr(rdata, "priority", None)
                    if pref is not None:
                        priority = int(pref)
                    value_text = rdata.exchange.to_text()
                elif rtype == "SRV":
                    priority = int(getattr(rdata, "priority", 0))
                    weight = int(getattr(rdata, "weight", 0))
                    port = int(getattr(rdata, "port", 0))
                    target = rdata.target.to_text()
                    value_text = f"{weight} {port} {target}"
                records.append(
                    Record(
                        name=owner,
                        type=rtype,
                        ttl=ttl,
                        value=value_text,
                        priority=priority,
                    )
                )

    return ZoneState(origin=origin, records=records)

