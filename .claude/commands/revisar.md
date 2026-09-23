---
description: Revisa o diff atual contra as convenções do projeto
---
Rode `git diff` (e `git diff --staged`). Revise contra o `CLAUDE.md`:
- algo bloqueante no loop principal?
- segredos ou URLs RTSP com senha em código/log?
- regra nova sem teste, ou teste que depende de tempo real?
- mensagens/docstrings fora do PT-BR?
- imports pesados no topo de módulo?
Liste problemas por gravidade e sugira correções. Não altere arquivos sem eu pedir.
