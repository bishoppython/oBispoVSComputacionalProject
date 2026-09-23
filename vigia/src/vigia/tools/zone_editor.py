"""Editor visual de zonas.

Clique esquerdo: adiciona ponto | Enter: fecha o polígono (pede nome no terminal)
u: desfaz ponto | d: apaga última zona | s: salva | q: sai sem salvar
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vigia.rules.zones import ZONE_KINDS, Zone, load_zones, save_zones
from vigia.viz.overlay import draw_zones

WINDOW = "vigia - zonas"


def run_editor(frame: np.ndarray, zones_path: Path) -> None:
    zones = load_zones(zones_path)
    h, w = frame.shape[:2]
    points: list[tuple[int, int]] = []

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)
    print(__doc__)

    while True:
        view = draw_zones(frame.copy(), zones)
        for i, p in enumerate(points):
            cv2.circle(view, p, 5, (0, 0, 255), -1)
            if i:
                cv2.line(view, points[i - 1], p, (0, 0, 255), 2)
        cv2.imshow(WINDOW, view)
        key = cv2.waitKey(30) & 0xFF

        if key == 13 and len(points) >= 3:  # Enter
            name = input("Nome da zona: ").strip() or f"zona{len(zones) + 1}"
            kind = input(f"Tipo {sorted(ZONE_KINDS)} [loitering]: ").strip() or "loitering"
            thr = input("Limiar em segundos (vazio = padrão): ").strip()
            poly = np.array(points, dtype=np.float32) / np.array([w, h], dtype=np.float32)
            zones = [z for z in zones if z.name != name]
            zones.append(
                Zone(name=name, kind=kind, polygon=poly, threshold_s=float(thr) if thr else None)
            )
            points.clear()
        elif key == ord("u") and points:
            points.pop()
        elif key == ord("d") and zones:
            removed = zones.pop()
            print(f"Zona removida: {removed.name}")
        elif key == ord("s"):
            save_zones(zones_path, zones)
            print(f"{len(zones)} zona(s) salvas em {zones_path}")
            break
        elif key == ord("q"):
            print("Saindo sem salvar.")
            break

    cv2.destroyAllWindows()
