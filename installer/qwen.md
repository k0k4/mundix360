# TUTORIAL DEFINITIVO — Integrar **Qwen3.7‑Max** a um SaaS em Tempo Real (Pay‑as‑you‑go)

> **Objetivo:** Guia único, testado e à prova de falhas para qualquer IA/dev integrar o
> modelo **Qwen3.7‑Max** (Alibaba Cloud Model Studio / DashScope) num SaaS com respostas
> em **streaming (tempo real)**, usando o plano **pay‑as‑you‑go** (pague‑pelo‑uso).
>
> **Status:** ✅ **VALIDADO AO VIVO** em `2026-06-02` neste servidor (`/opt/k0k4-trader`).
> Todos os endpoints, o nome do modelo e o streaming foram testados com a chave real
> `DASHSCOPE_API_KEY` do `.env`. Resultados na §1.

---

## 0. TL;DR (leia isto primeiro)

| O que | Valor confirmado |
|---|---|
| **Provider** | Alibaba Cloud Model Studio (DashScope) — região **Internacional** |
| **Plano recomendado** | **Pay‑as‑you‑go** (`bailian-payg`) — cobra por token usado |
| **Base URL (OpenAI‑compatível, recomendado p/ SaaS)** | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |
| **Base URL (Anthropic‑compatível, alternativo)** | `https://dashscope-intl.aliyuncs.com/apps/anthropic/v1` |
| **Chave (header)** | `Authorization: Bearer $DASHSCOPE_API_KEY` (OpenAI) **ou** `x-api-key: $DASHSCOPE_API_KEY` (Anthropic) |
| **Modelo** | `qwen3.7-max` (estável) — snapshots: `qwen3.7-max-2026-05-20`, `qwen3.7-max-2026-05-17`, `qwen3.7-max-preview` |
| **Streaming** | ✅ Suportado (`"stream": true`) nos dois endpoints |
| **Pegadinha #1** | O modelo é **reasoning/thinking**: a resposta vem em `reasoning_content` (pensamento) **+** `content` (resposta final). **Mostre só `content` ao usuário.** |
| **Onde a chave vive** | `/opt/k0k4-trader/.env` → `DASHSCOPE_API_KEY=sk-...` |

**Regra de ouro:** para um SaaS em tempo real, use o **endpoint OpenAI‑compatível com
streaming** + qualquer SDK OpenAI (Python `openai`, JS `openai`). É o caminho com menos
fricção e mais ferramentas prontas.

---

## 1. Validação ao vivo (provas reais — `2026-06-02`)

Todos os testes abaixo retornaram **HTTP 200** com a chave real deste servidor:

| Teste | Endpoint | Resultado |
|---|---|---|
| Chat não‑stream | `/compatible-mode/v1/chat/completions` | ✅ 200 · ~2.6 s · `content:"OK"` |
| Chat não‑stream | `/apps/anthropic/v1/messages` | ✅ 200 · ~3.0 s · `text:"OK FUNCIONANDO"` |
| Streaming SSE | `/compatible-mode/v1/chat/completions` (`stream:true`) | ✅ chunks `chat.completion.chunk` |
| Streaming SSE | `/apps/anthropic/v1/messages` (`stream:true`) | ✅ eventos `content_block_delta` |
| Lista de modelos | `/compatible-mode/v1/models` | ✅ `qwen3.7-max` presente (145 modelos) |

> **Conclusão da validação:** o plano **pay‑as‑you‑go** (`DASHSCOPE_API_KEY`, base
> `dashscope-intl...`) está **100% funcional**. O material antigo
> (`openrouter.config.models.md`, `OPENCODE_INSTALL_GUIDE.md`) estava **correto na
> essência**, mas misturava 2 planos diferentes — ver §9 para a distinção exata.

### 1.1 Reproduza a validação (copie e cole)

```bash
cd /opt/k0k4-trader && set -a && source .env && set +a

curl -sS -X POST "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions" \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.7-max","max_tokens":30,"messages":[{"role":"user","content":"Responda apenas: OK"}]}' \
  -w "\n[HTTP %{http_code} | %{time_total}s]\n"
```

Esperado: `HTTP 200` e um JSON com `choices[0].message.content == "OK"`.

---

## 2. Pré‑requisitos

1. **Conta Alibaba Cloud Model Studio (Bailian)** com billing pay‑as‑you‑go ativo:
   - Console internacional: <https://bailian.console.aliyun.com> (Singapore region).
   - Ative **"Pay-as-you-go"** em *Billing*. Sem isto → erro `Arrearage`/`AccessDenied`.
2. **API Key** criada em *API-Key* no menu lateral → começa com `sk-...`.
3. A chave **já está** neste projeto: `/opt/k0k4-trader/.env` → `DASHSCOPE_API_KEY`.
4. `curl` para validar; e/ou Python 3.11+ / Node 18+ para integrar.

> ⚠️ **Nunca** commite a chave nem a cole em arquivos versionados. Sempre via env var.

---

## 3. Conceito crítico nº 1 — `reasoning_content` (thinking)

`qwen3.7-max` é um modelo de **raciocínio**. Toda resposta tem **duas partes**:

| Campo (OpenAI‑compat) | Campo (Anthropic‑compat) | O que é | Mostrar ao usuário? |
|---|---|---|---|
| `message.reasoning_content` | bloco `type:"thinking"` | cadeia de pensamento | ❌ **NÃO** (ou área separada "pensando…") |
| `message.content` | bloco `type:"text"` | resposta final | ✅ **SIM** |

No **streaming**, cada chunk traz `delta.reasoning_content` (durante o "pensar") e depois
`delta.content` (resposta final). **Acumule só `content`** para o texto que vai ao cliente.

> Esquecer isto = o usuário vê o "Thinking Process: 1. Analyze the request…" vazando na UI.
> Esta é a falha mais comum nesta integração. Trate **sempre**.

### 3.1 Controlar o esforço de raciocínio

No endpoint **Anthropic‑compat**, controle o orçamento de pensamento:
```json
"thinking": { "type": "enabled", "budgetTokens": 8192 }
```
Para latência menor (respostas curtas/UI), reduza `budgetTokens` (ex.: 1024) ou, se
disponível na sua conta, desabilite (`"type":"disabled"`). Menos thinking = mais rápido e
mais barato, porém menos "esperto" em tarefas complexas.

---

## 4. Integração Python (recomendado) — FastAPI + streaming SSE

Cenário típico de SaaS: backend FastAPI que faz proxy do streaming para o navegador via
**Server‑Sent Events**. Funciona com o SDK oficial `openai` apontado para o DashScope.

### 4.1 Instalar

```bash
pip install "openai>=1.40" fastapi "uvicorn[standard]"
# (neste repo: /opt/k0k4-trader/venv/bin/pip install ...)
```

### 4.2 Cliente mínimo (não‑stream)

```python
from __future__ import annotations
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

resp = client.chat.completions.create(
    model="qwen3.7-max",
    messages=[{"role": "user", "content": "Explique RSI em 1 frase."}],
    max_tokens=512,
)
msg = resp.choices[0].message
print("PENSAMENTO:", getattr(msg, "reasoning_content", None))  # debug only
print("RESPOSTA:", msg.content)                                 # vai ao usuário
print("TOKENS:", resp.usage.prompt_tokens, resp.usage.completion_tokens)
```

### 4.3 Backend SaaS em tempo real (FastAPI + SSE)

```python
from __future__ import annotations
import json
import os
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

app = FastAPI()

client = AsyncOpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

class ChatIn(BaseModel):
    prompt: str

@app.post("/chat/stream")
async def chat_stream(body: ChatIn) -> StreamingResponse:
    async def event_gen():
        stream = await client.chat.completions.create(
            model="qwen3.7-max",
            messages=[{"role": "user", "content": body.prompt}],
            max_tokens=1024,
            stream=True,
            stream_options={"include_usage": True},  # último chunk traz usage p/ billing
        )
        async for chunk in stream:
            if not chunk.choices:
                # chunk final de usage (quando include_usage=True)
                if chunk.usage:
                    yield _sse("usage", {
                        "prompt": chunk.usage.prompt_tokens,
                        "completion": chunk.usage.completion_tokens,
                    })
                continue
            delta = chunk.choices[0].delta
            # Pensamento -> canal separado (opcional, NUNCA misture com a resposta)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield _sse("thinking", {"text": reasoning})
            # Resposta final -> canal que a UI exibe
            if delta.content:
                yield _sse("token", {"text": delta.content})
        yield _sse("done", {})

    return StreamingResponse(event_gen(), media_type="text/event-stream")

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

Frontend (navegador) consumindo o SSE:

```javascript
const res = await fetch("/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ prompt: "Resuma a estratégia do bot" }),
});
const reader = res.body.getReader();
const decoder = new TextDecoder();
let answer = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  for (const block of decoder.decode(value).split("\n\n")) {
    if (!block.trim()) continue;
    const ev = block.match(/event: (.*)/)?.[1];
    const data = JSON.parse(block.match(/data: (.*)/s)[1]);
    if (ev === "token") { answer += data.text; render(answer); }      // mostra
    // if (ev === "thinking") showThinkingIndicator(data.text);       // opcional
    // if (ev === "usage") logBilling(data);                          // custo
  }
}
```

---

## 5. Integração Node / TypeScript (OpenAI SDK)

```bash
npm install openai
```

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.DASHSCOPE_API_KEY!,
  baseURL: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
});

const stream = await client.chat.completions.create({
  model: "qwen3.7-max",
  messages: [{ role: "user", content: "diga oi" }],
  max_tokens: 256,
  stream: true,
  stream_options: { include_usage: true },
});

let answer = "";
for await (const chunk of stream) {
  const delta = chunk.choices[0]?.delta as any;
  if (delta?.reasoning_content) {/* pensamento: ignore ou canal separado */}
  if (delta?.content) { answer += delta.content; process.stdout.write(delta.content); }
  if (chunk.usage) console.error("\n[usage]", chunk.usage);
}
```

> O `reasoning_content` **não** existe no type oficial do SDK OpenAI → acesse via
> `as any` (TS) ou `getattr(...)` (Python). É um campo extra do DashScope.

---

## 6. Alternativa: endpoint Anthropic‑compatível

Use só se já tem código baseado no SDK Anthropic. Para SaaS novo, prefira §4/§5.

```bash
curl -sS -X POST "https://dashscope-intl.aliyuncs.com/apps/anthropic/v1/messages" \
  -H "x-api-key: $DASHSCOPE_API_KEY" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "qwen3.7-max",
    "max_tokens": 256,
    "thinking": { "type": "enabled", "budgetTokens": 4096 },
    "messages": [{"role":"user","content":"diga oi"}]
  }'
```

Python (SDK Anthropic):
```python
import os
from anthropic import Anthropic
client = Anthropic(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope-intl.aliyuncs.com/apps/anthropic/v1",
)
with client.messages.stream(model="qwen3.7-max", max_tokens=512,
        messages=[{"role": "user", "content": "diga oi"}]) as stream:
    for text in stream.text_stream:   # text_stream já entrega só o texto final
        print(text, end="", flush=True)
```

Resposta não‑stream traz blocos: `[{type:"thinking",...}, {type:"text", text:"..."}]`.
Pegue só o bloco `type:"text"`.

---

## 7. Pay‑as‑you‑go — billing, custo e controle

- **Como cobra:** por **token** (entrada + saída). **`reasoning_content` conta como tokens
  de saída** (`completion_tokens_details.reasoning_tokens`). Thinking longo = conta maior.
- **Meça sempre:** use `stream_options={"include_usage": True}` (stream) ou `resp.usage`
  (não‑stream) e registre `prompt_tokens` / `completion_tokens` por requisição.
- **Controle de custo no código:**
  - `max_tokens` baixo para respostas de UI (ex.: 512–1024).
  - `budgetTokens` (thinking) menor quando não precisa de raciocínio profundo.
  - Cache/deduplicação de prompts repetidos no seu backend.
- **Preço exato:** varia por modelo/região e muda com o tempo — confira a tabela oficial
  antes de ir a produção:
  - Pricing: <https://www.alibabacloud.com/help/en/model-studio/models> (seção *Qwen*).
  - Billing/console: <https://bailian.console.aliyun.com>.
- **Limites/quota:** pay‑as‑you‑go tem rate‑limit por conta (RPM/TPM). Trate `429` com
  backoff exponencial (ver §8).

---

## 8. Erros e troubleshooting (validado)

| Sintoma | Causa provável | Correção |
|---|---|---|
| `401` / `InvalidApiKey` | chave errada/expirada ou header errado | OpenAI: `Authorization: Bearer ...`; Anthropic: `x-api-key: ...`. Cheque `grep DASHSCOPE_API_KEY .env` |
| `model not found` / `InvalidParameter` | nome do modelo errado | use exatamente `qwen3.7-max` (ou snapshot `qwen3.7-max-2026-05-20`) |
| `Arrearage` / `AccessDenied` billing | pay‑as‑you‑go não ativado / saldo | ative billing no console Bailian |
| `429 Throttling` | rate‑limit (RPM/TPM) | retry com backoff exponencial + jitter |
| UI mostra "Thinking Process…" | misturou `reasoning_content` no texto | exiba só `content`/bloco `text` (§3) |
| Stream "trava"/timeout | proxy sem flush ou timeout curto | desabilite buffering (Nginx: `proxy_buffering off`), timeout ≥ 120 s |
| Latência alta (3‑6 s) | thinking longo | reduza `budgetTokens`/`max_tokens` |
| Região errada | usou endpoint da China c/ chave intl | use **`dashscope-intl.aliyuncs.com`** (internacional) |

Retry recomendado (Python):
```python
import asyncio, random
from openai import APIStatusError

async def with_retry(coro_factory, tries=4):
    for i in range(tries):
        try:
            return await coro_factory()
        except APIStatusError as e:
            if e.status_code != 429 or i == tries - 1:
                raise
            await asyncio.sleep((2 ** i) + random.random())
```

---

## 9. Distinção dos planos (evite confusão dos materiais antigos)

Existem **dois** provedores Alibaba nos arquivos legados. **São planos diferentes**:

| Plano | Provider (opencode) | Base URL | Chave | Cobrança |
|---|---|---|---|---|
| **Pay‑as‑you‑go** ✅ (este tutorial) | `bailian-payg` | `https://dashscope-intl.aliyuncs.com/apps/anthropic/v1` (ou `/compatible-mode/v1`) | `DASHSCOPE_API_KEY` (`sk-...`) | por token usado |
| **Token Plan** (pré‑pago) | `bailian-token-plan` | `https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic/v1` | chave `sk-sp-...` separada | pacote de tokens pré‑comprado |

> O `opencode.jsonc` deste servidor usa **`bailian-token-plan`** como modelo padrão, mas o
> `bailian-payg` (pay‑as‑you‑go) está configurado e **foi o validado** aqui. Para SaaS em
> produção com cobrança por uso → **use `bailian-payg` / `DASHSCOPE_API_KEY`**.

### 9.1 Referência: config OpenCode que funciona (CLI, não SaaS)

`~/.config/opencode/opencode.jsonc` (trecho do provider pay‑as‑you‑go):
```jsonc
"bailian-payg": {
  "npm": "@ai-sdk/anthropic",
  "name": "Alibaba Cloud Model Studio (Pay-as-you-go)",
  "options": {
    "baseURL": "https://dashscope-intl.aliyuncs.com/apps/anthropic/v1",
    "apiKey": "sk-...DASHSCOPE..."
  },
  "models": { "qwen3.7-max": { "name": "Qwen3.7 Max",
    "options": { "thinking": { "type": "enabled", "budgetTokens": 8192 } } } }
}
```
Trocar de modelo no TUI: `/model bailian-payg/qwen3.7-max`.

---

## 10. Checklist final — para a IA executora não falhar

- [ ] Billing **pay‑as‑you‑go** ativo no console Bailian.
- [ ] `DASHSCOPE_API_KEY` presente no ambiente (`echo $DASHSCOPE_API_KEY` não vazio).
- [ ] Base URL = `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (internacional).
- [ ] Modelo = `qwen3.7-max` (string exata).
- [ ] Validação §1.1 retorna `HTTP 200` antes de codar qualquer coisa.
- [ ] Streaming com `stream:true` **e** `stream_options.include_usage` (p/ billing).
- [ ] UI exibe **só** `content`/bloco `text`; `reasoning_content` ignorado ou canal separado.
- [ ] `max_tokens` e `budgetTokens` ajustados ao caso (custo/latência).
- [ ] Retry/backoff para `429`; timeout ≥ 120 s; `proxy_buffering off` no Nginx.
- [ ] Chave **nunca** hardcoded/commitada — sempre via env var.
- [ ] `usage` (prompt/completion tokens) logado por requisição.

---

## 11. Referências

- DashScope (intl) — Compatibilidade OpenAI: <https://www.alibabacloud.com/help/en/model-studio/developer-reference/compatibility-of-openai-with-dashscope>
- Modelos & preços (Qwen): <https://www.alibabacloud.com/help/en/model-studio/models>
- Console Bailian (API‑Key, billing): <https://bailian.console.aliyun.com>
- OpenAI SDK: <https://github.com/openai/openai-python> · <https://github.com/openai/openai-node>
- OpenCode docs: <https://opencode.ai/docs>

---

**Última validação:** `2026-06-02` em `/opt/k0k4-trader` · chave real `DASHSCOPE_API_KEY` ·
todos os endpoints/streaming/modelo testados `HTTP 200`. ✅
