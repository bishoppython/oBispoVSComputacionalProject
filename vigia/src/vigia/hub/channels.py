"""Canais de saída do hub: Telegram e WhatsApp (Evolution API)."""

from __future__ import annotations

import base64
import html
from datetime import datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from vigia.events.models import SEVERITY_ICON, Event
from vigia.notify.telegram import TelegramClient, format_caption


class Channel(Protocol):
    name: str

    def send_alert(self, event: Event, photo: bytes | None) -> None: ...
    def send_text(self, text: str) -> None: ...
    def send_document(self, content: bytes, filename: str, caption: str) -> None: ...
    def close(self) -> None: ...


class TelegramChannel:
    name = "telegram"

    def __init__(self, client: TelegramClient):
        self.client = client

    def send_alert(self, event: Event, photo: bytes | None) -> None:
        caption = format_caption(event)
        if photo:
            self.client.send_photo_bytes(photo, caption)
        else:
            self.client.send_message(caption)

    def send_text(self, text: str) -> None:
        self.client.send_message(html.escape(text))

    def send_document(self, content: bytes, filename: str, caption: str) -> None:
        self.client.send_document(content, filename, html.escape(caption), "application/pdf")

    def close(self) -> None:
        self.client.close()


def format_whatsapp(event: Event) -> str:
    """Mesma legenda do Telegram, na marcação do WhatsApp (*negrito*, _itálico_)."""
    when = datetime.fromtimestamp(event.timestamp).strftime("%d/%m/%Y %H:%M:%S")
    lines = [
        f"{SEVERITY_ICON[event.severity]} *Alerta de suspeito*",
        event.message,
        "",
        f"📷 {event.camera_id}" + (f" · zona _{event.zone}_" if event.zone else ""),
        f"🕒 {when}",
    ]
    return "\n".join(lines)


class EvolutionClient:
    """Cliente mínimo da Evolution API v2 (sendText / sendMedia)."""

    def __init__(self, url: str, api_key: str, instance: str, to: str, timeout: float = 30.0):
        self.to = to
        self.instance = quote(instance, safe="")
        self._http = httpx.Client(
            base_url=url.rstrip("/"), timeout=timeout, headers={"apikey": api_key}
        )

    def send_text(self, text: str) -> None:
        r = self._http.post(
            f"/message/sendText/{self.instance}", json={"number": self.to, "text": text}
        )
        r.raise_for_status()

    def send_media(
        self, content: bytes, mediatype: str, mimetype: str, filename: str, caption: str
    ) -> None:
        r = self._http.post(
            f"/message/sendMedia/{self.instance}",
            json={
                "number": self.to,
                "mediatype": mediatype,
                "mimetype": mimetype,
                "media": base64.b64encode(content).decode("ascii"),
                "fileName": filename,
                "caption": caption,
            },
        )
        r.raise_for_status()

    def close(self) -> None:
        self._http.close()


class WhatsAppChannel:
    name = "whatsapp"

    def __init__(self, client: EvolutionClient):
        self.client = client

    def send_alert(self, event: Event, photo: bytes | None) -> None:
        text = format_whatsapp(event)
        if photo:
            self.client.send_media(photo, "image", "image/jpeg", "alerta.jpg", text)
        else:
            self.client.send_text(text)

    def send_text(self, text: str) -> None:
        self.client.send_text(text)

    def send_document(self, content: bytes, filename: str, caption: str) -> None:
        self.client.send_media(content, "document", "application/pdf", filename, caption)

    def close(self) -> None:
        self.client.close()
