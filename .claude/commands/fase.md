---
description: Implementa os itens pendentes de uma fase do roadmap
argument-hint: <número da fase>
---
Leia `CLAUDE.md` e `docs/ROADMAP.md`. Foque APENAS na fase $ARGUMENTS.

1. Liste os itens `[ ]` pendentes dessa fase e proponha um plano curto (arquivos a criar/alterar,
   testes a escrever). Pare e espere minha aprovação.
2. Após aprovação, implemente um item por vez: código + testes em `tests/`.
3. Rode `pytest -q` e `ruff check src tests`. Corrija até passar.
4. Marque os itens concluídos no `docs/ROADMAP.md` e resuma o que mudou.
Não implemente itens de outras fases.
