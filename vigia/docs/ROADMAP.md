# Roadmap do Vigia

Legenda: `[x]` feito · `[ ]` a fazer. Cada fase tem critério de aceite.

## Fase 0 — Fundação ✅
- [x] Estrutura do projeto, `pyproject.toml`, CLI (`typer`)
- [x] Config em YAML + segredos no `.env`
- [x] Testes unitários das regras e do motor de eventos

## Fase 1 — Permanência + Telegram (MVP)
- [x] `VideoSource` com webcam/arquivo/RTSP e reconexão
- [x] YOLO11 + ByteTrack
- [x] Zonas normalizadas + editor visual (`vigia zones`)
- [x] `LoiteringTracker` com período de graça
- [x] `EventEngine` com cooldown por zona
- [x] Telegram com foto anotada (thread + fila + retentativas)
- [ ] Gravar vídeos de teste (`data/videos/`) com: passagem normal, pessoa parada, oclusão
- [ ] Calibrar `threshold_s`, `grace_period_s` e `conf` com esses vídeos
- [x] Fallback de **ocupação de zona**: alertar quando a zona fica ocupada continuamente
      por qualquer pessoa > limiar (resolve troca de ID do tracker)
- [ ] Horário de funcionamento por zona (ex.: só alertar entre 22h e 6h)
- [ ] Salvar clipe curto (ex.: 5 s antes + 5 s depois) junto do snapshot

**Aceite:** pessoa parada 60 s no portão gera **um** alerta com foto; passagem normal não gera nada.

## Fase 1.5 — Nó de inferência + hub no homelab
Câmera USB no homelab (sempre ligado), inferência na Nitro V15 (liga/desliga),
alertas e relatórios saindo do homelab.
- [x] `mediamtx` + `ffmpeg` no homelab publicando a webcam em `rtsp://homelab:8554/frente`
- [x] `HubSink` na Nitro: fila em disco (`data/outbox/`), reenvio e heartbeat
- [x] `vigia hub` (FastAPI): recebe eventos, guarda em SQLite + fotos, evita duplicados
- [x] Telegram pelo hub (reusa `TelegramClient`)
- [x] WhatsApp via Evolution API (instância do número novo)
- [x] Aviso de "vigilância pausada/retomada" (Nitro) e "câmera sem sinal" (mediamtx)
- [x] Relatório mensal em PDF com fotos (dia 1º) + `POST /reports/monthly`
- [x] Retenção automática de fotos/eventos (`HUB_RETENTION_DAYS`)
- [ ] Parear o número novo na Evolution API e validar o envio
- [x] Iniciar `vigia run` automaticamente quando a Nitro liga (`deploy/nitro/install-service.sh`)

**Aceite:** com a Nitro ligada, um alerta chega no Telegram e no WhatsApp com foto; com a
Nitro desligada, chega um único aviso de "vigilância pausada"; no dia 1º chega o PDF do mês.

## Fase 2 — Reconhecimento facial (teste no quarto: `config/quarto.yaml`)
Porta = `entrance`, cama = `sensitive`. Família reconhecida = evento informativo;
rosto desconhecido confirmado = alerta crítico + sirene (homelab + painel);
sem rosto reconhecível por 20 s = alerta leve.
- [x] `InsightFaceEncoder` (implementa `FaceEncoder`) com `buffalo_l` na GPU, recorte da caixa da pessoa
- [x] Filtro de qualidade: tamanho mínimo, nitidez (variância do Laplaciano), pose frontal
- [x] Galeria: fotos no hub (painel/CLI), embeddings calculados e cacheados na Nitro
      (`MemoryGallery`; pgvector dispensado para poucas pessoas)
- [x] CLI `vigia faces add <nome> <pasta>`, `vigia faces list`, `vigia faces remove <nome>`
- [x] `IdentityTracker`: votação em N frames, zona cinzenta, herança de identidade na troca de ID
- [x] Evento "Fulano entrou no quarto" (porta) / "identificado"; desconhecido na cama = crítico
- [x] Alarme sonoro: sirene no alto-falante do homelab + no painel (botão Silenciar)
- [x] Painel web no hub: vídeo anotado ao vivo, feed de alertas/identificações, cadastro
      (captura pela câmera, upload, remoção), login por senha
- [x] RTSP do mediamtx com senha (o vídeo do quarto não fica aberto na rede)
- [ ] Posicionar a câmera e redesenhar `porta`/`cama` (`vigia zones -c config/quarto.yaml`)
- [ ] Cadastrar as 4 pessoas (8+ fotos boas cada) e validar: cada um reconhecido, visita = alarme
- [ ] Calibrar `match_threshold`/`unknown_threshold` com as similaridades vistas no painel
- [ ] Pessoa conhecida -> suprime alertas de permanência dela (quando voltar ao portão)
- [ ] Bot do Telegram com botões inline: "Conheço", "Falso alarme", "Cadastrar como…"

**Aceite:** pessoas cadastradas são reconhecidas a ~2–3 m de frente; desconhecidos nunca recebem nome.

## Fase 3 — Atos suspeitos por regras
- [ ] Trocar/adicionar `yolo11n-pose.pt` para keypoints
- [ ] Zona `door`: pulsos dentro da ROI da maçaneta por > X s -> alerta
- [ ] Zona `vehicle`: posição de referência da moto; pessoa sobreposta + deslocamento do
      centróide > limiar -> alerta **crítico**
- [ ] Pessoa mexendo na moto por muito tempo sem movê-la -> alerta de nível menor
- [ ] Testes com sequências simuladas de detecções (sem vídeo)

**Aceite:** simulação de puxar a moto gera alerta crítico em < 3 s.

## Fase 4 — VLM e violência
- [ ] `OllamaVerifier` (implementa `SceneVerifier`) com Qwen2.5-VL 3B, resposta em JSON
- [ ] Rodar VLM em thread, com timeout; se falhar, o alerta segue sem verificação
- [ ] Usar o veredito para rebaixar/cancelar alerta e escrever a legenda
- [ ] Heurística de violência: velocidade dos pulsos, proximidade entre duas pessoas,
      queda brusca (reaproveitar lógica do projeto de detecção de quedas)
- [ ] (opcional) Classificador de vídeo treinado no RWF-2000

**Aceite:** taxa de falsos alarmes cai de forma mensurável com o VLM ligado.

## Fase 5 — VIGI C330I e implantação
- [ ] Habilitar RTSP/ONVIF na câmera; confirmar URLs (`stream1` principal, `stream2` sub)
- [ ] `vigia probe` estável por 24 h (reconexão testada desligando a câmera)
- [ ] Usar `snapshot_source` (stream principal) para foto e rosto
- [ ] Bloquear a câmera de acessar a internet (regra no roteador/VLAN)
- [ ] Dockerfile com GPU (NVIDIA Container Toolkit) no nó da GTX 1660 Super
- [ ] Serviço `systemd` ou `restart: unless-stopped`; suporte a múltiplas câmeras

## Fase 6 — Observabilidade e manutenção
- [ ] Métricas Prometheus: fps, latência por etapa, eventos por tipo, reconexões
- [ ] Dashboard no Grafana do homelab
- [ ] Retenção automática de snapshots/clipes (ex.: 30 dias)
- [ ] Aviso de monitoramento no local; revisar o que a câmera enquadra (LGPD)
