"""Firewall management via nftables.

Reads the live ruleset using `nft -j` (JSON output) and manages:
  - the dynamic IP blocklist (table ip mundix_blocklist, set blocked_ips)
  - simple port/service accept rules (table inet filter, chain input)
All mutating operations go through the allowlisted shell runner.
"""
from __future__ import annotations

import ipaddress
import json
from typing import Any

from ..config import settings
from . import shell

BLOCK_TABLE = "mundix_blocklist"
BLOCK_SET = "blocked_ips"


def _nft_json(*args: str) -> dict[str, Any]:
    res = shell.run(["nft", "-j", *args])
    if not res.ok or not res.stdout.strip():
        return {"nftables": []}
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {"nftables": []}


def validate_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return not addr.is_loopback
    except ValueError:
        return False


# ---------------------------------------------------------------- ruleset ----

def list_ruleset() -> dict[str, Any]:
    """Return a structured view of tables, chains and rules."""
    data = _nft_json("list", "ruleset")
    objects = data.get("nftables", [])
    tables: dict[str, dict[str, Any]] = {}
    chains: dict[str, list[dict[str, Any]]] = {}

    for obj in objects:
        if "table" in obj:
            t = obj["table"]
            key = f"{t.get('family')}/{t.get('name')}"
            tables[key] = {"family": t.get("family"), "name": t.get("name"), "chains": []}
        elif "chain" in obj:
            c = obj["chain"]
            chains.setdefault(f"{c.get('family')}/{c.get('table')}", []).append({
                "name": c.get("name"),
                "type": c.get("type"),
                "hook": c.get("hook"),
                "policy": c.get("policy"),
                "rules": [],
            })

    for obj in objects:
        if "rule" in obj:
            r = obj["rule"]
            tkey = f"{r.get('family')}/{r.get('table')}"
            for ch in chains.get(tkey, []):
                if ch["name"] == r.get("chain"):
                    ch["rules"].append({
                        "handle": r.get("handle"),
                        "expr": _format_expr(r.get("expr", [])),
                    })

    result = []
    for key, tbl in tables.items():
        tbl_chains = chains.get(key, [])
        tbl["chains"] = tbl_chains
        result.append(tbl)
    return {"tables": result}


def _format_expr(expr: list[dict[str, Any]]) -> str:
    """Best-effort human-readable rendering of an nft rule expression."""
    parts: list[str] = []
    for e in expr:
        if "match" in e:
            m = e["match"]
            left = _render_value(m.get("left"))
            right = _render_value(m.get("right"))
            op = m.get("op", "==")
            parts.append(f"{left} {op} {right}".strip())
        elif "accept" in e:
            parts.append("accept")
        elif "drop" in e:
            parts.append("drop")
        elif "counter" in e:
            pass
        elif "log" in e:
            prefix = e["log"].get("prefix", "")
            parts.append(f'log "{prefix}"')
        elif "masquerade" in e:
            parts.append("masquerade")
        else:
            key = next(iter(e.keys()), "")
            if key:
                parts.append(key)
    return " ".join(p for p in parts if p)


def _render_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):
        if "ct" in v:
            return f"ct {v['ct'].get('key', '')}".strip()
        if "meta" in v:
            return v["meta"].get("key", "meta")
        if "payload" in v:
            p = v["payload"]
            return f"{p.get('protocol', '')}.{p.get('field', '')}"
        if "set" in v:
            items = v["set"]
            return "{" + ", ".join(_render_value(i) for i in items) + "}"
        if "prefix" in v:
            pr = v["prefix"]
            return f"{_render_value(pr.get('addr'))}/{pr.get('len')}"
        if "range" in v:
            rng = v["range"]
            return f"{_render_value(rng[0])}-{_render_value(rng[1])}"
        return json.dumps(v)
    if isinstance(v, list):
        return "{" + ", ".join(_render_value(i) for i in v) + "}"
    return str(v)


# --------------------------------------------------------------- blocklist ----

def list_blocked() -> list[dict[str, Any]]:
    data = _nft_json("list", "set", "ip", BLOCK_TABLE, BLOCK_SET)
    ips: list[dict[str, Any]] = []
    for obj in data.get("nftables", []):
        if "set" in obj:
            for elem in obj["set"].get("elem", []) or []:
                if isinstance(elem, str):
                    ips.append({"ip": elem})
                elif isinstance(elem, dict) and "elem" in elem:
                    inner = elem["elem"]
                    ips.append({"ip": _render_value(inner.get("val"))})
    return ips


def block_ip(ip: str, duration: int = 3600, reason: str = "dashboard") -> dict[str, Any]:
    if not validate_ip(ip):
        raise ValueError(f"invalid IP: {ip}")
    res = shell.run([settings.block_ip_script, "add", ip, str(int(duration)), reason], timeout=15)
    return {"ok": res.ok, "ip": ip, "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}


def unblock_ip(ip: str) -> dict[str, Any]:
    if not validate_ip(ip):
        raise ValueError(f"invalid IP: {ip}")
    res = shell.run([settings.block_ip_script, "delete", ip], timeout=15)
    return {"ok": res.ok, "ip": ip, "stdout": res.stdout.strip(), "stderr": res.stderr.strip()}


# ------------------------------------------------------------- port rules ----

def list_input_rules() -> list[dict[str, Any]]:
    """Return rules of the inet filter input chain (handles for deletion)."""
    rs = list_ruleset()
    for tbl in rs["tables"]:
        if tbl["family"] == "inet" and tbl["name"] == "filter":
            for ch in tbl["chains"]:
                if ch["name"] == "input":
                    return ch["rules"]
    return []


def add_port_rule(proto: str, port: int, action: str = "accept", iif: str | None = None) -> dict[str, Any]:
    if proto not in {"tcp", "udp"}:
        raise ValueError("proto must be tcp or udp")
    if not (0 < int(port) < 65536):
        raise ValueError("invalid port")
    if action not in {"accept", "drop"}:
        raise ValueError("action must be accept or drop")
    args = ["nft", "add", "rule", "inet", "filter", "input"]
    if iif:
        args += ["iifname", iif]
    args += [proto, "dport", str(int(port)), action]
    res = shell.run(args, timeout=10)
    return {"ok": res.ok, "stderr": res.stderr.strip()}


def delete_input_rule(handle: int) -> dict[str, Any]:
    res = shell.run(
        ["nft", "delete", "rule", "inet", "filter", "input", "handle", str(int(handle))],
        timeout=10,
    )
    return {"ok": res.ok, "stderr": res.stderr.strip()}


def counters() -> dict[str, int]:
    """Aggregate drop counters parsed from journald is heavy; instead count set size."""
    return {"blocked_ips": len(list_blocked())}
