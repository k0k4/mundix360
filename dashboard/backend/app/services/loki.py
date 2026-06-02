"""Loki log query proxy."""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import settings


def query_range(
    logql: str,
    limit: int = 100,
    hours: int = 1,
    direction: str = "backward",
) -> list[dict[str, Any]]:
    end = int(time.time() * 1e9)
    start = end - int(hours * 3600 * 1e9)
    url = f"{settings.loki_url}/loki/api/v1/query_range"
    params = {
        "query": logql,
        "limit": limit,
        "start": start,
        "end": end,
        "direction": direction,
    }
    with httpx.Client(timeout=15) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    entries: list[dict[str, Any]] = []
    for stream in data.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for ts, line in stream.get("values", []):
            entries.append({
                "timestamp": int(ts),
                "labels": labels,
                "line": line,
            })
    entries.sort(key=lambda e: e["timestamp"], reverse=(direction == "backward"))
    return entries[:limit]


def labels() -> list[str]:
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{settings.loki_url}/loki/api/v1/labels")
            r.raise_for_status()
            return r.json().get("data", [])
    except Exception:
        return []


def ping() -> bool:
    try:
        with httpx.Client(timeout=5) as client:
            return client.get(f"{settings.loki_url}/ready").status_code == 200
    except Exception:
        return False
