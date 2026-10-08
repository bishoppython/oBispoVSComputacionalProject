"""Filtro de qualidade de rosto (puro): tamanho, confiança, nitidez e pose frontal.

Só rostos bons votam no reconhecimento — um rosto de perfil ou borrado tende a
ter similaridade baixa com todo mundo e geraria falso "desconhecido".
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class QualityCfg:
    min_face_px: int = 40
    min_det_score: float = 0.6
    min_sharpness: float = 30.0  # variância do Laplaciano
    min_frontal: float = 0.3  # 0 = perfil, 1 = de frente


def frontalness(kps: np.ndarray) -> float:
    """Quão de frente está o rosto, pelos 5 pontos (olho e, olho d, nariz, boca e, boca d).

    Usa o deslocamento horizontal do nariz em relação ao meio dos olhos.
    """
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_dist = abs(float(right_eye[0] - left_eye[0]))
    if eye_dist < 1e-3:
        return 0.0
    offset = (float(nose[0]) - (left_eye[0] + right_eye[0]) / 2) / eye_dist
    return float(max(0.0, 1.0 - abs(offset) / 0.5))


def sharpness(gray_face: np.ndarray) -> float:
    if gray_face.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray_face, cv2.CV_64F).var())


def assess(
    bbox: tuple[int, int, int, int],
    kps: np.ndarray,
    det_score: float,
    gray_face: np.ndarray,
    cfg: QualityCfg,
) -> float | None:
    """Retorna a qualidade (0..1) ou None se o rosto não serve para reconhecer."""
    size = min(bbox[2] - bbox[0], bbox[3] - bbox[1])
    if size < cfg.min_face_px or det_score < cfg.min_det_score:
        return None
    front = frontalness(kps)
    sharp = sharpness(gray_face)
    if front < cfg.min_frontal or sharp < cfg.min_sharpness:
        return None
    size_q = min(1.0, size / (3 * cfg.min_face_px))
    sharp_q = min(1.0, sharp / (4 * cfg.min_sharpness))
    return round((size_q + sharp_q + front + det_score) / 4, 3)


def head_region(
    box: tuple[int, int, int, int], frame_w: int, frame_h: int, margin: float = 0.15
) -> tuple[int, int, int, int]:
    """Parte de cima da caixa da pessoa (onde está o rosto), com margem."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    top_h = h * 0.6 if h > 1.3 * w else h  # em pé: só o topo; sentado/deitado: tudo
    mx, my = w * margin, h * margin * 0.5
    return (
        max(0, int(x1 - mx)),
        max(0, int(y1 - my)),
        min(frame_w, int(x2 + mx)),
        min(frame_h, int(y1 + top_h + my)),
    )
