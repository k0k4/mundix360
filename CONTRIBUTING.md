# Contribuindo com o Mundix Security 360

Obrigado pelo interesse em colaborar! Este documento explica como contribuir
de forma útil para o projeto.

> ⚠️ O projeto está em **fase inicial**: bugs estão sendo reportados e
> corrigidos continuamente. Contribuições de correção e de robustez são
> especialmente bem-vindas.

## Como ajudar

- **Reportando bugs**: abra uma
  [issue](https://github.com/k0k4/mundix360/issues) descrevendo o problema,
  como reproduzir, versão do appliance e trechos de log relevantes
  (remova senhas, chaves e dados sensíveis antes de colar).
- **Sugerindo funcionalidades**: abra uma issue descrevendo o caso de uso
  antes de escrever código — evita trabalho perdido se a ideia não couber
  no roadmap.
- **Com código**: abra um *pull request* (veja abaixo).

## Pull requests

1. Faça um *fork* do repositório e crie um branch a partir de `main`.
2. Mantenha o PR **pequeno e focado** (uma correção/funcionalidade por PR).
3. Siga o estilo do código ao redor (bash com `set -euo pipefail`, Python
   com type hints onde já existem, frontend em TypeScript/React com AntD).
4. Descreva no PR: o que muda, por quê e como foi testado.
5. **Assine o CLA**: na primeira contribuição, o bot *CLA Assistant* pedirá
   a assinatura do [CLA.md](CLA.md) — basta comentar a frase indicada no
   próprio PR. Sem a assinatura, o merge não é feito.

## Regras básicas

- **Nunca** envie segredos (senhas, tokens, chaves privadas, certificados
  reais) em código, commits ou issues.
- Não remova nem altere os créditos do projeto (ver [LICENSE](LICENSE)).
- Mudanças no instalador (`installer/`) devem ser testadas em máquina limpa
  (VM) sempre que possível — descreva o teste no PR.
- O mantenedor revisa e aprova todo merge; a branch `main` é protegida.

## Segurança

Encontrou uma vulnerabilidade? **Não abra issue pública.** Contate o autor
diretamente: Lucieliton Mundim · +55 62 98438-4774.

## Licença das contribuições

Ao contribuir, você concorda com os termos do [CLA.md](CLA.md), que garante
ao autor do projeto o direito de distribuir sua contribuição, inclusive sob
licenças comerciais. Você mantém os direitos autorais sobre o que criar.
