# Tutorial de Implantação — Mundix Security 360

Guia prático para colocar o Mundix Security 360 em produção num **Ubuntu Server
24.04** (minipc, 1U, VM, etc.). Este é o **caminho online recomendado**: você
instala o Ubuntu, traz o código para a máquina e roda **um único comando**.

> ⏱️ Tempo estimado: 10–20 min (depende da internet e do hardware).

---

## 0. Pré-requisitos

- **Ubuntu Server 24.04 LTS** já instalado no equipamento.
- **Acesso à internet** na máquina (o instalador baixa pacotes).
- Usuário com **sudo** (ou root).
- **Recomendado:** ≥ 4 GB RAM, ≥ 20 GB de disco livre, CPU x86-64 (amd64).
- Pelo menos **1 interface de rede** já com IP (para você acessar a máquina).
  Quantas interfaces o hardware tiver (2, 4, 6…), o Mundix detecta sozinho — não
  há nada hardcoded.

Confira o sistema:

```bash
. /etc/os-release && echo "$ID $VERSION_ID"   # esperado: ubuntu 24.04
ping -c1 8.8.8.8                               # internet OK?
ip -4 addr show scope global                   # qual IP a máquina tem?
```

---

## 1. Trazer o código para o servidor

Escolha **uma** das opções abaixo.

### Opção A — `git clone` (se o repositório já estiver no GitHub) ⭐

O repositório `k0k4/mundix360` é **privado**, então use um Personal Access Token
(PAT) com permissão de `repo`:

```bash
sudo apt-get update && sudo apt-get install -y git
# Cole o token quando o git pedir a senha (usuário = seu login do GitHub):
sudo git clone https://github.com/k0k4/mundix360.git /opt/mundix360
```

> Dica: para não digitar o token toda vez, depois do clone rode
> `sudo git -C /opt/mundix360 config credential.helper store`.

### Opção B — Copiar pela rede (scp/rsync) a partir da máquina de origem

Na **máquina onde o código está hoje** (ex.: a estação de desenvolvimento):

```bash
# Substitua USUARIO e IP_DO_SERVIDOR pelos do minipc:
rsync -avz --exclude '.git' --exclude 'node_modules' \
  --exclude 'installer/bundle' --exclude 'installer/dist' \
  /opt/mundix360/ USUARIO@IP_DO_SERVIDOR:/tmp/mundix360/
# No servidor, mova para o lugar definitivo:
ssh USUARIO@IP_DO_SERVIDOR 'sudo mkdir -p /opt && sudo mv /tmp/mundix360 /opt/mundix360'
```

### Opção C — Pendrive

Copie a pasta do projeto para um pendrive, plugue no servidor e:

```bash
sudo mkdir -p /opt/mundix360
sudo cp -a /media/$USER/SEU_PENDRIVE/mundix360/. /opt/mundix360/
```

> O instalador funciona rodando de **qualquer caminho**. Se o código não estiver
> em `/opt/mundix360`, ele copia para lá automaticamente.

---

## 2. Rodar o instalador

O instalador é **idempotente** (pode rodar de novo sem medo), faz tudo de ponta a
ponta e **verifica cada serviço** ao final.

### Modo interativo (recomendado na 1ª vez)

```bash
cd /opt/mundix360
sudo ./installer/mundix-install.sh
```

Ele vai pedir a **senha mestra** do painel (a que você usará no login `admin`).

### Modo não-interativo (automação)

```bash
cd /opt/mundix360
sudo ./installer/mundix-install.sh --yes \
  --master-password 'SUA_SENHA_FORTE' \
  --openrouter-key 'sk-or-...'          # opcional, ativa a IA
```

Com `--yes` e **sem** `--master-password`, uma senha aleatória é gerada e
**impressa no relatório final** (anote-a).

### O que o instalador faz

1. Instala os pacotes (firewall, DNS/DHCP, WAF, IDS, SIEM, Python, Node).
2. Posiciona o código em `/opt/mundix360` e cria o ambiente Python (`/opt/venv`).
3. Builda o painel (SPA).
4. Aplica as configs base — **firewall adaptativo** (sem interface hardcoded) que
   já libera as portas de gestão **22/80/443** (anti-lockout).
5. **Publica o painel em todas as interfaces** (`0.0.0.0:80/443`) — você acessa
   por qualquer IP da máquina, sem precisar adivinhar qual placa é a LAN.
6. Sobe e **verifica** cada serviço; se algo crítico falhar, mostra o diagnóstico.
7. Define a senha mestra e imprime o **relatório final** com as portas abertas.

### Opções úteis

| Opção | Para quê |
|---|---|
| `--yes`, `-y` | Não-interativo (gera senha mestra aleatória). |
| `--master-password VALOR` | Define a senha mestra. |
| `--openrouter-key VALOR` | Grava a chave da IA (OpenRouter). |
| `--regen-identity` | Regenera chaves SSH de host + machine-id (para clonar como appliance). |
| `--skip-frontend` | Pula o build do SPA (usa `dist/` existente). |

---

## 3. Acessar o painel

No relatório final o instalador mostra os **IPs da máquina** e a URL. Abra no
navegador (de um PC na mesma rede):

```
https://<IP-do-servidor>
```

- Aceite o aviso de certificado (é um certificado self-signed gerado na hora).
- Também funciona em `http://<IP-do-servidor>`.
- **Usuário:** `admin`
- **Senha:** a senha mestra que você definiu (ou a gerada no relatório).

---

## 4. Configuração inicial no painel

Depois de logar, configure a rede do firewall (é aqui que o produto ganha forma):

1. **Redes → Interfaces:** o sistema lista as interfaces físicas detectadas.
   Defina o papel de cada uma (WAN, LAN, DMZ, IoT…), renomeie, habilite/desabilite
   e crie **VLANs** (nome + número) conforme sua topologia.
2. **Redes → Zonas:** agrupe interfaces em zonas e ajuste as políticas inter-zona.
3. **Multi-WAN** (se tiver 2+ links): configure failover/load-balance.
4. **Firewall:** regras, NAT/port-forward, aliases, etc.
5. **Filtro de conteúdo:** categorias bloqueadas e visibilidade em tempo real.
6. **IA:** se informou a chave OpenRouter, o assistente já fica ativo.

> O firewall tem **anti-lockout**: as portas de gestão (22/80/443) permanecem
> abertas mesmo com política `drop`, então você não se tranca para fora.

---

## 5. Verificação e diagnóstico

Se algo não responder, rode na máquina:

```bash
# Estado dos serviços principais:
systemctl status mundix-dashboard-api.service nginx.service dnsmasq.service \
  nftables.service clickhouse-server.service valkey-server.service --no-pager

# Portas em escuta (esperado: 22, 53, 80, 443, e 8100/8099 internos):
sudo ss -tlnp | grep -E ':(22|53|80|443|8100|8099)\b'

# O painel responde localmente?
curl -k -I https://127.0.0.1/

# Log completo da instalação:
sudo less /var/log/mundix-install.log

# Logs de um serviço específico:
journalctl -u mundix-dashboard-api.service --no-pager -n 50
```

**Se a senha mestra falhou** (ou para redefinir):

```bash
cd /opt/mundix360/dashboard/backend
sudo /opt/venv/bin/python -m app.admin reset-master-password
```

**Reinstalar / reparar:** basta rodar o instalador de novo (é idempotente):

```bash
cd /opt/mundix360 && sudo ./installer/mundix-install.sh --yes
```

---

## 6. Atualizar o sistema depois

```bash
cd /opt/mundix360
sudo git pull                       # se veio por git (Opção A)
sudo ./installer/mundix-install.sh  # reaplica configs, rebuilda o SPA, reinicia
```

---

## Resumo rápido (TL;DR)

```bash
# No Ubuntu Server 24.04, com internet:
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/k0k4/mundix360.git /opt/mundix360   # (PAT no prompt)
cd /opt/mundix360
sudo ./installer/mundix-install.sh
# Acesse https://<IP-do-servidor>  (admin + senha mestra)
```

Dúvidas ou erro na instalação? O `/var/log/mundix-install.log` tem o detalhe
completo de cada passo.
