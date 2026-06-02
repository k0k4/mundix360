"""NetFlow data API (ClickHouse akvorado.flows)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..services import clickhouse

router = APIRouter(prefix="/api/flows", tags=["flows"])


@router.get("/summary")
def summary(minutes: int = Query(60, ge=1, le=1440)):
    params = {"minutes": minutes}
    try:
        total = clickhouse.query(
            "SELECT count() AS flows, sum(Bytes) AS bytes, sum(Packets) AS packets "
            "FROM flows WHERE TimeReceived > now() - INTERVAL {minutes:UInt32} MINUTE",
            params,
        )
        top_src = clickhouse.query(
            "SELECT IPv6NumToString(SrcAddr) AS src, sum(Bytes) AS bytes "
            "FROM flows WHERE TimeReceived > now() - INTERVAL {minutes:UInt32} MINUTE "
            "GROUP BY src ORDER BY bytes DESC LIMIT 10",
            params,
        )
        top_dst = clickhouse.query(
            "SELECT IPv6NumToString(DstAddr) AS dst, sum(Bytes) AS bytes "
            "FROM flows WHERE TimeReceived > now() - INTERVAL {minutes:UInt32} MINUTE "
            "GROUP BY dst ORDER BY bytes DESC LIMIT 10",
            params,
        )
        return {
            "totals": total[0] if total else {},
            "top_src": top_src,
            "top_dst": top_dst,
        }
    except Exception as e:
        return {"totals": {}, "top_src": [], "top_dst": [], "error": str(e)}
