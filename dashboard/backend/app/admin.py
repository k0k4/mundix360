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


# --- dashboard user accounts (local root recovery) -------------------------
def _cmd_user_list(_args: argparse.Namespace) -> int:
    from .services import users
    users.init_db()
    rows = users.list_users()
    if not rows:
        print("(nenhum usuário cadastrado — use 'create-admin' ou a tela de configuração inicial)")
        return 0
    print(f"{'USUÁRIO':<24} {'PERFIL':<10} {'ATIVO':<6} ÚLTIMO LOGIN")
    for u in rows:
        last = "-" if not u["last_login"] else \
            __import__("datetime").datetime.fromtimestamp(u["last_login"]).isoformat(timespec="seconds")
        print(f"{u['username']:<24} {u['role']:<10} {'sim' if u['active'] else 'não':<6} {last}")
    return 0


def _prompt_password(args: argparse.Namespace) -> str | None:
    new = args.password
    if not new:
        new = getpass.getpass("Senha: ")
        confirm = getpass.getpass("Confirme a senha: ")
        if new != confirm:
            print("ERRO: as senhas não conferem.", file=sys.stderr)
            return None
    return new


def _cmd_create_admin(args: argparse.Namespace) -> int:
    from .services import users
    users.init_db()
    pw = _prompt_password(args)
    if pw is None:
        return 1
    try:
        u = users.create_user(args.username, pw, role="admin")
    except ValueError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    print(f"OK: administrador '{u['username']}' criado.")
    return 0


def _cmd_reset_user(args: argparse.Namespace) -> int:
    from .services import users
    users.init_db()
    target = next((u for u in users.list_users()
                   if u["username"].lower() == args.username.lower()), None)
    if not target:
        print(f"ERRO: usuário '{args.username}' não encontrado.", file=sys.stderr)
        return 1
    pw = _prompt_password(args)
    if pw is None:
        return 1
    try:
        users.update_user(target["id"], password=pw, active=True)
    except ValueError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    print(f"OK: senha de '{target['username']}' redefinida (conta ativada; sessões revogadas).")
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

    sub.add_parser("list-users", help="Lista as contas do dashboard."
                   ).set_defaults(func=_cmd_user_list)

    p_admin = sub.add_parser(
        "create-admin", help="Cria uma conta de administrador do dashboard.")
    p_admin.add_argument("username", help="Nome do administrador.")
    p_admin.add_argument("--password", help="Senha (se omitida, será solicitada).")
    p_admin.set_defaults(func=_cmd_create_admin)

    p_rpw = sub.add_parser(
        "reset-password", help="Redefine a senha de uma conta e a reativa.")
    p_rpw.add_argument("username", help="Conta alvo.")
    p_rpw.add_argument("--password", help="Nova senha (se omitida, será solicitada).")
    p_rpw.set_defaults(func=_cmd_reset_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
