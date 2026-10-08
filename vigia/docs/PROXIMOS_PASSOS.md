# Próximos passos — passagem de turno

**Atualizado em:** 08/10/2026, ~14h45 (horário de Brasília)
**Branch:** `main` — fases 1.5 e 2 mescladas pelo PR #1 (`f3f8cb1`); trabalhe a partir da `main`
**Referência de operação:** [`OPERACAO.md`](OPERACAO.md) · **Checklist geral:** [`ROADMAP.md`](ROADMAP.md)

## Onde paramos

### Feito e testado
- **Fase 1.5 (commitada):** câmera USB no homelab via mediamtx; Nitro faz a inferência;
  hub no homelab com Telegram, outbox/reenvio, heartbeat, "vigilância pausada/retomada",
  "câmera sem sinal", relatório mensal em PDF, retenção; serviço systemd na Nitro
  (sobe no boot, `linger` ativo).
- **Fase 2 — teste no quarto (commitada):**
  - InsightFace `buffalo_l` na GPU (~4 ms/rosto, pipeline a ~30–33 fps).
  - `IdentityTracker` (votação, zona cinzenta, herança na troca de ID) + `FaceWatcher`
    (porta = entrada, cama = zona sensível).
  - Galeria: fotos no hub (painel/CLI) → Nitro calcula embeddings → status ok/sem rosto.
  - Sirene no alto-falante do homelab (sobe o volume Master, que estava 0%/mudo) + sirene
    no navegador; botão Silenciar.
  - Painel web com login: vídeo anotado ao vivo, feed de eventos, cadastro de pessoas.
  - RTSP com senha (antes o vídeo ficava aberto na rede).
  - 72 testes passando, ruff ok.
  - Verificado ao vivo: vídeo anotado no painel, login, RTSP sem senha → 401, ciclo
    captura → Nitro processa → "sem rosto" → apagar (pessoa de teste já removida).

### Estado dos serviços ao encerrar
| Serviço | Estado | Observação |
|---|---|---|
| Nitro `vigia.service` | **parado** (`-c config/quarto.yaml`) | ainda habilitado: volta no próximo boot |
| Homelab `vigia-camera` | **parado** | ~0,8 núcleo do i3 (libx264) quando rodando |
| Homelab `vigia-hub` | **parado** | painel em :8090 quando rodando |

Parados pelo usuário ao encerrar (sem uso enquanto a câmera não está posicionada).
**Ao retomar, religue primeiro** (homelab antes da Nitro):
```bash
# parar (Nitro primeiro, para não sobrar evento na outbox)
systemctl --user stop vigia
ssh bispos@192.168.1.108 'cd ~/projetos/vigia && docker compose -f docker-compose.homelab.yml stop'

# religar (homelab primeiro: a Nitro precisa da câmera e do hub)
ssh bispos@192.168.1.108 'cd ~/projetos/vigia && docker compose -f docker-compose.homelab.yml start'
systemctl --user start vigia
```
> `stop` não desabilita: a Nitro volta sozinha no próximo boot (serviço habilitado), e os
> containers parados à mão **não** voltam sozinhos (`restart: unless-stopped`).

## O que falta — em ordem

### 1. Posicionar a câmera e desenhar as zonas (bloqueia o resto)
Hoje a câmera está numa mesa, apontada para cima: **não enquadra porta nem cama**, e as
zonas em `config/zones_quarto.yaml` são provisórias.
- Ideal: alto, num canto, pegando a porta de frente (rostos entrando) e a cama.
  Rostos a ≥ 40 px na imagem de 1280 px → até ~3 m nessa câmera em 720p.
- Desenhar: `systemctl --user stop vigia && vigia zones -c config/quarto.yaml`
  (Enter fecha o polígono → nome `porta`, tipo `entrance`; depois `cama`, `sensitive`;
  `s` salva) → `systemctl --user start vigia`.
- Conferir no painel (aba Ao vivo) se as zonas caíram no lugar certo.

### 2. Cadastrar as 4 pessoas
Painel → aba **Pessoas** → adicionar cada nome → **Capturar pela câmera** com a pessoa a
1–2 m olhando para a lente e virando o rosto devagar. Repetir 2–3 vezes (luz acesa/
apagada, com/sem óculos). Meta: **≥ 8 fotos "✓ ok" por pessoa**. Apagar as "✗ sem rosto".
Alternativa: `vigia faces add "Nome" pasta/` com fotos nítidas de frente.

### 3. Validar (critério de aceite)
- [ ] Cada pessoa entra pela porta → no vídeo vira o nome em verde em poucos segundos;
      no feed aparece "Fulano entrou no quarto" (sem Telegram, sem sirene).
- [ ] De costas / rosto coberto por 20 s → "Pessoa não identificada" (Telegram, sem sirene).
- [ ] Alguém **não cadastrado** (visita, ou foto de outra pessoa no celular) → "Pessoa
      desconhecida", sirene no homelab, Telegram com foto. **Avise a casa antes.**
- [ ] Desconhecido indo para a cama → alerta "zona sensível".
- [ ] "Testar alarme" no painel: a sirene toca no homelab? (ainda **não ouvida**)
- [ ] Silenciar pelo painel para a sirene.

### 4. Calibrar (depois de ~1 dia de uso)
- No feed, cada identificação mostra a similaridade. Família costuma ficar em 0,5–0,8.
- Se alguém da família fica muito tempo como `?`: cadastrar mais fotos naquele ângulo/luz
  antes de mexer nos limiares.
- Se um desconhecido chegou a receber nome: subir `match_threshold` (0,45 → 0,50).
- Se a família já disparou "desconhecido": subir `unknown_votes` (5 → 7) e/ou baixar
  `unknown_threshold` (0,30 → 0,25). Arquivo: `config/quarto.yaml`, depois
  `systemctl --user restart vigia`.

### 5. Pendências menores
- [ ] **WhatsApp:** criar a instância `vigia` na Evolution API (http://192.168.1.108:8081/manager),
      parear o número novo, preencher `EVOLUTION_API_KEY` e `WHATSAPP_TO` no `.env`
      (dos dois lados ou usar `--exclude .env` no rsync), `up -d hub`, testar com `/notify/test`.
- [ ] Reserva de DHCP para a Nitro (hoje 192.168.1.175 via Wi-Fi) — não é obrigatório.
- [ ] CPU do homelab: o ffmpeg da câmera usa ~0,8 núcleo (a imagem do mediamtx não tem
      driver VAAPI da Intel). Opções: baixar para 10 fps ou imagem própria com
      `intel-media-driver`.
- [ ] Botões no Telegram ("Conheço", "Falso alarme", "Cadastrar como…") — fase 2 do roadmap.
- [ ] Quando a câmera for para o portão: voltar a usar `config/config.yaml` (permanência)
      e decidir se o rosto roda lá também (suprimir permanência de conhecidos).

## Problemas conhecidos (cosméticos)
- O 1º heartbeat após ligar a Nitro manda `fps 0 / camera_ok false` (o YOLO ainda está
  carregando); o seguinte, 60 s depois, já vem certo.
- Aviso `StarletteDeprecationWarning (httpx2)` nos testes — não afeta nada.
- Reiniciar o hub com a Nitro desligada gera um "⏸️ Vigilância pausada" ~5 min depois.

## Para retomar com o Claude Code
Diga algo como: *"continue de `docs/PROXIMOS_PASSOS.md`"*. Primeiro passo útil:
`curl -s http://192.168.1.108:8090/health` e `systemctl --user status vigia` para ver o
estado atual antes de mexer.
