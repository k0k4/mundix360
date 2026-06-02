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
└── frontend/         Vite + React + Refine + Ant Design (SPA com CRUD completo)
    └── src/
        ├── App.tsx          Refine: resources, rotas, tema (dark)
        ├── dataProvider.ts  mapeia recursos Refine → API FastAPI existente
        └── pages/           overview, alerts, firewall/*, network/*, content, flows, logs, system
```

> A SPA é compilada para `frontend/dist/` e **servida pelo próprio FastAPI** (StaticFiles +
> fallback SPA). Resultado: **um único serviço e uma única porta** (`8099`) — produto unificado.

## Stack

- **Backend:** FastAPI (Python 3.12) — API REST + operações privilegiadas (nft, dnsmasq, systemctl).
- **Frontend:** [Refine](https://refine.dev) (MIT) + Ant Design — framework headless de admin com
  CRUD pronto (hooks, formulários, tabelas, notificações), tema escuro corporativo.

## Módulos

| Módulo | Fonte de dados | Capacidades |
|--------|----------------|-------------|
| Visão Geral | tudo | KPIs, saúde de serviços, recursos do host |
| SIEM / Alertas | ClickHouse `akvorado.siem_alerts` | timeline, filtros, severidade |
| **Firewall** | nftables | **blocklist de IP** (criar/excluir), **regras de porta** (criar/excluir), **ruleset** completo |
| Rede / VLANs | dnsmasq + leases | **zonas/VLANs CRUD**, **reservas DHCP CRUD**, concessões DHCP ativas |
| Filtro de Conteúdo | dnsmasq sinkhole | **bloqueio de domínios CRUD** (criar/editar nota/excluir) |
| Fluxos | ClickHouse `akvorado.flows` | volume, top origens/destinos |
| Logs | Loki | suricata, dnsmasq, busca LogQL |
| Sistema | systemd + /proc | serviços, **controle (start/stop/restart/reload)**, CPU/mem/disco |

> Toda gestão (criar / editar / excluir) é feita **pelo próprio painel**. Alterações em dnsmasq
> são validadas com `dnsmasq --test` e revertidas automaticamente (rollback) em caso de erro.

## Segurança

- Operações privilegiadas (`nft`, `systemctl`, `block-ip.sh`) passam por `services/shell.py` com
  **allowlist** estrita; argumentos sempre como lista (sem shell) — sem injeção.
- Auth opcional via `MUNDIX_API_TOKEN` (Bearer). Sem token = somente localhost.
- Backend faz bind apenas em `127.0.0.1`; exponha via reverse proxy (Traefik/Nginx) + Keycloak.

## Execução

### Build do frontend
```bash
cd frontend && npm install && npm run build   # gera frontend/dist (servido pela API)
```

### Via systemd (produção)
```bash
sudo cp backend/mundix-dashboard-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mundix-dashboard-api
```
- App + API: http://127.0.0.1:8099  (API docs: `/docs`)

### Desenvolvimento
```bash
# backend
cd backend && /opt/venv/bin/pip install -r requirements.txt
/opt/venv/bin/python -m uvicorn app.main:app --reload --port 8099

# frontend (Vite dev server com proxy /api → 8099)
cd frontend && npm install && npm run dev   # http://127.0.0.1:5273
```

## Configuração

Backend: copie `backend/.env.example` para `backend/.env`.
Frontend: opcional `VITE_API_TOKEN` (Bearer) se o backend exigir `MUNDIX_API_TOKEN`.
O `/api/*` é servido pela mesma origem em produção; em dev o Vite faz proxy para `:8099`.
