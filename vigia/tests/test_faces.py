import cv2
import numpy as np

from vigia.config import FaceCfg
from vigia.detection.detector import Detection
from vigia.face.contracts import FaceObservation
from vigia.face.gallery import MemoryGallery
from vigia.face.quality import QualityCfg, assess, frontalness, head_region
from vigia.face.sync import GallerySync
from vigia.face.watcher import FaceWatcher
from vigia.rules.identity import IdentityCfg, IdentityTracker
from vigia.rules.zones import Zone

FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)
FRONT = np.array([[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]], dtype=np.float32)
PROFILE = np.array([[40, 50], [55, 50], [70, 70], [45, 90], [55, 90]], dtype=np.float32)


def unit(seed):
    v = np.random.default_rng(seed).normal(size=512).astype(np.float32)
    return v / np.linalg.norm(v)


ANA, BIA, STRANGER = unit(1), unit(2), unit(3)


def textured(size=100):
    return np.random.default_rng(0).integers(0, 255, (size, size), dtype=np.uint8)


# ---- qualidade / galeria ----------------------------------------------------
def test_frontal_e_perfil():
    assert frontalness(FRONT) == 1.0
    assert frontalness(PROFILE) < 0.3


def test_qualidade_rejeita_pequeno_perfil_e_borrado():
    cfg = QualityCfg(min_face_px=40)
    assert assess((0, 0, 100, 100), FRONT, 0.9, textured(), cfg) > 0
    assert assess((0, 0, 30, 30), FRONT, 0.9, textured(30), cfg) is None
    assert assess((0, 0, 100, 100), PROFILE, 0.9, textured(), cfg) is None
    blurred = np.full((100, 100), 128, dtype=np.uint8)
    assert assess((0, 0, 100, 100), FRONT, 0.9, blurred, cfg) is None


def test_regiao_da_cabeca_fica_no_frame():
    x1, y1, x2, y2 = head_region((0, 0, 100, 400), 1280, 720)
    assert (x1, y1) == (0, 0) and y2 < 300  # em pé: só a parte de cima
    assert head_region((1200, 600, 1280, 720), 1280, 720)[2] == 1280


def test_galeria_melhor_correspondencia():
    g = MemoryGallery()
    g.add("Ana", ANA, "a1")
    g.add("Bia", BIA, "b1")
    name, sim = g.best(ANA * 3)  # normaliza
    assert name == "Ana" and sim > 0.99
    assert g.match(STRANGER, threshold=0.45).person is None
    assert g.people == ["Ana", "Bia"]


# ---- watcher ------------------------------------------------------------------
class FakeEncoder:
    def __init__(self):
        self.faces = {}  # track box -> embedding

    def encode(self, frame, box):
        emb = self.faces.get(box)
        return [] if emb is None else [FaceObservation(box, emb, 0.9, 1.0)]


def person(tid, box):
    return Detection(track_id=tid, cls_name="person", conf=0.9, xyxy=box)


DOOR = Zone(name="porta", kind="entrance", polygon=[[0, 0], [0.2, 0], [0.2, 1], [0, 1]])
BED = Zone(name="cama", kind="sensitive", polygon=[[0.6, 0], [1, 0], [1, 1], [0.6, 1]])
BOX_DOOR, BOX_MIDDLE, BOX_BED = (50, 100, 150, 500), (500, 100, 600, 500), (1000, 100, 1100, 500)


def watcher(known_votes=2, unknown_votes=2, gallery=True):
    enc = FakeEncoder()
    ident = IdentityTracker(
        IdentityCfg(known_votes=known_votes, unknown_votes=unknown_votes, sample_interval_s=0)
    )
    w = FaceWatcher(FaceCfg(enabled=True), "quarto", [DOOR, BED], enc, ident)
    if gallery:
        g = MemoryGallery()
        g.add("Ana", ANA, "a1")
        w.set_gallery(g)
    return w, enc


def run(w, dets, steps, t0=0.0, dt=0.5):
    events = []
    for i in range(steps):
        events += w.step(FRAME, dets, t0 + i * dt)
    return events


def test_conhecida_entrando_pela_porta_gera_info_sem_alarme():
    w, enc = watcher()
    enc.faces[BOX_DOOR] = ANA
    [ev] = run(w, [person(1, BOX_DOOR)], 4)
    assert ev.kind == "face_known" and ev.severity == "info" and ev.subject == "Ana"
    assert ev.message == "Ana entrou no quarto."
    assert "alarm" not in ev.meta


def test_desconhecido_gera_critico_com_alarme():
    w, enc = watcher()
    enc.faces[BOX_MIDDLE] = STRANGER
    [ev] = run(w, [person(2, BOX_MIDDLE)], 4)
    assert ev.kind == "face_unknown" and ev.severity == "critico"
    assert ev.meta["alarm"] is True and ev.zone is None


def test_desconhecido_na_cama_avisa_uma_vez_com_a_zona():
    w, enc = watcher()
    enc.faces[BOX_BED] = STRANGER
    events = run(w, [person(3, BOX_BED)], 6)
    assert [e.kind for e in events] == ["face_unknown"]
    assert events[0].zone == "cama" and "cama" in events[0].message


def test_desconhecido_que_vai_para_a_cama_gera_alerta_extra():
    w, enc = watcher()
    enc.faces[BOX_MIDDLE] = STRANGER
    events = run(w, [person(4, BOX_MIDDLE)], 3)
    events += run(w, [person(4, BOX_BED)], 2, t0=2)
    assert [e.kind for e in events] == ["face_unknown", "sensitive_zone"]
    assert events[1].meta["alarm"] is True


def test_galeria_vazia_nao_dispara_nada():
    w, enc = watcher(gallery=False)
    enc.faces[BOX_MIDDLE] = STRANGER
    assert run(w, [person(5, BOX_MIDDLE)], 10) == []


def test_rotulos_do_overlay():
    w, enc = watcher()
    enc.faces[BOX_DOOR] = ANA
    enc.faces[BOX_MIDDLE] = STRANGER
    dets = [person(1, BOX_DOOR), person(2, BOX_MIDDLE), person(3, BOX_BED)]
    run(w, dets, 4)
    labels, colors, highlight = w.overlay(dets)
    assert labels[1].startswith("Ana") and labels[2] == "DESCONHECIDO" and labels[3] == "?"
    assert highlight == {2}


# ---- sincronização ---------------------------------------------------------------
class FakeHub:
    def __init__(self, people):
        self.people = people
        self.statuses = {}

    def get_json(self, path):
        return {"people": self.people}

    def get_bytes(self, path):
        pid = path.rsplit("/", 1)[1].removesuffix(".jpg")
        img = np.full((64, 64, 3), 0 if pid.startswith("vazia") else 200, dtype=np.uint8)
        return cv2.imencode(".jpg", img)[1].tobytes()

    def post_json(self, path, data):
        self.statuses[path.split("/")[-2]] = data["status"]
        return {}


class FakeImageEncoder:
    def __init__(self):
        self.calls = 0

    def encode_image(self, image):
        self.calls += 1
        if image.mean() < 10:
            return None
        return FaceObservation((0, 0, 10, 10), ANA, 0.9, 1.0)


def test_sincroniza_galeria_e_reporta_status(tmp_path):
    hub = FakeHub(
        [
            {
                "name": "Ana",
                "photos": [
                    {"id": "ok1", "status": "pending"},
                    {"id": "vazia1", "status": "pending"},
                ],
            }
        ]
    )
    enc, updates = FakeImageEncoder(), []
    sync = GallerySync(hub, enc, tmp_path / "emb.npz", updates.append)
    g = sync.sync_once()
    assert len(g) == 1 and g.people == ["Ana"]
    assert hub.statuses == {"ok1": "ok", "vazia1": "sem_rosto"}
    assert len(updates) == 1

    # cache: não recalcula; foto com "sem_rosto" não é reprocessada
    hub.people[0]["photos"][1]["status"] = "sem_rosto"
    sync2 = GallerySync(hub, enc, tmp_path / "emb.npz", updates.append)
    calls = enc.calls
    assert len(sync2.sync_once()) == 1 and enc.calls == calls

    # pessoa apagada no hub: some da galeria e do cache local
    hub.people = []
    assert len(sync2.sync_once()) == 0
    assert sync2.cache.items == {}
