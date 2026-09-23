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

## Fase 2 — Reconhecimento facial
- [ ] `docker compose --profile face up -d` (pgvector) + migração da tabela `faces`
- [ ] `InsightFaceEncoder` (implementa `FaceEncoder`) com `buffalo_l`, recorte a partir da caixa da pessoa
- [ ] Filtro de qualidade: rosto >= 80 px, nitidez (variância do Laplaciano), pose frontal
- [ ] `PgVectorGallery` (implementa `FaceGallery`), similaridade de cosseno
- [ ] CLI `vigia faces add <nome> <pasta>`, `vigia faces list`, `vigia faces remove <nome>`
- [ ] Associar identidade ao `track_id` (votação em N frames, não em 1)
- [ ] Pessoa conhecida -> suprime alertas de permanência dela; evento opcional "Fulano chegou"
- [ ] Bot do Telegram com botões inline: "Conheço", "Falso alarme", "Cadastrar como…"
- [ ] Calibrar limiar de similaridade com as suas fotos (curva de falsos aceites/rejeições)

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
