"""Tool definitions (OpenAI function-calling) + dispatcher.

The dispatcher is the security boundary: it enforces policy regardless of what the
model asks, redacts secrets in every result, and audits every action.
"""
from __future__ import annotations

import json
import ipaddress
import os
import subprocess
from typing import Any, Callable

from .. import clickhouse, content, firewall, network, system, threatintel
from ...config import settings
from . import codegate, memory, livingmemory, safety

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
            "name": "read_file",
            "description": "Lê um arquivo de código-fonte sob /opt/mundix360 (com números de linha). Use ANTES de propor uma edição para obter o conteúdo exato. Segredos são bloqueados/redigidos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Caminho do arquivo (relativo à raiz do projeto ou absoluto sob /opt/mundix360)"},
                    "start": {"type": "integer", "description": "Linha inicial (1-based, opcional)"},
                    "end": {"type": "integer", "description": "Linha final (1-based, opcional)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Lista o conteúdo de um diretório do projeto (arquivos e subpastas) sob /opt/mundix360.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Caminho do diretório (default: raiz do projeto)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Busca um padrão (regex/texto) nos arquivos do projeto e retorna arquivo:linha:trecho. Use para localizar onde algo está definido antes de editar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto ou regex a procurar"},
                    "path": {"type": "string", "description": "Subdiretório/arquivo onde buscar (opcional)"},
                    "glob": {"type": "string", "description": "Filtro de nome, ex.: *.py (opcional)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_code_change",
            "description": "Propõe alteração no código-fonte enviando o conteúdo COMPLETO do arquivo (use para criar arquivos novos ou reescritas grandes). NÃO aplica: requer o operador digitar a senha master no painel. Para edições pontuais prefira propose_code_edit.",
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
            "name": "propose_code_edit",
            "description": "Propõe uma edição PONTUAL substituindo um trecho exato e único do arquivo (find→replace), sem reenviar o arquivo todo. Mais fácil/barato. NÃO aplica: requer a senha master do operador no painel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Caminho do arquivo existente (sob /opt/mundix360)"},
                    "find": {"type": "string", "description": "Trecho EXATO a localizar (deve ser único no arquivo; inclua contexto suficiente)"},
                    "replace": {"type": "string", "description": "Texto que substituirá o trecho 'find'"},
                    "description": {"type": "string", "description": "Resumo da mudança (vira mensagem de commit)"},
                },
                "required": ["path", "find", "replace", "description"],
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
    {
        "type": "function",
        "function": {
            "name": "update_system_memory",
            "description": (
                "Atualiza UMA seção da memória viva do sistema (documento curado que "
                "descreve como a plataforma funciona). Use quando algo do sistema mudar "
                "de forma duradoura. Substitui a seção '## <title>' inteira."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título da seção (sem '##')."},
                    "content": {"type": "string", "description": "Novo conteúdo da seção (markdown)."},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_system_memory",
            "description": "Lê o documento completo da memória viva do sistema.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_journal",
            "description": (
                "Publica um recado no mural/diário compartilhado com o operador e o "
                "agente de build (copilot-cli). Use para registrar decisões, dúvidas, "
                "incidentes ou pedir algo a quem evolui o sistema."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "topic": {"type": "string", "description": "Assunto curto (opcional)."},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_journal",
            "description": "Lê as mensagens recentes do mural/diário compartilhado.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "threat_intel_status",
            "description": ("Mostra o estado do bloqueio proativo por Threat Intelligence "
                            "(feeds de IOC: C2 de malware, botnets, redes sequestradas, "
                            "atacantes), nº de redes bloqueadas, feeds ativos e última aplicação."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "threat_intel_update",
            "description": ("Rebaixa os feeds de Threat Intelligence e reaplica o bloqueio no "
                            "firewall (nftables). Opcionalmente especifique feeds por id "
                            "(spamhaus-drop, feodo, et-compromised, et-block, dshield, "
                            "blocklist-de); vazio = todos os ativos."),
            "parameters": {
                "type": "object",
                "properties": {
                    "feeds": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "backup_status",
            "description": ("Mostra o estado dos backups do appliance: quantidade, espaço "
                            "usado, agendamento, retenção e resultado da última execução "
                            "(verificada ou não)."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "backup_run",
            "description": ("Gera AGORA um backup verificado (configs de firewall/DNS/DHCP/WAF, "
                            "estado do painel, memória da IA e histórico do SIEM) e valida sua "
                            "integridade. Não restaura nada."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# Tools that may pause the agent loop awaiting out-of-band user action.
SPECIAL_TOOLS = {"propose_code_change", "propose_code_edit"}

# name -> {"required": [...], "props": {...}} built once from the tool schemas so
# dispatch can validate arguments and return a helpful, model-correctable error
# instead of crashing deep inside a handler (e.g. KeyError: 'path').
_TOOL_SCHEMA: dict[str, dict[str, Any]] = {
    t["function"]["name"]: {
        "required": list(t["function"].get("parameters", {}).get("required", [])),
        "props": t["function"].get("parameters", {}).get("properties", {}),
    }
    for t in TOOLS
}


def _validate_args(name: str, args: dict[str, Any]) -> str | None:
    """Return a clear error message if required arguments are missing/empty, else
    None. Keeps the agent from looping on a cryptic handler exception."""
    schema = _TOOL_SCHEMA.get(name)
    if not schema:
        return None
    missing = [
        k for k in schema["required"]
        if k not in args or args[k] in (None, "")
    ]
    if missing:
        allowed = ", ".join(schema["props"].keys()) or "(nenhum)"
        return (
            f"parâmetro(s) obrigatório(s) ausente(s): {', '.join(missing)}. "
            f"Esta ferramenta exige: {', '.join(schema['required'])}. "
            f"Parâmetros aceitos: {allowed}."
        )
    return None


_MAX_OUTPUT = 6000


def _truncate(s: str) -> str:
    if len(s) > _MAX_OUTPUT:
        return s[:_MAX_OUTPUT] + f"\n…[truncado, +{len(s) - _MAX_OUTPUT} chars]"
    return s


def _read_file(path: str, start: int | None = None, end: int | None = None) -> dict[str, Any]:
    if not safety.in_editable_root(path):
        return {"error": "caminho fora da raiz editável do projeto"}
    if safety.is_secret_path(path):
        return {"blocked": True, "error": "arquivo de segredo — leitura não permitida"}
    real = safety.resolve_in_root(path)
    if not os.path.isfile(real):
        return {"error": f"arquivo não encontrado: {path}"}
    if real.endswith((".db", ".sqlite", ".png", ".jpg", ".jpeg", ".gz", ".zip", ".lock")):
        return {"error": "tipo de arquivo binário/não legível"}
    try:
        if os.path.getsize(real) > 512_000:
            return {"error": "arquivo muito grande (>500KB); leia um intervalo com start/end"}
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": safety.redact(str(e))}
    total = len(lines)
    s = max(1, int(start)) if start else 1
    e = min(total, int(end)) if end else total
    sliced = lines[s - 1:e]
    numbered = "".join(f"{i}\t{ln}" for i, ln in enumerate(sliced, start=s))
    return {
        "path": path,
        "total_lines": total,
        "start": s,
        "end": e,
        "content": _truncate(safety.redact(numbered)),
    }


def _list_dir(path: str | None) -> dict[str, Any]:
    target = path or settings.ai_editable_root
    if not safety.in_editable_root(target):
        return {"error": "caminho fora da raiz editável do projeto"}
    real = safety.resolve_in_root(target)
    if not os.path.isdir(real):
        return {"error": f"diretório não encontrado: {target}"}
    try:
        names = sorted(os.listdir(real))
    except OSError as e:
        return {"error": safety.redact(str(e))}
    entries = []
    for n in names:
        if n in (".git", "__pycache__", "node_modules") or n.startswith("."):
            continue
        full = os.path.join(real, n)
        is_dir = os.path.isdir(full)
        try:
            size = os.path.getsize(full) if not is_dir else None
        except OSError:
            size = None
        entries.append({"name": n + ("/" if is_dir else ""), "dir": is_dir, "size": size})
    rel = os.path.relpath(real, settings.ai_editable_root)
    return {"path": "." if rel == "." else rel, "count": len(entries), "entries": entries}


def _search_code(query: str, path: str | None, glob: str | None) -> dict[str, Any]:
    base = path or settings.ai_editable_root
    if not safety.in_editable_root(base):
        return {"error": "caminho fora da raiz editável do projeto"}
    real = safety.resolve_in_root(base)
    if not os.path.exists(real):
        return {"error": f"caminho não encontrado: {base}"}
    cmd = ["grep", "-rInE", "--max-count=5",
           "--exclude-dir=.git", "--exclude-dir=__pycache__",
           "--exclude-dir=node_modules", "--exclude-dir=dist",
           "--exclude=*.db", "--exclude=*.sqlite", "--exclude=*.env"]
    if glob:
        cmd.append(f"--include={glob}")
    cmd.extend(["--", query, real])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return {"error": "timeout (20s) na busca"}
    out_lines = [ln for ln in (r.stdout or "").splitlines() if not safety.is_secret_path(ln.split(":", 1)[0])]
    out_lines = out_lines[:80]
    rel_lines = [ln.replace(settings.ai_editable_root + "/", "") for ln in out_lines]
    return {
        "query": query,
        "matches": len(rel_lines),
        "results": _truncate(safety.redact("\n".join(rel_lines)) or "(nenhum resultado)"),
    }


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
    if name == "propose_code_edit":
        for k in ("find", "replace"):
            if k in safe:
                safe[k] = f"<{len(str(safe[k]))} chars omitidos>"
    return safe


def dispatch(name: str, args: dict[str, Any], conversation_id: str | None) -> dict[str, Any]:
    """Execute a tool. Returns a dict; may carry a special '_event' for the UI."""
    try:
        arg_err = _validate_args(name, args)
        if arg_err:
            memory.audit(name, _audit_args(name, args), "error", arg_err, conversation_id)
            return {"error": arg_err}
        result = _do_dispatch(name, args, conversation_id)
        # Coerce to JSON-safe values (ClickHouse returns datetime/Decimal/UUID/IP
        # objects) so downstream json.dumps — here, the SSE stream and the tool
        # message persisted for the model — never raise and abort the turn.
        event = result.pop("_event", None) if isinstance(result, dict) else None
        result = json.loads(json.dumps(result, ensure_ascii=False, default=str))
        if event is not None:
            result["_event"] = event
        status = "blocked" if result.get("blocked") else ("error" if result.get("error") else "ok")
        summary = safety.redact(json.dumps(result, ensure_ascii=False, default=str))[:500]
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
    if name == "read_file":
        return _read_file(a["path"], a.get("start"), a.get("end"))
    if name == "list_dir":
        return _list_dir(a.get("path"))
    if name == "search_code":
        return _search_code(a["query"], a.get("path"), a.get("glob"))
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
    if name == "propose_code_edit":
        info = codegate.propose_edit(a["path"], a["find"], a["replace"], a["description"])
        return {
            "_event": {"type": "code_change_pending", "data": info},
            "pending": True,
            "message": (
                f"Edição proposta em {info['path']}. Aguardando o operador inserir a "
                f"senha master no painel para aplicar. NÃO está aplicada ainda."
            ),
            "change_id": info["id"],
        }
    if name == "remember":
        return memory.add_fact(a["content"], a.get("category", "note"))
    if name == "forget":
        memory.delete_fact(a["id"])
        return {"ok": True, "forgotten": a["id"]}
    if name == "update_system_memory":
        doc = livingmemory.update_section(a["title"], a["content"], updated_by="mundix-ai")
        return {"ok": True, "section": a["title"], "size": len(doc["content"])}
    if name == "read_system_memory":
        return {"content": livingmemory.get_memory()["content"]}
    if name == "post_journal":
        entry = livingmemory.post("mundix-ai", a["message"], a.get("topic"))
        return {"ok": True, "id": entry["id"]}
    if name == "read_journal":
        return {"entries": livingmemory.recent(min(int(a.get("limit", 20)), 100))}
    if name == "threat_intel_status":
        return threatintel.overview()
    if name == "threat_intel_update":
        feeds = a.get("feeds") or None
        return threatintel.manual_update(feeds)
    if name == "backup_status":
        from .. import backup as _bk
        return _bk.overview()
    if name == "backup_run":
        from .. import backup as _bk
        return _bk.run_backup()
    return {"error": f"ferramenta desconhecida: {name}"}
