"""VictoriaMetrics (Prometheus-compatible) query proxy."""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings


def instant(query: str) -> dict[str, Any]:
    url = f"{settings.victoriametrics_url}/api/v1/query"
    with httpx.Client(timeout=10) as client:
        r = client.get(url, params={"query": query})
        r.raise_for_status()
        return r.json()


def range_query(query: str, start: str, end: str, step: str = "60s") -> dict[str, Any]:
    url = f"{settings.victoriametrics_url}/api/v1/query_range"
    with httpx.Client(timeout=15) as client:
        r = client.get(url, params={"query": query, "start": start, "end": end, "step": step})
        r.raise_for_status()
        return r.json()


def scalar(query: str, default: float = 0.0) -> float:
    try:
        data = instant(query)
        result = data.get("data", {}).get("result", [])
        if result:
            return float(result[0]["value"][1])
    except Exception:
        pass
    return default


def ping() -> bool:
    try:
        with httpx.Client(timeout=5) as client:
            return client.get(f"{settings.victoriametrics_url}/health").status_code == 200
    except Exception:
        return False
