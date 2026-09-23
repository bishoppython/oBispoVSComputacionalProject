# Fluxo de trabalho: VS Code + Claude Code

## Preparação (uma vez)
1. Abra a pasta no VS Code e aceite as extensões recomendadas (`.vscode/extensions.json`).
2. Selecione o interpretador `.venv` (Ctrl+Shift+P -> "Python: Select Interpreter").
3. No terminal integrado:
   ```bash
   git init && git add . && git commit -m "fase 0: fundação"
   claude
   ```
   O Claude Code lê o `CLAUDE.md` automaticamente.

## Ciclo por tarefa
1. **Você** escolhe um item do `docs/ROADMAP.md`.
2. No Claude Code: `/fase 1` (ou `/tarefa "fallback de ocupação de zona"`).
3. Peça o plano primeiro, revise, e só então autorize a implementação.
4. Rode e teste você mesmo pelo VS Code (F5 -> "vigia run").
5. `/revisar` antes do commit. Um commit por item do roadmap.

## Comandos personalizados (`.claude/commands/`)
| Comando | O que faz |
|---|---|
| `/fase N` | Implementa os itens pendentes da fase N, com plano e testes |
| `/tarefa "..."` | Implementa um item específico |
| `/revisar` | Revisa o diff atual contra as convenções do `CLAUDE.md` |
| `/calibrar` | Ajuda a ajustar limiares a partir dos logs/snapshots |

## Divisão sugerida
- **Você no VS Code:** gravar vídeos de teste, desenhar zonas, calibrar, depurar visualmente
  (breakpoints no `pipeline.py`), decidir limiares.
- **Claude Code no terminal:** implementar módulos contra os contratos (`face/`, `vlm/`),
  escrever testes, refatorar, Dockerfile, migrações.
