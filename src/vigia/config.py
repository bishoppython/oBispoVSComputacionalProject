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


class EventsCfg(BaseModel):
    cooldown_s: float = 120.0
    snapshot_dir: Path = Path("data/snapshots")


class TelegramCfg(BaseModel):
    enabled: bool = True


class DisplayCfg(BaseModel):
    show_window: bool = True


class AppConfig(BaseModel):
    camera: CameraCfg = CameraCfg()
    detector: DetectorCfg = DetectorCfg()
    zones_file: Path = Path("config/zones.yaml")
    loitering: LoiteringCfg = LoiteringCfg()
    events: EventsCfg = EventsCfg()
    telegram: TelegramCfg = TelegramCfg()
    display: DisplayCfg = DisplayCfg()


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    vigia_camera_source: str | None = None
    vigia_snapshot_source: str | None = None

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
