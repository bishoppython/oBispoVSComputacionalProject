#!/usr/bin/env bash
# Instala o `vigia run` como serviço systemd do usuário no nó de inferência (Nitro).
# Sobe no boot (linger), reinicia se cair e para com SIGINT (esvazia a outbox ao sair).
#   bash deploy/nitro/install-service.sh                      # config/config.yaml
#   bash deploy/nitro/install-service.sh config/quarto.yaml   # outro perfil
#   bash deploy/nitro/install-service.sh --remove             # remove
set -euo pipefail

UNIT=vigia.service
UNIT_DIR="$HOME/.config/systemd/user"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VIGIA="$PROJECT/.venv/bin/vigia"

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now "$UNIT" 2>/dev/null || true
  rm -f "$UNIT_DIR/$UNIT"
  systemctl --user daemon-reload
  echo "Serviço removido."
  exit 0
fi

CONFIG="${1:-config/config.yaml}"
[[ -f "$PROJECT/$CONFIG" ]] || { echo "Não achei $PROJECT/$CONFIG"; exit 1; }
[[ -x "$VIGIA" ]] || { echo "Não achei $VIGIA (rode: make install)"; exit 1; }
[[ -f "$PROJECT/.env" ]] || { echo "Falta $PROJECT/.env"; exit 1; }

mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/$UNIT" <<UNIT
[Unit]
Description=Vigia - inferência (câmera do homelab -> hub)
After=default.target

[Service]
Type=simple
WorkingDirectory=$PROJECT
ExecStart="$VIGIA" run --no-window -c "$CONFIG"
# Ctrl+C "de verdade": o pipeline fecha os sinks e tenta esvaziar a outbox.
KillSignal=SIGINT
TimeoutStopSec=30
Restart=on-failure
RestartSec=15
Environment=PYTHONUNBUFFERED=1
Environment=COLUMNS=160

[Install]
WantedBy=default.target
UNIT

# Linger: o serviço sobe no boot, mesmo antes de fazer login.
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
systemctl --user restart "$UNIT"   # aplica mudanças se já estava rodando
echo "Serviço ativo com $CONFIG. Logs: journalctl --user -u vigia -f"
