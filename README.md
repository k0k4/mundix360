# Mundix Security 360

**Firewall/UTM open appliance para Ubuntu 24.04** — painel web completo, IDS,
WAF, VPNs, filtro de conteúdo, SIEM e assistente de IA, com instalação
desatendida via ISO e menu de console de recuperação estilo pfSense.

> **Mundix Security 360** — Projeto de **Lucieliton Mundim** · +55 62 98438-4774
> Licença: uso **não comercial livre** e **comercial gratuito em appliances com
> até 50 usuários cada** — leia [LICENSE](LICENSE). É proibido remover os
> créditos do autor.

> ⚠️ **Estado do projeto: FASE INICIAL.** O Mundix Security 360 está em
> desenvolvimento ativo — bugs estão sendo reportados e corrigidos
> continuamente, e comportamentos podem mudar entre versões. **Use com
> cautela**: teste antes de implantar, mantenha backups e avalie o risco
> antes de colocar em produção crítica. Encontrou um problema? Abra uma
> [issue](https://github.com/k0k4/mundix360/issues).

---

## Sumário

- [O que é](#o-que-é)
- [Funcionalidades](#funcionalidades)
- [Arquitetura](#arquitetura)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Primeiro acesso](#primeiro-acesso)
- [Ferramentas de operação](#ferramentas-de-operação)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Gerando os artefatos (build)](#gerando-os-artefatos-build)
- [Notas de segurança](#notas-de-segurança)
- [Licença e créditos](#licença-e-créditos)

## O que é

O Mundix Security 360 transforma um computador comum (minipc, servidor ou VM)
com Ubuntu 24.04 LTS em um **firewall de borda completo**, administrado por um
painel web moderno e por um menu de console para situações de emergência. Ele
nasceu para ser prático: a ISO instala tudo de forma desatendida e, ao final do
primeiro boot, o appliance já está roteando, filtrando e com o painel no ar.

## Funcionalidades

**Rede e firewall**
- Firewall **nftables** com política restritiva por padrão e eventos de bloqueio visíveis no painel
- Zonas, interfaces, VLANs, rotas e aliases gerenciados pela UI (netplan por baixo)
- **Multi-WAN** com failover e **PPPoE** (discagem, status do link e IP negociado)
- DNS + DHCP (**dnsmasq**) com leases, reservas e resolvedor local
- Gestão de acesso remoto **SSH** com liberação integrada ao firewall

**Segurança**
- **IDS Suricata** (af-packet) com atualização automática de regras (timer)
- **WAF** Nginx + ModSecurity (OWASP CRS)
- **Filtro de conteúdo** por DNS (categorias, curingas, proteção contra DoH/DoT)
- **SIEM próprio**: ingestão de eventos em **ClickHouse**, triagem automática (timer) e **resposta ativa** (bloqueio de IPs)
- Threat intelligence e consulta de ameaças

**VPN**
- **WireGuard** server (road-warrior e site-to-site, com QR code)
- **OpenVPN** server com PKI por cliente, `.ovpn` sob demanda e CCD por cliente
- Cliente **OpenVPN** (importa `.ovpn` e disca) e cliente **Fortinet SSL-VPN** (openfortivpn)

**Gestão**
- Painel web (React + FastAPI) com visão geral, KPIs, logs e configuração completa
- **Assistente de IA** integrado (OpenRouter, opcional) com ferramentas de operação e geração de código assistida
- **Backup e restore** completos pela UI e por CLI (`mundix-restore.sh`)
- **Menu de console** estilo pfSense (`mundix-menu`) para recuperação quando a web não responde
- Atualização empacotada: pacote `.deb` e **repositório APT assinado (GPG)**

## Arquitetura

| Camada | Componentes |
|---|---|
| Base | Ubuntu Server 24.04 LTS, systemd, netplan |
| Firewall | nftables (`inet filter`, drop por padrão) |
| Serviços de rede | dnsmasq (DNS/DHCP), Suricata (IDS) |
| Borda web | Nginx (proxy reverso + TLS) + ModSecurity CRS |
| Painel | Frontend React (Refine/AntD) · Backend FastAPI (venv em `/opt/venv`) |
| Dados/SIEM | ClickHouse (localhost), Valkey (cache/filas) |
| IA | Agente próprio com ferramentas, via OpenRouter (chave opcional) |

Código em `/opt/mundix360`, configurações de estado em `/etc/mundix` e
`/var/lib/mundix`. As units systemd do projeto ficam em `installer/units/`.

## Requisitos

- **CPU x86_64 com AVX** (o ClickHouse atual exige AVX — verifique com `grep -o avx /proc/cpuinfo`)
- **2+ interfaces de rede** (WAN + LAN); mais NICs permitem DMZ/WAN2
- **4 GB RAM** mínimo (8 GB recomendado), **20 GB** de disco
- Ubuntu Server **24.04 LTS** (a ISO já inclui a base)

## Instalação

### Opção 1 — ISO autoinstall (recomendada)

1. Grave `installer/dist/mundix-appliance-<versão>-amd64.iso` num pendrive
   (`dd`, Rufus, Ventoy...) e dê boot no hardware de destino.
2. A instalação é **100% desatendida e APAGA O DISCO**: particiona, instala o
   Ubuntu e agenda o setup do Mundix para o primeiro boot.
3. No primeiro boot, o serviço `mundix-firstinstall` instala o appliance
   offline a partir do bundle embarcado (log em `/var/log/mundix-firstinstall.log`).

### Opção 2 — Bundle offline (Ubuntu 24.04 já instalado)

```bash
tar -xf mundix-appliance-<versão>.tar.zst -C /opt/
cd /opt/mundix-appliance/installer
sudo ./install.sh --offline
```

O bundle carrega todos os `.deb` necessários — **não precisa de internet**.

### Opção 3 — Repositório APT / pacote .deb

```bash
# Pacote único (dependências precisam estar acessíveis):
sudo apt install ./mundix360_<versão>_all.deb

# Ou repo APT autocontido e assinado (installer/dist/repo/):
sudo cp repo/mundix-repo.gpg /usr/share/keyrings/
echo "deb [signed-by=/usr/share/keyrings/mundix-repo.gpg] file:///caminho/para/repo ./" \
  | sudo tee /etc/apt/sources.list.d/mundix360.list
sudo apt update && sudo apt install mundix360
```

### Opção 4 — Instalador interativo a partir do código-fonte

```bash
git clone https://github.com/k0k4/mundix360.git /opt/mundix360
cd /opt/mundix360/installer
sudo ./install.sh            # modo online (baixa pacotes)
# flags úteis: --skip-apt (só reconfigura) | --upgrade | --yes (não interativo)
```

## Primeiro acesso

1. **LAN de gestão**: `192.168.1.1/24` na primeira NIC detectada, com DHCP
   ativo (faixa `.50–.150`). Plugue um notebook e acesse **https://192.168.1.1**.
2. **Painel**: usuário `admin` + **senha mestra** definida na instalação
   (no modo desatendido ela é gerada e impressa no log do first-install e no console).
3. **Console/SO**: a ISO cria o usuário local `mundix` com senha inicial
   `mundix360`, **expirada de fábrica** — o primeiro login exige definir senha nova.
4. Depois refine WAN/LAN, PPPoE, VPNs e regras pelo painel.

## Ferramentas de operação

| Comando | O que faz |
|---|---|
| `mundix-menu` | Menu de console estilo pfSense: status, rede, senha mestra, logs, restore, energia. Abre sozinho no login root do console local. |
| `mundix-export start\|stop\|status` | Sobe/derruba um servidor HTTP temporário (porta 8642) expondo `installer/dist/` para download, abrindo e fechando a regra no nftables automaticamente. |
| `scripts/ops/mundix360-healthcheck.sh` | Verifica serviços, portas e integridade do appliance. |
| `scripts/ops/mundix-restore.sh <backup.tar.gz>` | Restaura backup por CLI (config, estado e, opcionalmente, dados). |
| `scripts/reset-master-password.sh` | Reseta a senha mestra do painel. |

## Estrutura do repositório

```
configs/            Configurações-modelo (dnsmasq, nftables, akvorado, vector...)
dashboard/          Painel web — backend FastAPI (app/) + frontend React (src/)
installer/          Instalador, build de ISO/bundle/.deb/repo APT, units systemd
  ├── lib/          Fases da instalação (apt, app, python, frontend, config, first-boot)
  ├── iso/          Autoinstall (cloud-init) + serviço de primeira instalação
  ├── deb/          Metadados do pacote .deb (control, postinst, prerm, postrm)
  └── manifest.env  Manifesto: pacotes, units e caminhos (fonte única da verdade)
scripts/            SIEM (ingest/triage), active-response, ops, setup (menu/export)
dashboards/         Dashboards exportáveis (ex.: SIEM)
ARQUITETURA.md      Decisões de arquitetura
```

## Gerando os artefatos (build)

Todos os builds gravam em `installer/dist/`:

```bash
cd installer
sudo ./build-bundle.sh   # bundle offline (.tar.zst com todos os .deb)
sudo ./build-deb.sh      # pacote mundix360_<versão>_all.deb
sudo ./build-repo.sh     # repositório APT autocontido, assinado via GPG
sudo ./build-iso.sh      # ISO autoinstall (Ubuntu 24.04 + bundle embarcado)
```

A versão e a lista de pacotes/units vêm de `installer/manifest.env`.

## Notas de segurança

- A senha inicial do console (`mundix360`) **expira no primeiro boot** — troca obrigatória no 1º login.
- Chaves de host SSH e machine-id são **regenerados** no first-boot; nenhum segredo do ambiente de desenvolvimento vai nos artefatos.
- O painel escuta apenas na **LAN de gestão**; ClickHouse e Valkey escutam somente em `127.0.0.1`.
- O firewall aplica **drop por padrão** na entrada; liberações são explícitas.
- A integração de IA (OpenRouter) é **opcional** e desativada sem chave em `configs/openrouter.env`.
- Credenciais locais de serviço (ex.: usuário `akvorado` do ClickHouse) são restritas a localhost; ao expor serviços, troque-as.

## Contribuindo

Contribuições são bem-vindas! Leia [CONTRIBUTING.md](CONTRIBUTING.md) antes de
abrir issues e pull requests. Na primeira contribuição, o **CLA Assistant**
(bot) pedirá a assinatura do [Acordo de Licença de Contribuidor](CLA.md) —
basta comentar a frase indicada no próprio PR.

## Licença e créditos

Este projeto é **source-available** sob licença própria — veja [LICENSE](LICENSE):

- **Uso não comercial**: livre e gratuito, sem limite de appliances nem usuários.
- **Uso comercial**: gratuito em cada appliance que atenda **até 50 usuários**;
  appliances com mais de 50 usuários exigem licença comercial — fale com o autor.
- **Créditos obrigatórios**: é proibido remover ou ocultar a identificação
  *"Mundix Security 360 — Projeto de Lucieliton Mundim · +55 62 98438-4774"*
  do código, da documentação e das interfaces do software.

Componentes de terceiros (Ubuntu, Suricata, Nginx, ClickHouse etc.) seguem
suas próprias licenças.

---

**Autor:** Lucieliton Mundim · **Contato:** +55 62 98438-4774
**Repositório:** https://github.com/k0k4/mundix360
