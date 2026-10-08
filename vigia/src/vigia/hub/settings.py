"""Configuração do hub (tudo via .env / variáveis de ambiente)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class HubSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    vigia_hub_token: str

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # WhatsApp via Evolution API (instância pareada com o número novo)
    evolution_url: str | None = None  # ex.: http://192.168.1.108:8081
    evolution_api_key: str | None = None
    evolution_instance: str | None = None
    whatsapp_to: str | None = None  # número com DDI (5511999998888) ou JID de grupo (...@g.us)

    hub_data_dir: Path = Path("data/hub")
    hub_retention_days: int = 90
    hub_node_offline_after_s: float = 300.0  # sem heartbeat da Nitro -> "vigilância pausada"
    hub_notify_node_status: bool = True
    hub_mediamtx_api: str | None = None  # ex.: http://camera:9997 (monitora a câmera)
    hub_camera_path: str = "cam1"  # vídeo cru da webcam
    hub_live_path: str = "cam1-vigia"  # vídeo anotado publicado pela Nitro
    hub_rtsp_host: str = "camera:8554"
    vigia_rtsp_user: str | None = None
    vigia_rtsp_pass: str | None = None
    hub_camera_offline_after_s: float = 90.0
    hub_report_day: int = 1
    hub_report_hour: int = 8

    # Só eventos a partir desta severidade vão para Telegram/WhatsApp (o painel mostra tudo)
    hub_notify_min_severity: str = "alerta"
    hub_panel_password: str | None = None
    hub_alarm_sound: bool = True
    hub_alarm_device: str | None = None  # ex.: plughw:0,0 (padrão: dispositivo ALSA padrão)
    hub_alarm_duration_s: float = 30.0
    hub_alarm_volume: int | None = 100  # % aplicado ao mixer antes de tocar (None = não mexe)
    hub_alarm_mixer: str = "Master"
    hub_alarm_card: int = 0

    def rtsp_url(self, path: str) -> str:
        auth = f"{self.vigia_rtsp_user}:{self.vigia_rtsp_pass}@" if self.vigia_rtsp_user else ""
        return f"rtsp://{auth}{self.hub_rtsp_host}/{path}"

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def whatsapp_ready(self) -> bool:
        return bool(
            self.evolution_url
            and self.evolution_api_key
            and self.evolution_instance
            and self.whatsapp_to
        )
