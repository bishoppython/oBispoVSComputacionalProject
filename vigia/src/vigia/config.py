"""Carregamento de configuração (config.yaml) e segredos (.env)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

Source = int | str


def parse_source(value: Source | None) -> Source | None:
    """'0' vira 0 (webcam); o resto (RTSP, arquivo) continua string."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


class CameraCfg(BaseModel):
    id: str = "cam0"
    source: Source = 0
    snapshot_source: Source | None = None
    width: int = 1280
    reconnect_seconds: float = 5.0


class DetectorCfg(BaseModel):
    model: str = "yolo11n.pt"
    conf: float = 0.4
    device: int | str = "cpu"
    imgsz: int = 640
    tracker: str = "bytetrack.yaml"
    classes: list[str] = ["person", "motorcycle"]


class LoiteringCfg(BaseModel):
    default_threshold_s: float = 90.0
    grace_period_s: float = 4.0
    # Fallback: alerta se a zona fica ocupada por qualquer pessoa além do limiar
    # (resolve troca de ID do tracker). Usa os mesmos limiares e período de graça.
    occupancy_fallback: bool = True


class EventsCfg(BaseModel):
    cooldown_s: float = 120.0
    # Exceções por tipo, ex.: {face_known: 1800} -> "Ana identificada" no máximo a cada 30 min
    cooldown_by_kind: dict[str, float] = {}
    snapshot_dir: Path = Path("data/snapshots")


class TelegramCfg(BaseModel):
    enabled: bool = True


class FaceCfg(BaseModel):
    """Reconhecimento facial (InsightFace na GPU) + regra de identidade por track."""

    enabled: bool = False
    model: str = "buffalo_l"
    det_size: int = 320
    device: int | str = 0
    match_threshold: float = 0.45
    unknown_threshold: float = 0.30
    known_votes: int = 3
    unknown_votes: int = 5
    unidentified_after_s: float = 20.0
    min_face_px: int = 40
    min_frontal: float = 0.3
    sync_interval_s: float = 30.0
    cache_path: Path = Path("data/faces/embeddings.npz")
    # Alarme sonoro no homelab/painel para rosto desconhecido confirmado
    alarm_on_unknown: bool = True


class LiveCfg(BaseModel):
    """Vídeo anotado publicado no mediamtx (URL com senha em VIGIA_LIVE_URL no .env)."""

    enabled: bool = False
    fps: float = 15.0
    encoder: str = "h264_nvenc"  # libx264 se não houver NVIDIA
    bitrate: str = "2M"


class HubCfg(BaseModel):
    """Envio dos eventos para o hub do homelab (que dispara Telegram/WhatsApp)."""

    enabled: bool = False
    url: str = "http://192.168.1.108:8090"
    heartbeat_s: float = 60.0
    retry_s: float = 30.0
    timeout_s: float = 10.0
    outbox_dir: Path = Path("data/outbox")


class DisplayCfg(BaseModel):
    show_window: bool = True


class AppConfig(BaseModel):
    camera: CameraCfg = CameraCfg()
    detector: DetectorCfg = DetectorCfg()
    zones_file: Path = Path("config/zones.yaml")
    loitering: LoiteringCfg = LoiteringCfg()
    events: EventsCfg = EventsCfg()
    telegram: TelegramCfg = TelegramCfg()
    hub: HubCfg = HubCfg()
    face: FaceCfg = FaceCfg()
    live: LiveCfg = LiveCfg()
    display: DisplayCfg = DisplayCfg()


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    vigia_camera_source: str | None = None
    vigia_snapshot_source: str | None = None
    vigia_hub_token: str | None = None
    vigia_live_url: str | None = None

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_config(path: str | Path = "config/config.yaml") -> tuple[AppConfig, Secrets]:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    cfg = AppConfig.model_validate(data or {})
    secrets = Secrets()

    if secrets.vigia_camera_source:
        cfg.camera.source = parse_source(secrets.vigia_camera_source)
    if secrets.vigia_snapshot_source:
        cfg.camera.snapshot_source = parse_source(secrets.vigia_snapshot_source)
    cfg.camera.source = parse_source(cfg.camera.source)
    return cfg, secrets
