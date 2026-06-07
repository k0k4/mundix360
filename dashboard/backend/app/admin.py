"""Local, root-only administrative CLI for the Mundix360 appliance.

This tool is the recovery trust-anchor for the master password, analogous to
resetting the Linux root password from the console. It operates DIRECTLY on the
local config store and is intentionally NOT reachable over the network/WAF — the
only protection it relies on is local shell access to the appliance (the AI
SQLite DB is root-only).

Usage (from dashboard/backend, with the project venv):

    /opt/venv/bin/python -m app.admin status
    /opt/venv/bin/python -m app.admin reset-master-password           # prompts
    /opt/venv/bin/python -m app.admin reset-master-password --password 'NovaSenha'
    /opt/venv/bin/python -m app.admin clear-master-password           # set a new one in the UI later
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .services.ai import config_store


def _cmd_status(_args: argparse.Namespace) -> int:
    print(f"master_password_set:    {config_store.master_password_set()}")
    print(f"master_password_source: {config_store.master_password_source()}")
    if config_store.master_password_source() == "env":
        print("  (definida via variável de ambiente AI_MASTER_PASSWORD — "
              "edite o .env para alterá-la)")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    new = args.password
    if not new:
        new = getpass.getpass("Nova senha mestra: ")
        confirm = getpass.getpass("Confirme a nova senha: ")
        if new != confirm:
            print("ERRO: as senhas não conferem.", file=sys.stderr)
            return 1
    if len(new) < 8:
        print("ERRO: a senha mestra deve ter ao menos 8 caracteres.", file=sys.stderr)
        return 1
    config_store.set_master_password(new)
    print("OK: senha mestra redefinida. A nova senha já está ativa.")
    return 0


def _cmd_clear(_args: argparse.Namespace) -> int:
    config_store.clear_master_password()
    print("OK: senha mestra removida.")
    print("Defina uma nova em Assistente → Configuração (nenhuma senha atual será exigida).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.admin",
        description="Ferramentas administrativas locais (somente-root) do Mundix360.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Mostra o estado da senha mestra.").set_defaults(
        func=_cmd_status)

    p_reset = sub.add_parser("reset-master-password",
                             help="Define uma nova senha mestra (recuperação local).")
    p_reset.add_argument("--password", help="Nova senha (se omitido, será solicitada).")
    p_reset.set_defaults(func=_cmd_reset)

    sub.add_parser("clear-master-password",
                   help="Remove a senha mestra para definir uma nova pela interface."
                   ).set_defaults(func=_cmd_clear)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
