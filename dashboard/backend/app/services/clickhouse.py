"""ClickHouse access for SIEM alerts and NetFlow data."""
from __future__ import annotations

import threading
from typing import Any

import clickhouse_connect

from ..config import settings

# clickhouse_connect clients are NOT safe to share across threads — a session may
# only run one query at a time. FastAPI executes sync endpoints in a threadpool,
# so a single cached client raises "Attempt to execute concurrent queries within
# the same session" under load. Keep one client per thread instead.
_local = threading.local()


def _client():
    client = getattr(_local, "client", None)
    if client is None:
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_db,
        )
        _local.client = client
    return client


def query(sql: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    client = _client()
    result = client.query(sql, parameters=parameters or {})
    cols = result.column_names
    return [dict(zip(cols, row)) for row in result.result_rows]


def command(sql: str, parameters: dict[str, Any] | None = None) -> None:
    _client().command(sql, parameters=parameters or {})


def ping() -> bool:
    try:
        _client().query("SELECT 1")
        return True
    except Exception:
        return False
