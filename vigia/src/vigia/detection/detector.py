"""Detecção + tracking com YOLO11 e ByteTrack (Ultralytics)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vigia.config import DetectorCfg


@dataclass(frozen=True)
class Detection:
    track_id: int | None
    cls_name: str
    conf: float
    xyxy: tuple[int, int, int, int]

    @property
    def anchor(self) -> tuple[int, int]:
        """Ponto de referência para zonas: base central da caixa (os pés da pessoa)."""
        x1, _, x2, y2 = self.xyxy
        return (x1 + x2) // 2, y2

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.xyxy
        return (x1 + x2) // 2, (y1 + y2) // 2


class Detector:
    def __init__(self, cfg: DetectorCfg):
        from ultralytics import YOLO  # import tardio: os testes não precisam do torch

        self.cfg = cfg
        self.model = YOLO(cfg.model)
        names: dict[int, str] = self.model.names
        missing = set(cfg.classes) - set(names.values())
        if missing:
            raise ValueError(f"Classes inexistentes no modelo {cfg.model}: {missing}")
        self.class_ids = [i for i, n in names.items() if n in cfg.classes]

    def track(self, frame: np.ndarray) -> list[Detection]:
        result = self.model.track(
            frame,
            persist=True,
            conf=self.cfg.conf,
            classes=self.class_ids,
            tracker=self.cfg.tracker,
            imgsz=self.cfg.imgsz,
            device=self.cfg.device,
            verbose=False,
        )[0]

        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy().astype(int)
        cls = boxes.cls.cpu().numpy().astype(int)
        conf = boxes.conf.cpu().numpy()
        if boxes.id is not None:
            ids: list[int | None] = boxes.id.cpu().numpy().astype(int).tolist()
        else:
            ids = [None] * len(xyxy)

        return [
            Detection(
                track_id=tid,
                cls_name=result.names[c],
                conf=float(cf),
                xyxy=tuple(int(v) for v in box),
            )
            for box, c, cf, tid in zip(xyxy, cls, conf, ids, strict=True)
        ]
