#!/usr/bin/env bash
# Fase 00 — Pré-voo: valida ambiente antes de tocar no sistema.
phase_preflight() {
  step "Pré-voo"
  require_root

  # SO suportado.
  local id ver
  id="$(. /etc/os-release && echo "$ID")"
  ver="$(. /etc/os-release && echo "$VERSION_ID")"
  if [[ "$id" != "$TARGET_OS_ID" || "$ver" != "$TARGET_OS_VERSION" ]]; then
    warn "SO detectado: ${id} ${ver} (suportado: ${TARGET_OS_ID} ${TARGET_OS_VERSION})"
    confirm "Continuar mesmo assim?" || die "abortado pelo operador."
  else
    ok "SO ${id} ${ver}"
  fi

  # Arquitetura.
  local arch; arch="$(dpkg --print-architecture)"
  [[ "$arch" == "amd64" ]] || warn "arquitetura ${arch} não testada (esperado amd64)."

  # CPU sem AVX: o ClickHouse >= 22.8 exige AVX e o postinst morre com SIGILL
  # (exit 132). No modo online, pinamos a série 22.3 (última compatível) e o
  # SIEM sobe em versão legada. No modo OFFLINE o bundle já traz debs novos e
  # o pin não resolve — só avisamos claro (a fase 10 trata o pacote como
  # não-crítico, então a instalação continua sem o SIEM).
  if grep -qw avx /proc/cpuinfo; then
    ok "CPU com AVX"
  elif [[ "${MODE}" == "offline" ]]; then
    warn "CPU sem AVX: o ClickHouse empacotado no bundle exige AVX e vai falhar (SIGILL)."
    warn "O SIEM ficará indisponível neste hardware; a instalação continua sem ele."
  elif [[ -e /etc/apt/preferences.d/mundix-clickhouse-noavx ]]; then
    log "CPU sem AVX — pin de ClickHouse já existe (mantido): /etc/apt/preferences.d/mundix-clickhouse-noavx"
  else
    run bash -c "printf 'Package: clickhouse-server clickhouse-common-static clickhouse-client\nPin: version 22.3.*\nPin-Priority: 1001\n' \
      > /etc/apt/preferences.d/mundix-clickhouse-noavx"
    warn "CPU sem AVX — ClickHouse pinado na série legada 22.3 (SIEM em versão legada)."
  fi

  # Espaço em disco (>= 4 GB livres em /).
  local free_kb; free_kb="$(df --output=avail / | tail -1 | tr -d ' ')"
  if (( free_kb < 4194304 )); then
    warn "pouco espaço livre em / ($(( free_kb / 1024 )) MB). Recomendado >= 4 GB."
  else
    ok "disco: $(( free_kb / 1024 / 1024 )) GB livres"
  fi

  # Modo de instalação (offline exige bundle).
  if [[ "${MODE}" == "offline" ]]; then
    [[ -d "${BUNDLE_DIR}/debs" ]] || die "modo offline mas bundle não encontrado em ${BUNDLE_DIR}.
       Num clone do git não há bundle — use:  sudo ./install.sh --online
       Ou descompacte o bundle .tar.zst e rode a partir dele (offline)."
    ok "bundle offline: ${BUNDLE_DIR}"
  else
    ok "modo online (instala via apt da internet)"
  fi
}
