# Mundix Security 360 — Copilot Instructions

Unified open-source network security appliance (firewall, IDS, SIEM, WAF, DNS/DHCP,
content filtering, NetFlow) for Brazilian SMBs, with an embedded AI assistant. Runs on
Ubuntu 24.04. Code lives at `/opt/mundix360` on the appliance — `config.py` and several
services hardcode that absolute path, so keep the repo there when running locally.

Docs are largely in Portuguese (`ARQUITETURA.md`, `installer/README.md`,
`tutorial_de_implantação.md`); code, identifiers, and docstrings are in English.

## Architecture

Two deployable parts plus host integration:

- **Backend** (`dashboard/backend/app`) — FastAPI app (`app.main:app`). `main.py` wires
  routers under `Depends(require_auth)`, mounts the built SPA from `frontend/dist`, and runs
  firewall self-heal/hardening on startup. Layering is strict:
  - `routers/*.py` — thin HTTP layer; define Pydantic request models, call services. Each
    router sets `APIRouter(prefix="/api/<name>", tags=["<name>"])`.
  - `services/*.py` — all business logic and host interaction (nftables, netplan, dnsmasq,
    systemd, ClickHouse, Loki, VictoriaMetrics).
  - `services/ai/*` — the AI assistant (DashScope/Qwen agent, tools, SQLite "living memory",
    PII masking, safety/codegate guards). State persists in `dashboard/backend/data/ai.db`.
- **Frontend** (`dashboard/frontend`) — Refine + Ant Design + Vite SPA (TypeScript). Built to
  `dist/` and served by the backend; in dev it proxies `/api` and `/health` to `:8099`.
- **Installer** (`installer/`) — idempotent, adaptive appliance provisioning (pfSense-style
  offline bundle). `manifest.env` is the single source of truth for packages/units/paths;
  `mundix-install.sh` orchestrates phases in `lib/`. `scripts/` holds host-side helpers
  (active-response IP blocking, triage).

## Critical conventions

- **Never run privileged/host commands directly.** All shell-outs go through
  `services/shell.py` `run(args: list[str])`, which enforces an `ALLOWED_BINARIES` allowlist
  and always passes args as a list (no shell string). To use a new binary (e.g. `nft`,
  `systemctl`, `ip`), add it to the allowlist there — do not call `subprocess` elsewhere.
- **Config** is centralized in `app/config.py` via pydantic-settings. Env vars use the
  `MUNDIX_` prefix and load from `/opt/mundix360/.env`. Import the singleton `settings`; never
  read `os.environ` directly. Secrets (API tokens, master password) must come from env, never
  hardcoded or committed.
- **Auth** is optional bearer-token (`MUNDIX_API_TOKEN`); empty token disables auth for
  localhost-only binding. The API is meant to bind `127.0.0.1` behind nginx.
- **Firewall edits must stay anti-lockout**: the input chain must always accept mgmt ports
  (22/80/443) and `nftables-base` must be adaptive (no hardcoded NICs).
- Every Python module starts with `from __future__ import annotations` and a module docstring.
- Background schedulers (contentcat, threatintel, backup, multiwan) start in `main.py`'s
  `startup` hook — register new ones there.

## Build & run

Backend (Python 3.12, deps in `dashboard/backend/requirements.txt`):
```bash
cd dashboard/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099   # dev
```
Frontend:
```bash
cd dashboard/frontend
npm install
npm run dev      # vite dev server on :5273, proxies to backend :8099
npm run build    # tsc -b && vite build  ->  dist/  (what production serves)
```
`dashboard/build.sh` is the idempotent build used by the `mundix-dashboard-build` systemd
unit. Production runs as systemd services (`mundix-dashboard-api`, `mundix-dashboard-build`).

There is currently **no automated test suite or linter config** in the repo. Verify backend
changes by importing the app / hitting `/health`, and frontend changes with `npm run build`
(the TypeScript build is the type check).

## Gotchas

- ModSecurity is broken on Ubuntu 24.04 (t64 ABI bug) and nginx segfaults with the WAF on;
  the installer self-tests and fails the WAF open. Don't assume the WAF is active.
- The AI assistant targets Qwen3.7-Max via DashScope OpenAI-compatible API. The model is a
  reasoning model: stream/return only `content`, never leak `reasoning_content` to the UI.
- `.gitignore` excludes `*.db`, `/data/`, `/logs/`, and `*.env` (except `*.env.example` and
  `installer/manifest.env`). Never commit databases, runtime data, or secrets.
