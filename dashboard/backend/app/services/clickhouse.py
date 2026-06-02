"""ClickHouse access for SIEM alerts and NetFlow data."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import clickhouse_connect

from ..config import settings


@lru_cache(maxsize=1)
def _client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_db,
    )


def query(sql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    client = _client()
    result = client.query(sql, parameters=parameters or {})
    cols = result.column_names
    return [dict(zip(cols, row)) for row in result.result_rows]


def ping() -> bool:
    try:
        _client().query("SELECT 1")
        return True
    except Exception:
        return False
