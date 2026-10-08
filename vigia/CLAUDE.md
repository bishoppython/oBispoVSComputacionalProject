# CLAUDE.md — Contexto do projeto Vigia

Este arquivo é lido automaticamente pelo Claude Code. Mantenha-o curto e atualizado.

## O que é
Sistema **local** de segurança por câmera que:
1. detecta pessoas paradas tempo demais em zonas (permanência / loitering);
2. detecta atos suspeitos (mexer na porta, mover a moto, violência);
3. reconhece rostos cadastrados;
4. envia alertas com foto para o Telegram.

Nada vai para a nuvem além das mensagens do Telegram/WhatsApp. Biometria é dado sensível (LGPD).

## Arquitetura (fluxo por frame)
```
VideoSource (thread, só o frame mais recente)
  -> resize_to_width
  -> Detector.track()  (YOLO11 + ByteTrack)  -> list[Detection]
  -> regras (rules/*)  -> Event
  -> EventEngine (cooldown por camera:kind:zona) -> sinks (Log, Snapshot, Hub | Telegram)
```
Implantação atual (fase 1.5): webcam USB no **homelab** -> `mediamtx` publica
`rtsp://192.168.1.108:8554/frente` -> **Nitro** roda `vigia run` (GPU) -> `HubSink`
-> **hub** no homelab (`vigia hub`) grava SQLite + fotos e envia Telegram/WhatsApp,
avisa quando a Nitro/câmera somem e manda o relatório mensal em PDF.
- `src/vigia/video/source.py` — webcam / arquivo / RTSP, reconexão automática.
- `src/vigia/detection/detector.py` — wrapper Ultralytics. `Detection.anchor` = pés da pessoa.
- `src/vigia/rules/` — lógica PURA e testável (sem OpenCV no núcleo; tempo injetado via `now`).
- `src/vigia/events/` — `Event`, `EventEngine`, sinks.
- `src/vigia/notify/telegram.py` — fila + thread; o loop de vídeo nunca espera rede.
- `src/vigia/notify/hub.py` — `HubSink`: outbox em disco + reenvio + heartbeat para o hub.
- `src/vigia/hub/` — serviço do homelab (FastAPI): `store` (SQLite), `channels`
  (Telegram, WhatsApp/Evolution API), `monitor` (presença, lógica pura), `report` (PDF).
- `src/vigia/face/contracts.py`, `src/vigia/vlm/contracts.py` — interfaces das fases 2 e 4.
- `src/vigia/pipeline.py` — orquestra tudo. Novas regras entram como `_xxx_step()`.

## Comandos
```bash
pip install -e ".[dev]"        # fase 2: pip install -e ".[dev,face]"
pytest -q                      # testes (não exigem GPU nem YOLO)
ruff check src tests && ruff format src tests
vigia probe                    # testa a fonte de vídeo
vigia zones                    # editor visual de zonas -> config/zones.yaml
vigia telegram-test            # valida o bot
vigia run [-s video.mp4] [--no-window] [-v]
vigia hub                      # serviço do homelab (normalmente via Docker, abaixo)
# homelab (~/projetos/vigia):
docker compose -f docker-compose.homelab.yml up -d --build
# Nitro: serviço systemd do usuário (sobe no boot)
bash deploy/nitro/install-service.sh    # journalctl --user -u vigia -f
```

## Convenções
- Código em inglês nos identificadores; **docstrings, comentários, logs e mensagens em PT-BR**.
- Type hints em tudo; `from __future__ import annotations`.
- Regras novas: classe pura em `rules/`, com testes em `tests/` usando tempo simulado.
- Nada bloqueante no loop principal (rede, VLM, banco -> thread/fila).
- Imports pesados (ultralytics, insightface) são tardios, dentro de `__init__`.
- Segredos só no `.env` (nunca no YAML nem em logs). Use `mask_source()` para URLs RTSP.
- Zonas sempre em coordenadas normalizadas 0..1.
- Toda alteração de comportamento vem com teste. Rode `pytest` e `ruff` antes de encerrar.

## Hardware
- Dev: notebook Ryzen 7 + RTX 4050 6 GB.
- Nó de inferência 24/7 previsto: máquina com GTX 1660 Super 6 GB.
- Nó de inferência atual: Nitro V15 (liga/desliga; o hub avisa "vigilância pausada").
- Homelab (sem GPU, sempre ligado, host em UTC): câmera USB (mediamtx), hub, banco.
  Não rodar inferência lá.
- Orçamento de VRAM: 6 GB -> YOLO11n/s + InsightFace + VLM 3B Q4 sob demanda.

## Câmeras
- Teste: webcam 4K (analisar em 1280 px de largura para simular a câmera final).
- Final: TP-Link VIGI C330I (3 MP, RTSP/ONVIF). Sub-stream para análise,
  stream principal só para snapshot/rosto (`camera.snapshot_source`).

## Como trabalhar
Siga `docs/ROADMAP.md`. Trabalhe uma fase por vez, marque os itens concluídos
no checklist e não implemente fases futuras sem pedido explícito.
