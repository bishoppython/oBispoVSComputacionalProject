"""Desenho de zonas, caixas e cronômetros sobre o frame."""

from __future__ import annotations

import cv2
import numpy as np

from vigia.detection.detector import Detection
from vigia.rules.zones import Zone

ZONE_COLORS = {
    "loitering": (0, 200, 255),
    "entrance": (255, 200, 0),
    "sensitive": (180, 80, 255),
    "door": (255, 120, 0),
    "vehicle": (200, 0, 200),
}
PERSON = (60, 220, 60)
ALERT = (0, 0, 255)
OTHER = (200, 200, 200)


def draw_zones(frame: np.ndarray, zones: list[Zone], alpha: float = 0.18) -> np.ndarray:
    h, w = frame.shape[:2]
    overlay = frame.copy()
    for z in zones:
        pts = z.to_pixels(w, h)
        color = ZONE_COLORS.get(z.kind, OTHER)
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(frame, [pts], True, color, 2)
        x, y = pts[0]
        cv2.putText(
            frame,
            z.name,
            (int(x) + 4, int(y) + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    return cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)


def draw_detections(
    frame: np.ndarray,
    detections: list[Detection],
    labels: dict[int, str] | None = None,
    highlight: set[int] | None = None,
    colors: dict[int, tuple[int, int, int]] | None = None,
) -> np.ndarray:
    labels = labels or {}
    highlight = highlight or set()
    colors = colors or {}
    for d in detections:
        x1, y1, x2, y2 = d.xyxy
        is_alert = d.track_id in highlight
        color = ALERT if is_alert else (PERSON if d.cls_name == "person" else OTHER)
        color = colors.get(d.track_id, color) if not is_alert else color
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if is_alert else 2)
        text = f"{d.cls_name} #{d.track_id}" if d.track_id is not None else d.cls_name
        if d.track_id in labels:
            text += f" {labels[d.track_id]}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
        cv2.putText(
            frame, text, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA
        )
        cv2.circle(frame, d.anchor, 4, color, -1)
    return frame


def draw_hud(frame: np.ndarray, fps: float, camera_id: str) -> np.ndarray:
    cv2.putText(
        frame,
        f"{camera_id} | {fps:4.1f} fps",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame
