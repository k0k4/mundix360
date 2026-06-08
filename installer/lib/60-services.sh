#!/usr/bin/env bash
# Fase 60 — Serviços: habilita/inicia o perfil núcleo e desativa o que não
# pertence a ele (caso de imagem clonada com a stack pesada).

phase_services() {
  step "Serviços (perfil ${MUNDIX_PROFILE})"

  # Garante forwarding de pacotes (firewall roteia entre zonas).
  if [[ ! -f /etc/sysctl.d/99-mundix-forward.conf ]]; then
    run bash -c "echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-mundix-forward.conf"
    run sysctl --system >/dev/null 2>&1 || true
  fi

  # Desabilita componentes fora do perfil núcleo (não falha se não existirem).
  local u
  for u in "${PROFILE_DISABLE_UNITS[@]}"; do
    if systemctl list-unit-files "$u" >/dev/null 2>&1 && systemctl is-enabled "$u" >/dev/null 2>&1; then
      log "desabilitando (fora do perfil): $u"
      run systemctl disable --now "$u" >/dev/null 2>&1 || true
    fi
  done

  run systemctl daemon-reload

  # Habilita serviços de distro do núcleo.
  for u in "${SYSTEM_UNITS_ENABLE[@]}"; do
    run systemctl enable "$u" >/dev/null 2>&1 || warn "não consegui habilitar $u"
  done

  # Habilita units do Mundix.
  for u in "${MUNDIX_UNITS[@]}"; do
    run systemctl enable "$u" >/dev/null 2>&1 || warn "não consegui habilitar $u"
  done

  ok "serviços do perfil habilitados (start efetivo após o first-boot)"
}
