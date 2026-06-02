"""Overview / dashboard summary endpoint."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ..services import clickhouse, firewall, loki, metrics, system

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("")
def overview():
    now = datetime.now(timezone.utc)

    # SIEM counters
    alerts_24h = 0
    alerts_high = 0
    top_sources: list[dict] = []
    try:
        rows = clickhouse.query(
            "SELECT count() AS c FROM siem_alerts WHERE timestamp > now() - INTERVAL 24 HOUR"
        )
        alerts_24h = int(rows[0]["c"]) if rows else 0
        rows = clickhouse.query(
            "SELECT count() AS c FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL 24 HOUR AND severity >= 3"
        )
        alerts_high = int(rows[0]["c"]) if rows else 0
        top_sources = clickhouse.query(
            "SELECT source, count() AS count FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL 24 HOUR "
            "GROUP BY source ORDER BY count DESC LIMIT 5"
        )
    except Exception:
        pass

    blocked = []
    try:
        blocked = firewall.list_blocked()
    except Exception:
        pass

    return {
        "timestamp": now.isoformat(),
        "siem": {
            "alerts_24h": alerts_24h,
            "alerts_high_24h": alerts_high,
            "top_sources": top_sources,
        },
        "firewall": {"blocked_ips": len(blocked)},
        "host": system.host_metrics(),
        "services": system.all_services(),
        "health": {
            "clickhouse": clickhouse.ping(),
            "victoriametrics": metrics.ping(),
            "loki": loki.ping(),
        },
    }
