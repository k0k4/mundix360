# Mundix360 — Dashboard Centralizador

Ponto único de **gestão e visibilidade** de toda a plataforma Mundix Security 360.

## Arquitetura

```
dashboard/
├── backend/          FastAPI (Python 3.12) — API unificada + operações privilegiadas
│   └── app/
│       ├── main.py           app + routers
│       ├── config.py         settings (env MUNDIX_*)
│       ├── security.py       auth Bearer opcional
│       ├── routers/          overview, alerts, firewall, network, content, flows, logs, system
│       └── services/         clickhouse, metrics(VM), loki, firewall(nft), network(dnsmasq), content, system, shell
└── frontend/         Next.js 14 + Tailwind + componentes shadcn-style
    └── src/app/      /, /siem, /firewall, /network, /content, /flows, /logs, /system
```

## Módulos

| Módulo | Fonte de dados | Capacidades |
|--------|----------------|-------------|
| Visão Geral | tudo | KPIs, saúde de serviços, recursos do host |
| SIEM / Alertas | ClickHouse `akvorado.siem_alerts` | timeline, filtros, severidade |
| **Firewall** | nftables | **blocklist de IP** (add/remove), **regras de porta** (add/remove), **ruleset** completo |
| Rede / VLANs | dnsmasq + leases | zonas LAN/DMZ/IoT, concessões DHCP |
| Filtro de Conteúdo | dnsmasq sinkhole | bloqueio de domínios (0.0.0.0) |
| Fluxos | ClickHouse `akvorado.flows` | volume, top origens/destinos |
| Logs | Loki | suricata, dnsmasq, busca LogQL |
| Sistema | systemd + /proc | serviços, CPU/mem/disco |

## Segurança

- Operações privilegiadas (`nft`, `systemctl`, `block-ip.sh`) passam por `services/shell.py` com
  **allowlist** estrita; argumentos sempre como lista (sem shell) — sem injeção.
- Auth opcional via `MUNDIX_API_TOKEN` (Bearer). Sem token = somente localhost.
- Backend faz bind apenas em `127.0.0.1`; exponha via reverse proxy (Traefik/Nginx) + Keycloak.

## Execução

### Via systemd (produção)
```bash
sudo cp backend/mundix-dashboard-api.service /etc/systemd/system/
sudo cp frontend/mundix-dashboard-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mundix-dashboard-api mundix-dashboard-web
```
- API:  http://127.0.0.1:8099  (docs: `/docs`)
- Web:  http://127.0.0.1:3001

### Desenvolvimento
```bash
# backend
cd backend && /opt/venv/bin/pip install -r requirements.txt
/opt/venv/bin/python -m uvicorn app.main:app --reload --port 8099

# frontend
cd frontend && npm install && npm run dev
```

## Configuração

Backend: copie `backend/.env.example` para `backend/.env`.
Frontend: usa `MUNDIX_API_BASE` (default `http://127.0.0.1:8099`) para o proxy `/api/*`.
