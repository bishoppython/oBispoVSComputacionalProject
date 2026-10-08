# Operação do Vigia (homelab + Nitro)

Referência de como o sistema está montado e como operar. Estado e pendências da
sessão ficam em [`PROXIMOS_PASSOS.md`](PROXIMOS_PASSOS.md).

## 1. Arquitetura

```
                       HOMELAB 192.168.1.108 (Lenovo 80YF, i3-6006U, sempre ligado)
 EMEET S600 (USB) ──► vigia-camera (mediamtx 1.21.1 + ffmpeg)
                         rtsp://…:8554/cam1        vídeo cru, H.264 1280x720 15 fps (com senha)
                         rtsp://…:8554/cam1-vigia  vídeo ANOTADO, publicado pela Nitro
                         API :9997 (só rede interna do Docker)
                      vigia-hub (FastAPI, :8090)
                         painel web · SQLite + fotos · Telegram/WhatsApp · sirene (ALSA)
                         relatório mensal PDF · retenção · avisos de Nitro/câmera fora
            ▲  eventos + heartbeat (HTTP, token)        │ RTSP cam1 (com senha)
            │  galeria (fotos de cadastro)              ▼
                       NITRO V15 192.168.1.175 (Wi-Fi, RTX 4050, liga/desliga)
                      vigia.service (systemd --user, sobe no boot)
                         YOLO11n + ByteTrack → regras → InsightFace → IdentityTracker
                         → HubSink (outbox) · LivePublisher (NVENC) → cam1-vigia
```

Fluxo de um alerta: frame (Nitro) → `FaceWatcher` decide "desconhecido" → `EventEngine`
(cooldown) → `HubSink` grava em `data/outbox/` e envia → hub grava (SQLite + foto),
dispara a sirene se `meta.alarm`, envia ao Telegram se severidade ≥ `alerta` →
painel mostra em até 3 s.

## 2. Onde está cada coisa

| Máquina | Caminho | O quê |
|---|---|---|
| Nitro | `~/Documentos/03 - Projetos/Visão Computacional/vigia` | repositório, `.venv`, `.env` |
| Nitro | `~/.config/systemd/user/vigia.service` | serviço (gerado por `deploy/nitro/install-service.sh`) |
| Nitro | `vigia/data/faces/embeddings.npz` | embeddings dos rostos (biometria; fora do git) |
| Nitro | `vigia/data/outbox/` | eventos aguardando o hub |
| Nitro | `~/.insightface/models/buffalo_l` | modelo de rosto (~280 MB, baixado no 1º uso) |
| Homelab | `~/projetos/vigia` | cópia do repositório (via rsync) + `.env` |
| Homelab | `~/projetos/vigia/data/hub/vigia.db` | eventos, pessoas, fotos de cadastro (SQLite) |
| Homelab | `~/projetos/vigia/data/hub/photos/AAAA-MM/` | fotos dos alertas (retenção 90 dias) |
| Homelab | `~/projetos/vigia/data/hub/faces/<id>/` | fotos de cadastro (biometria) |

Perfis de configuração (Nitro):
- `config/quarto.yaml` + `config/zones_quarto.yaml` — **em uso**: reconhecimento facial,
  vídeo ao vivo, zonas `porta` (entrance) e `cama` (sensitive).
- `config/config.yaml` + `config/zones.yaml` — perfil do portão (permanência), para depois.

## 3. Segredos (`.env`, nunca no git)

O mesmo `.env` é usado nos dois lados (o rsync copia). Gerados nesta sessão:

| Variável | Uso |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | envio pelo hub |
| `VIGIA_HUB_TOKEN` | Nitro ↔ hub (Bearer) e assinatura do cookie do painel |
| `VIGIA_RTSP_USER` / `VIGIA_RTSP_PASS` | leitura do RTSP e publicação do `cam1-vigia` |
| `VIGIA_CAMERA_SOURCE` | Nitro: `rtsp://vigia:SENHA@192.168.1.108:8554/cam1` |
| `VIGIA_LIVE_URL` | Nitro: `rtsp://vigia:SENHA@192.168.1.108:8554/cam1-vigia` |
| `HUB_PANEL_PASSWORD` | **senha do painel** (veja com `grep HUB_PANEL_PASSWORD .env`) |
| `VIGIA_CAMERA_DEVICE` | homelab: `/dev/v4l/by-id/usb-EMEET_…-video-index0` |
| `EVOLUTION_*`, `WHATSAPP_TO` | WhatsApp — **ainda vazio** (`EVOLUTION_API_KEY`, `WHATSAPP_TO`) |

Opcionais do hub e valores padrão: veja `.env.example` (`HUB_RETENTION_DAYS`,
`HUB_NOTIFY_MIN_SEVERITY`, `HUB_ALARM_VOLUME`, `HUB_ALARM_DURATION_S`…).

## 4. Comandos do dia a dia

**Nitro**
```bash
cd "~/Documentos/03 - Projetos/Visão Computacional/vigia" && source .venv/bin/activate
journalctl --user -u vigia -f                       # logs ao vivo
systemctl --user restart vigia                      # após mudar config/zonas
systemctl --user stop vigia                         # pausar (hub avisa em ~5 min)
bash deploy/nitro/install-service.sh config/quarto.yaml   # (re)instalar com um perfil
vigia zones -c config/quarto.yaml                   # desenhar zonas (abre janela)
vigia faces add "Nome" pasta/ | vigia faces list | vigia faces remove "Nome"
pytest -q && ruff check src tests && ruff format src tests
```

**Homelab** (`ssh bispos@192.168.1.108`, depois `cd ~/projetos/vigia`)
```bash
docker compose -f docker-compose.homelab.yml ps
docker logs -f vigia-hub          # eventos, envios, alarme
docker logs -f vigia-camera       # mediamtx/ffmpeg
docker compose -f docker-compose.homelab.yml up -d --build      # após atualizar o código
docker compose -f docker-compose.homelab.yml restart camera     # câmera USB reconectada
```

**Atualizar o homelab a partir da Nitro** (o `.env` vai junto; não tem nada só do homelab nele hoje)
```bash
rsync -a --delete --exclude .venv --exclude data --exclude '__pycache__' \
  --exclude .pytest_cache --exclude .ruff_cache --exclude '*.pt' --exclude .claude \
  --exclude .vscode ./ bispos@192.168.1.108:projetos/vigia/
ssh bispos@192.168.1.108 'cd ~/projetos/vigia && docker compose -f docker-compose.homelab.yml up -d --build'
```
> Quando preencher o WhatsApp **só no homelab**, passe a usar `--exclude .env` no rsync
> (ou preencha nos dois lados) para não sobrescrever.

**Testes rápidos**
```bash
set -a; . ./.env; set +a
curl http://192.168.1.108:8090/health
curl -X POST -H "Authorization: Bearer $VIGIA_HUB_TOKEN" http://192.168.1.108:8090/notify/test
curl -X POST -H "Authorization: Bearer $VIGIA_HUB_TOKEN" "http://192.168.1.108:8090/reports/monthly?month=2026-10"
```

## 5. Painel (http://192.168.1.108:8090)

- **Ao vivo:** "Automático" mostra o vídeo anotado quando a Nitro está online e a câmera
  crua quando não está. Cores: verde = conhecido (com similaridade), amarelo `?` =
  identificando, vermelho `DESCONHECIDO`; azul = porta, rosa = cama.
- **Eventos:** filtros Todos / Alertas / Identificações; clique na foto para ampliar.
- **Alarme:** faixa vermelha + **Silenciar**. "🔕 Ativar som" liga a sirene também no
  navegador (exige um clique). **Testar alarme** toca no homelab (alto!).
- **Pessoas:** adicionar; **Capturar pela câmera** (8 fotos em ~5 s); **Enviar fotos**;
  apagar foto (×) ou pessoa. Status: ✓ ok (na galeria), ⏳ pendente (Nitro desligada ou
  ainda não sincronizou — até 30 s), ✗ sem rosto (não serviu).
- Assistir ao vivo custa ~20–25% de CPU no homelab; o relay fecha 20 s após fechar a aba.

API (cookie do painel ou `Authorization: Bearer`): `GET /api/state`, `GET /api/events`,
`GET /api/live.mjpg?src=vigia|raw`, `POST /api/alarm/stop|test`, `GET|POST /api/people`,
`DELETE /api/people/{id}`, `POST /api/people/{id}/photos|capture`,
`GET /api/faces/manifest`, `GET|DELETE /api/faces/photos/{id}`.

## 6. Como a decisão de identidade funciona

Por pessoa rastreada (track do ByteTrack), em `rules/identity.py`:

1. A cada 0,3 s (pendente) ou 2 s (já decidido), recorta a cabeça e roda o InsightFace.
2. Rosto só vota se passar no filtro (`face/quality.py`): ≥ `min_face_px` (40), confiança
   ≥ 0,6, nitidez (Laplaciano ≥ 30) e de frente (`min_frontal` 0,3).
3. Similaridade com a galeria (cosseno, melhor foto de cada pessoa):
   - ≥ `match_threshold` (0,45) → voto no nome;
   - < `unknown_threshold` (0,30) → voto "desconhecido";
   - entre os dois → **não vota** (zona cinzenta).
4. Janela das últimas 8 leituras: 3 do mesmo nome → **conhecido**; 5 "desconhecido" e
   nenhum acerto → **desconhecido** (crítico + sirene). Empate mantém o nome atual.
5. Pendente por 20 s (`unidentified_after_s`) → "pessoa não identificada" (sem sirene).
6. Track perdido por > 3 s e outro aparecendo no mesmo lugar (IoU ≥ 0,3, em até 10 s)
   → herda a identidade, sem novo alerta.
7. **Galeria vazia → reconhecimento pausado** (nunca alarma todo mundo).

Eventos e cooldowns (`config/quarto.yaml`):

| kind | Severidade | Sirene | Telegram | Cooldown |
|---|---|---|---|---|
| `face_known` ("Ana entrou no quarto") | info | não | não (só painel) | 30 min por pessoa |
| `face_unknown` | crítico | sim | sim | 60 s |
| `sensitive_zone` (desconhecido entrou na cama) | crítico | sim | sim | 60 s |
| `unidentified` | alerta | não | sim | 5 min |

## 7. Avisos automáticos do hub

- **Nitro sem heartbeat por 5 min** → "⏸️ Vigilância pausada"; ao voltar → "▶️ retomada".
  (Reiniciar o hub com a Nitro desligada gera o aviso de pausa ~5 min depois — normal.)
- **Câmera sem vídeo no mediamtx por 90 s** → "📷❌ Câmera sem sinal"; ao voltar → aviso.
- **Relatório mensal** (PDF com fotos, só alertas; identificações ficam fora) no dia 1º
  às 8h, no Telegram/WhatsApp.
- **Retenção:** fotos e eventos com mais de 90 dias são apagados diariamente.
  Fotos de cadastro **não** expiram (apagar pelo painel).

## 8. Problemas comuns

| Sintoma | Causa provável / o que fazer |
|---|---|
| Painel "Nitro desligada" com a Nitro ligada | `journalctl --user -u vigia -n 50`; RTSP com senha errada → conferir `VIGIA_CAMERA_SOURCE` |
| `401 Unauthorized` no RTSP | senha do `.env` diferente nos dois lados → rsync do `.env` + `up -d` |
| "Câmera sem sinal" | USB desconectado/trocado de porta → `docker compose … restart camera` |
| Família vira "?" por muito tempo | rosto pequeno/de lado; cadastrar mais fotos nesse ângulo/luz; ver similaridade no painel e baixar `match_threshold` com cuidado |
| Sirene não toca | `docker logs vigia-hub \| grep -i aplay`; volume: `HUB_ALARM_VOLUME`, mixer `HUB_ALARM_MIXER` |
| Fotos de cadastro ficam ⏳ | Nitro desligada ou serviço parado; sincroniza a cada 30 s |
| `CUDAExecutionProvider` ausente no log | `pip uninstall -y onnxruntime && pip install --force-reinstall --no-deps onnxruntime-gpu` |

## 9. Privacidade (LGPD)

- Fotos de cadastro só no homelab; embeddings só na Nitro (`data/faces/`). Apagar uma
  pessoa no painel apaga as fotos no homelab e, na sincronização seguinte (≤ 30 s), o
  embedding na Nitro.
- Vídeo do quarto: RTSP exige senha; painel exige login. Nada é exposto à internet
  (não roteie a porta 8090/8554 no ngrok/roteador).
- Biometria de menores: uso doméstico, com consentimento da família.
- Modelos InsightFace `buffalo_l`: licença **não comercial** (ok para uso pessoal).
