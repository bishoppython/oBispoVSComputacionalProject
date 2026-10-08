"""CLI do Vigia:  vigia run | zones | probe | telegram-test | hub"""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.logging import RichHandler

from vigia.config import load_config, parse_source

app = typer.Typer(add_completion=False, help="Sistema local de segurança com visão computacional.")
CONFIG = typer.Option(Path("config/config.yaml"), "--config", "-c", help="Arquivo de configuração")


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # não logar cada heartbeat


@app.command()
def run(
    config: Path = CONFIG,
    source: str = typer.Option(
        None, "--source", "-s", help="Sobrescreve a fonte (0, arquivo, rtsp://)"
    ),
    no_window: bool = typer.Option(False, "--no-window", help="Sem janela (servidor/headless)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Roda o pipeline de monitoramento."""
    _logging(verbose)
    from vigia.pipeline import Pipeline

    cfg, secrets = load_config(config)
    if source is not None:
        cfg.camera.source = parse_source(source)
    if no_window:
        cfg.display.show_window = False
    Pipeline(cfg, secrets).run()


@app.command()
def zones(config: Path = CONFIG, source: str = typer.Option(None, "--source", "-s")) -> None:
    """Abre o editor visual de zonas sobre um frame da câmera."""
    _logging(False)
    from vigia.tools.zone_editor import run_editor
    from vigia.video.source import grab_one_frame, resize_to_width

    cfg, _ = load_config(config)
    src = parse_source(source) if source is not None else cfg.camera.source
    frame = resize_to_width(grab_one_frame(src), cfg.camera.width)
    run_editor(frame, cfg.zones_file)


@app.command()
def probe(config: Path = CONFIG, source: str = typer.Option(None, "--source", "-s")) -> None:
    """Testa a fonte de vídeo e mostra resolução/FPS (útil para validar o RTSP da VIGI)."""
    _logging(False)
    import time

    import cv2

    from vigia.video.source import VideoSource, mask_source

    cfg, _ = load_config(config)
    src = parse_source(source) if source is not None else cfg.camera.source
    vs = VideoSource(src, "probe").start()
    n, t0 = 0, time.monotonic()
    try:
        while True:
            ok, frame, _ = vs.read()
            if not ok:
                if vs.ended:
                    break
                continue
            n += 1
            fps = n / (time.monotonic() - t0)
            h, w = frame.shape[:2]
            cv2.putText(
                frame,
                f"{w}x{h} {fps:.1f} fps",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )
            cv2.imshow("vigia - probe", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        vs.stop()
        cv2.destroyAllWindows()
        typer.echo(f"Fonte {mask_source(src)}: {n} frames recebidos")


@app.command("telegram-test")
def telegram_test(config: Path = CONFIG) -> None:
    """Envia uma mensagem e uma imagem de teste para validar o bot."""
    _logging(False)
    import numpy as np

    from vigia.events.models import Event
    from vigia.notify.telegram import TelegramClient, format_caption

    _, secrets = load_config(config)
    if not secrets.telegram_ready:
        raise typer.Exit("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env")
    client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
    img = np.full((240, 420, 3), (40, 40, 40), dtype=np.uint8)
    event = Event(
        kind="teste",
        camera_id="teste",
        message="Mensagem de teste do Vigia.",
        severity="info",
        frame=img,
    )
    client.send_photo(img, format_caption(event))
    client.close()
    typer.echo("Enviado ✅")


@app.command()
def hub(
    host: str = typer.Option("0.0.0.0", help="Endereço de escuta"),
    port: int = typer.Option(8090, help="Porta HTTP"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Roda o hub do homelab: recebe eventos e envia Telegram/WhatsApp/relatórios."""
    _logging(verbose)
    import uvicorn

    from vigia.hub.app import create_app
    from vigia.hub.service import build_hub
    from vigia.hub.settings import HubSettings

    settings = HubSettings()
    uvicorn.run(
        create_app(build_hub(settings), settings.vigia_hub_token),
        host=host,
        port=port,
        log_config=None,  # usa o RichHandler já configurado
    )


if __name__ == "__main__":
    app()
