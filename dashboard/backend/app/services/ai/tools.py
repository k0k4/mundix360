"""Tool definitions (OpenAI function-calling) + dispatcher.

The dispatcher is the security boundary: it enforces policy regardless of what the
model asks, redacts secrets in every result, and audits every action.
"""
from __future__ import annotations

import json
import ipaddress
import subprocess
from typing import Any, Callable

from .. import clickhouse, content, firewall, network, system
from ...config import settings
from . import codegate, memory, safety

# --------------------------------------------------------------------------- #
# Tool schemas exposed to the model                                           #
# --------------------------------------------------------------------------- #
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "block_ip",
            "description": "Bloqueia um endereço IP no firewall (nftables blocklist).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "Endereço IP a bloquear"},
                    "duration": {"type": "integer", "description": "Duração em segundos (default 3600)"},
                    "reason": {"type": "string"},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unblock_ip",
            "description": "Remove um IP da blocklist do firewall.",
            "parameters": {
                "type": "object",
                "properties": {"ip": {"type": "string"}},
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_port_rule",
            "description": "Adiciona regra na chain input para uma porta (accept/drop).",
            "parameters": {
                "type": "object",
                "properties": {
                    "proto": {"type": "string", "enum": ["tcp", "udp"]},
                    "port": {"type": "integer"},
                    "action": {"type": "string", "enum": ["accept", "drop"]},
                    "iif": {"type": "string", "description": "Interface de entrada (opcional)"},
                },
                "required": ["proto", "port"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "block_domain",
            "description": "Bloqueia um domínio/site via sinkhole DNS (dnsmasq). Use para pedidos do tipo 'bloqueie o site X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "note": {"type": "string", "description": "Categoria/motivo"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unblock_domain",
            "description": "Remove um domínio do bloqueio de conteúdo.",
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_zone",
            "description": "Cria, edita ou exclui uma VLAN/zona de rede (dnsmasq). Zonas built-in (lan/dmz/iot) não podem ser excluídas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["create", "update", "delete"]},
                    "zone": {"type": "string"},
                    "interface": {"type": "string"},
                    "domain": {"type": "string"},
                    "gateway": {"type": "string"},
                    "dhcp_start": {"type": "string"},
                    "dhcp_end": {"type": "string"},
                    "netmask": {"type": "string"},
                    "lease_time": {"type": "string"},
                },
                "required": ["op", "zone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "manage_reservation",
            "description": "Cria ou remove uma reserva DHCP (IP fixo por MAC).",
            "parameters": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["create", "delete"]},
                    "mac": {"type": "string"},
                    "ip": {"type": "string"},
                    "hostname": {"type": "string"},
                },
                "required": ["op", "mac"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "service_action",
            "description": "Controla um serviço da plataforma (start/stop/restart/reload).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "action": {"type": "string", "enum": ["start", "stop", "restart", "reload", "reload-or-restart"]},
                },
                "required": ["name", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_alerts",
            "description": "Consulta alertas recentes do SIEM (ClickHouse).",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer"},
                    "min_severity": {"type": "integer"},
                    "source": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overview",
            "description": "Retorna a visão geral do sistema (saúde, alertas, recursos, serviços).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Executa um comando shell no servidor (diagnóstico/operação). Leitura de segredos e escrita no código-fonte são bloqueadas.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_code_change",
            "description": "Propõe alteração no código-fonte. NÃO aplica: requer o operador digitar a senha master no painel para confirmar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Caminho do arquivo (sob /opt/mundix360)"},
                    "new_content": {"type": "string", "description": "Conteúdo COMPLETO do arquivo após a alteração"},
                    "description": {"type": "string", "description": "Resumo da mudança (vira mensagem de commit)"},
                },
                "required": ["path", "new_content", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Guarda um fato na memória evolutiva (preferência do operador, fato do ambiente, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": ["system", "preference", "incident", "exclusion", "note"]},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove um fato da memória pelo id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
]

# Tools that may pause the agent loop awaiting out-of-band user action.
SPECIAL_TOOLS = {"propose_code_change"}

_MAX_OUTPUT = 6000


def _truncate(s: str) -> str:
    if len(s) > _MAX_OUTPUT:
        return s[:_MAX_OUTPUT] + f"\n…[truncado, +{len(s) - _MAX_OUTPUT} chars]"
    return s


def _run_shell(command: str) -> dict[str, Any]:
    reason = safety.shell_precheck(command)
    if reason:
        return {"blocked": True, "error": reason}
    try:
        r = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True, text=True, timeout=45,
            env=safety.sanitized_env(), cwd=settings.ai_editable_root,
            start_new_session=True,
        )
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        return {
            "returncode": r.returncode,
            "output": _truncate(safety.redact(out.strip()) or "(sem saída)"),
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout (45s) ao executar o comando"}


# --------------------------------------------------------------------------- #
# Dispatch                                                                     #
# --------------------------------------------------------------------------- #
def _audit_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Sanitize tool arguments before they are persisted to the audit log."""
    safe = dict(args)
    if name == "propose_code_change":
        # Never store full source content in the audit log.
        if "new_content" in safe:
            safe["new_content"] = f"<{len(str(safe['new_content']))} chars omitidos>"
    return safe


def dispatch(name: str, args: dict[str, Any], conversation_id: str | None) -> dict[str, Any]:
    """Execute a tool. Returns a dict; may carry a special '_event' for the UI."""
    try:
        result = _do_dispatch(name, args, conversation_id)
        status = "blocked" if result.get("blocked") else ("error" if result.get("error") else "ok")
        summary = safety.redact(json.dumps(result, ensure_ascii=False))[:500]
        memory.audit(name, _audit_args(name, args), status, summary, conversation_id)
        return result
    except Exception as e:  # never crash the agent loop on a tool error
        memory.audit(name, _audit_args(name, args), "error", safety.redact(str(e)), conversation_id)
        return {"error": f"{type(e).__name__}: {safety.redact(str(e))}"}


# Critical services that must never be stopped/disabled by the AI (anti-lockout).
_PROTECTED_SERVICES = {
    "mundix-dashboard-api",
    "nftables",
    "dnsmasq",
    "ssh",
    "sshd",
    "systemd-networkd",
    "systemd-resolved",
    "clickhouse-server",
}
_DESTRUCTIVE_ACTIONS = {"stop", "disable", "mask", "kill"}


def _guard_service(svc: str, action: str) -> dict[str, Any] | None:
    base = svc.replace(".service", "").strip().lower()
    if base in _PROTECTED_SERVICES and action.lower() in _DESTRUCTIVE_ACTIONS:
        return {
            "blocked": True,
            "error": (
                f"Ação '{action}' bloqueada no serviço crítico '{svc}': interromperia "
                f"a gestão/conectividade do appliance. Use 'restart' se necessário."
            ),
        }
    return None


def _guard_block_ip(ip: str) -> dict[str, Any] | None:
    """Refuse to block gateways/own addresses to avoid locking out the appliance."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return {"error": f"IP inválido: {ip}"}
    if addr.is_loopback:
        return {"blocked": True, "error": "Não é permitido bloquear o loopback."}
    protected: set[str] = set()
    try:
        for z in network.list_zones():
            gw = (z.get("gateway") or "").strip()
            if gw:
                protected.add(gw)
    except Exception:
        pass
    if str(addr) in protected:
        return {
            "blocked": True,
            "error": (
                f"IP {ip} é um gateway de zona do appliance; bloqueá-lo derrubaria a "
                f"rede. Ação recusada."
            ),
        }
    return None


def _do_dispatch(name: str, a: dict[str, Any], cid: str | None) -> dict[str, Any]:
    if name == "block_ip":
        guard = _guard_block_ip(a["ip"])
        if guard:
            return guard
        return firewall.block_ip(a["ip"], int(a.get("duration", 3600)), a.get("reason", "ai"))
    if name == "unblock_ip":
        return firewall.unblock_ip(a["ip"])
    if name == "add_port_rule":
        return firewall.add_port_rule(a["proto"], int(a["port"]), a.get("action", "accept"), a.get("iif"))
    if name == "block_domain":
        return content.add_domain(a["domain"], a.get("note", "ai"))
    if name == "unblock_domain":
        return content.remove_domain(a["domain"])
    if name == "manage_zone":
        op = a.get("op")
        if op == "delete":
            return network.delete_zone(a["zone"])
        data = {k: a.get(k) for k in (
            "zone", "interface", "domain", "gateway", "dhcp_start", "dhcp_end", "netmask", "lease_time"
        )}
        return network.save_zone(data, create=(op == "create"))
    if name == "manage_reservation":
        if a.get("op") == "delete":
            return network.delete_reservation(a["mac"])
        return network.save_reservation(
            {"mac": a["mac"], "ip": a.get("ip", ""), "hostname": a.get("hostname", "")},
            create=True,
        )
    if name == "service_action":
        guard = _guard_service(a["name"], a["action"])
        if guard:
            return guard
        return system.control_service(a["name"], a["action"])
    if name == "query_alerts":
        where = ["timestamp > now() - INTERVAL {h:UInt32} HOUR", "severity >= {s:UInt8}"]
        params: dict[str, Any] = {"h": int(a.get("hours", 24)), "s": int(a.get("min_severity", 0))}
        if a.get("source"):
            where.append("source = {src:String}")
            params["src"] = a["source"]
        limit = min(int(a.get("limit", 20)), 100)
        rows = clickhouse.query(
            "SELECT timestamp, source, severity, rule_name, src_ip, dst_ip, description "
            f"FROM siem_alerts WHERE {' AND '.join(where)} ORDER BY timestamp DESC LIMIT {limit}",
            params,
        )
        return {"count": len(rows), "alerts": rows}
    if name == "get_overview":
        return {
            "services": system.all_services(),
            "host": system.host_metrics(),
            "blocked_ips": len(firewall.list_blocked()),
            "zones": [z["zone"] for z in network.list_zones()],
        }
    if name == "run_shell":
        return _run_shell(a["command"])
    if name == "propose_code_change":
        info = codegate.propose(a["path"], a["new_content"], a["description"])
        return {
            "_event": {"type": "code_change_pending", "data": info},
            "pending": True,
            "message": (
                f"Mudança proposta em {info['path']}. Aguardando o operador inserir a "
                f"senha master no painel para aplicar. NÃO está aplicada ainda."
            ),
            "change_id": info["id"],
        }
    if name == "remember":
        return memory.add_fact(a["content"], a.get("category", "note"))
    if name == "forget":
        memory.delete_fact(a["id"])
        return {"ok": True, "forgotten": a["id"]}
    return {"error": f"ferramenta desconhecida: {name}"}
