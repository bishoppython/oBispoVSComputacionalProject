"""Sincroniza a galeria com o hub.

O hub guarda as fotos de cadastro (painel: captura pela câmera ou upload). A Nitro
baixa as fotos novas, calcula os embeddings na GPU, informa ao hub se cada foto
serviu ("ok") ou não ("sem_rosto") e mantém um cache local dos embeddings.
Pessoa/foto apagada no hub some também do cache local (dado biométrico).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from vigia.face.contracts import FaceObservation
from vigia.face.gallery import MemoryGallery

log = logging.getLogger(__name__)


class ImageEncoder(Protocol):
    def encode_image(self, image: np.ndarray) -> FaceObservation | None: ...


class HubApi(Protocol):
    def get_json(self, path: str) -> dict: ...
    def get_bytes(self, path: str) -> bytes: ...
    def post_json(self, path: str, data: dict) -> dict: ...


class EmbeddingCache:
    """photo_id -> embedding, num .npz local."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: dict[str, np.ndarray] = {}
        if self.path.exists():
            with np.load(self.path) as data:
                self.items = {k: data[k] for k in data.files}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp.npz")
        np.savez(tmp, **self.items)
        tmp.replace(self.path)


class GallerySync:
    def __init__(
        self,
        hub: HubApi,
        encoder: ImageEncoder,
        cache_path: Path,
        on_update: Callable[[MemoryGallery], None],
        interval_s: float = 30.0,
    ):
        self.hub = hub
        self.encoder = encoder
        self.cache = EmbeddingCache(cache_path)
        self.on_update = on_update
        self.interval_s = interval_s
        self._signature: tuple | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sync_once(self) -> MemoryGallery:
        manifest = self.hub.get_json("/api/faces/manifest")
        changed = False
        live_ids: set[str] = set()
        for person in manifest.get("people", []):
            for photo in person.get("photos", []):
                pid = photo["id"]
                live_ids.add(pid)
                if pid in self.cache.items or photo.get("status") == "sem_rosto":
                    continue
                status = self._process(pid)
                if status != photo.get("status"):
                    self.hub.post_json(f"/api/faces/photos/{pid}/status", {"status": status})
                changed |= status == "ok"

        for stale in set(self.cache.items) - live_ids:
            del self.cache.items[stale]
            changed = True
        if changed:
            self.cache.save()

        gallery = MemoryGallery()
        for person in manifest.get("people", []):
            for photo in person.get("photos", []):
                if photo["id"] in self.cache.items:
                    gallery.add(person["name"], self.cache.items[photo["id"]], photo["id"])
        signature = tuple(sorted(gallery.sources))
        if signature != self._signature:
            self._signature = signature
            log.info(
                "Galeria: %d foto(s) de %d pessoa(s): %s",
                len(gallery), len(gallery.people), ", ".join(gallery.people) or "-",
            )  # fmt: skip
            self.on_update(gallery)
        return gallery

    def _process(self, photo_id: str) -> str:
        data = self.hub.get_bytes(f"/api/faces/photos/{photo_id}.jpg")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        obs = self.encoder.encode_image(image) if image is not None else None
        if obs is None:
            return "sem_rosto"
        self.cache.items[photo_id] = np.asarray(obs.embedding, dtype=np.float32)
        return "ok"

    # ---- thread -------------------------------------------------------
    def start(self) -> GallerySync:
        self._thread = threading.Thread(target=self._loop, name="faces-sync", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception as exc:  # hub fora: mantém a galeria atual
                log.warning("Sincronização da galeria falhou: %s", exc)
            self._stop.wait(self.interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
