# Mundix Security 360 — Instalador do Appliance

Há **dois caminhos** de instalação. Escolha conforme o cenário:

## ⭐ Caminho A — Instalação online (recomendado, mais robusto)

Você instala o **Ubuntu Server 24.04** no minipc (com internet) e roda **um único
comando**. É o caminho mais confiável: nada de ISO/bundle, tudo é baixado e
verificado na hora, e o painel é publicado em **todas as interfaces** (não depende
de adivinhar qual NIC é a LAN).

```bash
# 1) Instale o Ubuntu Server 24.04 e conecte à internet.
# 2) Copie/clone o repositório para a máquina, ex.:
git clone <repo> /opt/mundix360            # ou scp do diretório
cd /opt/mundix360
# 3) Rode o instalador:
sudo ./installer/mundix-install.sh         # interativo (pede a senha mestra)
# ou não-interativo:
sudo ./installer/mundix-install.sh --yes --openrouter-key sk-or-...
```

Ao final ele imprime as **portas realmente abertas** e a **URL do painel**. Acesse
`https://<IP-da-caixa>` (HTTP também funciona). Usuário `admin` + a senha mestra.

O instalador é **idempotente** (pode rodar de novo sem medo) e **auto-verificável**:
sobe cada serviço, confirma que ficou ativo, e se algo crítico falhar mostra o
diagnóstico e sai com erro. Log completo em `/var/log/mundix-install.log`.

Opções: `--yes`, `--master-password VALOR`, `--openrouter-key VALOR`,
`--regen-identity` (regenera chaves SSH/machine-id), `--skip-frontend`.

> **Por que o caminho offline/ISO falhava antes:** o `nftables-base` era hardcoded
> (`define WAN1 = ens18`…) e o firewall `policy drop` **não liberava as portas
> 80/443 do painel** — só SSH e DNS. Resultado: "nenhuma porta aberta". Isso foi
> corrigido: a base agora é **adaptativa** (sem NIC fixa) e libera 22/80/443
> sempre (anti-lockout), e o render em runtime (`fwmanage`) também mantém 80/443.

---

## Caminho B — Bundle offline + ISO autoinstalável (avançado)

Implantação **reproduzível** sem depender da internet do cliente, no estilo
pfSense/OPNsense: você gera um **bundle offline**, grava num pendrive, e instala.
Veja `build-bundle.sh` / `build-iso.sh` abaixo.

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
