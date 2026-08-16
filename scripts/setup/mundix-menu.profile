# Mundix Security 360 — menu de console no login local (estilo pfSense).
# Abre o menu de recuperação automaticamente APENAS para root no console
# local (VGA/serial). Sessões SSH nunca são interceptadas.
if [[ "$(id -u 2>/dev/null)" == "0" && -z "${SSH_CONNECTION:-}" && -z "${SSH_TTY:-}" ]]; then
  case "$(tty 2>/dev/null)" in
    /dev/tty1|/dev/ttyS0|/dev/ttyAMA0|/dev/hvc0)
      [[ -x /usr/local/bin/mundix-menu ]] && /usr/local/bin/mundix-menu
      ;;
  esac
fi
