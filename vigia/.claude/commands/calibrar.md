---
description: Ajuda a calibrar limiares a partir dos snapshots e logs
argument-hint: [zona]
---
Analise `config/config.yaml`, `config/zones.yaml` e os arquivos em `data/snapshots/`
(nomes contêm data, câmera, tipo e zona). Zona de interesse: $ARGUMENTS

Resuma quantos alertas houve por zona/horário, aponte prováveis falsos positivos e sugira
novos valores para `threshold_s`, `grace_period_s`, `cooldown_s` e `detector.conf`,
explicando o trade-off. Não altere nada sem eu confirmar.
