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

## Homelab (câmera + hub) e Nitro (inferência)
```bash
# no homelab, em ~/projetos/vigia (com o .env preenchido)
docker compose -f docker-compose.homelab.yml up -d --build
curl http://192.168.1.108:8090/health

# na Nitro (.env com VIGIA_HUB_TOKEN e VIGIA_CAMERA_SOURCE=rtsp://192.168.1.108:8554/frente)
vigia run --no-window                      # manual, ou como serviço (sobe no boot):
bash deploy/nitro/install-service.sh       # logs: journalctl --user -u vigia -f
```
Rotas do hub (com `Authorization: Bearer $VIGIA_HUB_TOKEN`): `POST /notify/test`,
`POST /reports/monthly?month=AAAA-MM`. Sem token: `GET /health`.

## Documentação
- `CLAUDE.md` — contexto para o Claude Code (arquitetura, convenções, comandos)
- `docs/ROADMAP.md` — fases, checklist e critérios de aceite
- `docs/FLUXO_DE_TRABALHO.md` — como usar VS Code + Claude Code neste projeto
