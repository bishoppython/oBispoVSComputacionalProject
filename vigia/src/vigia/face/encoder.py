"""InsightFace (`buffalo_l`: SCRFD + ArcFace 512-d) na GPU via onnxruntime."""

from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

from vigia.face.contracts import FaceObservation
from vigia.face.quality import QualityCfg, assess, head_region

log = logging.getLogger(__name__)


class InsightFaceEncoder:
    def __init__(
        self,
        model: str = "buffalo_l",
        det_size: int = 320,
        device: int | str = 0,
        quality: QualityCfg | None = None,
    ):
        import onnxruntime as ort  # import tardio: os testes não precisam disso

        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()  # usa as libs CUDA instaladas pelo pip (as mesmas do torch)
        from insightface.app import FaceAnalysis

        use_gpu = device != "cpu"
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if use_gpu else None
        self.app = FaceAnalysis(
            name=model, allowed_modules=["detection", "recognition"], providers=providers
        )
        self.app.prepare(ctx_id=0 if use_gpu else -1, det_size=(det_size, det_size))
        self.quality = quality or QualityCfg()
        self._lock = threading.Lock()  # loop de vídeo e sincronização da galeria usam junto
        provider = self.app.models["recognition"].session.get_providers()[0]
        log.info("InsightFace %s carregado (%s).", model, provider)

    def _faces(self, image: np.ndarray):
        with self._lock:
            return self.app.get(image)

    def encode(
        self, frame: np.ndarray, person_box: tuple[int, int, int, int]
    ) -> list[FaceObservation]:
        """Rostos bons dentro da caixa da pessoa, do melhor para o pior."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = head_region(person_box, w, h)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        out = []
        for f in self._faces(crop):
            fx1, fy1, fx2, fy2 = (int(v) for v in f.bbox)
            face_gray = gray[max(0, fy1) : max(0, fy2), max(0, fx1) : max(0, fx2)]
            q = assess((fx1, fy1, fx2, fy2), f.kps, float(f.det_score), face_gray, self.quality)
            if q is None:
                continue
            bbox = (fx1 + x1, fy1 + y1, fx2 + x1, fy2 + y1)
            out.append(FaceObservation(bbox, f.normed_embedding, float(f.det_score), q))
        return sorted(out, key=lambda o: o.quality, reverse=True)

    def encode_image(self, image: np.ndarray) -> FaceObservation | None:
        """Foto de cadastro: o maior rosto da imagem, com filtro de qualidade mais leve."""
        faces = self._faces(image)
        if not faces:
            return None
        f = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        if float(f.det_score) < 0.5:
            return None
        bbox = tuple(int(v) for v in f.bbox)
        return FaceObservation(bbox, f.normed_embedding, float(f.det_score), 1.0)
