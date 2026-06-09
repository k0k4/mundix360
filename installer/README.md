# Mundix Security 360 — Instalador do Appliance

Implantação **profissional e reproduzível** do Mundix em hardware físico
(minipc, 1U, etc.), no estilo pfSense/OPNsense: você gera um **bundle offline**,
grava num pendrive, e instala sem depender da internet do cliente.

## Por que não clonar o disco?

Clonar carrega o estado do ambiente de desenvolvimento (chaves SSH, `machine-id`,
senha mestra, IP estático da WAN do dev, 1,5 GB de dados do ClickHouse) e quebra
em hardware diferente (os nomes de interface não batem). É **inseguro** (todas as
appliances teriam a mesma identidade) e **não-auditável**. Este instalador é
determinístico, adaptativo e dá **identidade única** a cada appliance.

## Perfil instalado — NÚCLEO

| Camada | Componentes |
|---|---|
| Firewall / rede | nftables, dnsmasq (DNS+DHCP+**filtro de conteúdo**), iproute2 |
| WAF / proxy | nginx + ModSecurity + OWASP CRS |
| IDS | Suricata |
| SIEM / dados | ClickHouse, valkey |
| Aplicação | API FastAPI (`mundix-*`), frontend Refine (pré-buildado) |
| IA | Mundix AI via OpenRouter (remota — só precisa da chave) |

Fora do perfil (não instalado): Kafka, Loki, Vector, VictoriaMetrics, Grafana,
Akvorado. Se a máquina já os tiver (imagem clonada), o instalador os **desabilita**.

## Estrutura

```
installer/
  manifest.env        # fonte única da verdade (pacotes, units, caminhos)
  install.sh          # orquestrador idempotente (offline por padrão)
  build-bundle.sh     # gera o pacote offline (rodar na build box)
  lib/                # fases: preflight, apt, mundix, python, frontend, config, services, firstboot
  units/              # units systemd canônicas do perfil núcleo
  config/             # nginx WAF, ModSecurity, nftables base, dnsmasq base
```

## Fluxo de implantação

### 1. Na build box (Ubuntu 24.04 com internet + Node)

```bash
cd /opt/mundix360/installer
sudo ./build-bundle.sh
# => dist/mundix-appliance-1.0.0.tar.zst  (código + .debs + wheels + dist)
```

### 2. Grave num pendrive e leve ao minipc

```bash
cp dist/mundix-appliance-1.0.0.tar.zst /media/pendrive/
```

### 3. No minipc (Ubuntu 24.04 Server recém-instalado)

```bash
tar --zstd -xf mundix-appliance-1.0.0.tar.zst
cd mundix-appliance/installer
sudo ./install.sh          # instalação 100% offline + assistente inicial
```

O **assistente inicial (first-boot)**:
- regenera chaves SSH e `machine-id` (identidade única);
- **detecta as interfaces de rede** reais (4, 6, as que houver — sem hardcode) e
  pergunta qual é a LAN de gestão;
- sobe a LAN em `192.168.1.1/24` com DHCP (plugue o notebook e acesse o painel);
- define a **senha mestra** e (opcional) a **chave OpenRouter** da IA;
- publica o painel em `https://192.168.1.1` e inicia os serviços.

### Modos úteis

```bash
sudo ./install.sh --dry-run      # mostra tudo que faria, sem alterar nada
sudo ./install.sh --online       # instala via apt da internet (dev/build)
sudo ./install.sh --yes          # não-interativo (gera senha mestra aleatória)
MUNDIX_MASTER_PASSWORD=... OPENROUTER_API_KEY=... sudo -E ./install.sh --yes
```

## Camada 2 (futuro) — ISO autoinstall

Este instalador é a base para uma **ISO de boot** (Ubuntu autoinstall/subiquity):
o pendrive particiona o disco, instala o Ubuntu base e roda `install.sh` no
primeiro boot — experiência "instala como pfSense". O `manifest.env` e as fases
já são reaproveitados como estão.
