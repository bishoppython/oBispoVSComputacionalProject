# Vigia

Sistema local de segurança com visão computacional: permanência em zonas, atos suspeitos
e reconhecimento facial, com alertas no Telegram.

## Início rápido
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
pytest -q
vigia probe                     # a webcam abre?
vigia zones                     # desenhe a zona do portão
vigia telegram-test             # o bot responde?
vigia run
```

### Criando o bot do Telegram
1. Fale com o **@BotFather** -> `/newbot` -> copie o token.
2. Mande qualquer mensagem para o seu bot.
3. Abra `https://api.telegram.org/bot<TOKEN>/getUpdates` e copie `chat.id`.

### Testando com vídeo gravado
```bash
vigia run -s data/videos/pessoa_parada.mp4
```

## Documentação
- `CLAUDE.md` — contexto para o Claude Code (arquitetura, convenções, comandos)
- `docs/ROADMAP.md` — fases, checklist e critérios de aceite
- `docs/FLUXO_DE_TRABALHO.md` — como usar VS Code + Claude Code neste projeto
