import io
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vigia.events.models import Event
from vigia.hub.app import create_app
from vigia.hub.channels import format_whatsapp
from vigia.hub.monitor import PresenceMonitor
from vigia.hub.report import build_report_pdf, month_bounds, previous_month, summarize
from vigia.hub.service import Hub
from vigia.hub.settings import HubSettings
from vigia.hub.store import EventStore

TOKEN = "segredo"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeChannel:
    def __init__(self, name="fake", fail_times=0):
        self.name = name
        self.fail_times = fail_times
        self.sent = []

    def _maybe_fail(self):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("canal fora")

    def send_alert(self, event, photo):
        self._maybe_fail()
        self.sent.append(("alert", event.message, photo))

    def send_text(self, text):
        self._maybe_fail()
        self.sent.append(("text", text, None))

    def send_document(self, content, filename, caption):
        self._maybe_fail()
        self.sent.append(("document", filename, content))

    def close(self):
        pass


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def jpeg(w=64, h=36):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 50, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def payload(i=1, ts=None, kind="loitering", zone="portao"):
    return {
        "id": f"{i:032x}",
        "kind": kind,
        "camera_id": "frente",
        "message": f"Pessoa parada há {60 + i}s na zona '{zone}'.",
        "severity": "alerta",
        "zone": zone,
        "track_id": i,
        "timestamp": ts if ts is not None else datetime(2026, 9, 10, 23, 30).timestamp(),
        "meta": {"dwell_s": 60.0 + i},
    }


@pytest.fixture
def settings(tmp_path):
    return HubSettings(_env_file=None, vigia_hub_token=TOKEN, hub_data_dir=tmp_path / "hub")


def make_hub(settings, now=datetime(2026, 10, 8, 12, 0), channels=None, probe=None):
    clock = Clock(now.timestamp())
    chans = channels if channels is not None else [FakeChannel("telegram"), FakeChannel("whatsapp")]
    hub = Hub(settings, EventStore(settings.hub_data_dir), chans, camera_probe=probe, clock=clock)
    return hub, chans, clock


# ---- monitor -----------------------------------------------------------
def test_presenca_avisa_uma_vez_ao_cair_e_ao_voltar():
    m = PresenceMonitor(offline_after_s=300, started_at=0)
    assert m.beat(10) is None  # primeiro sinal: silencioso
    assert m.check(200) is None
    assert m.check(311) == "offline"
    assert m.check(900) is None  # não repete
    assert m.beat(1000) == "online"


def test_presenca_avisa_se_nunca_apareceu_desde_o_inicio():
    m = PresenceMonitor(offline_after_s=300, started_at=0)
    assert m.check(301) == "offline"
    assert m.last_signal == 0  # "sem contato desde" o início, não desde a verificação
    assert m.beat(400) == "online"


# ---- store / service ---------------------------------------------------
def test_ingest_grava_foto_e_ignora_duplicado(settings):
    hub, chans, _ = make_hub(settings)
    assert hub.ingest(payload(1), jpeg())
    assert not hub.ingest(payload(1), jpeg())  # reenvio da outbox
    hub.process_pending(sleep=lambda s: None)
    for c in chans:
        assert [k for k, *_ in c.sent] == ["alert"]
    ev = hub.store.between(0, 1e12)[0]
    assert ev.photo.startswith("photos/2026-09/") and hub.store.read_photo(ev)


def test_canal_com_falha_temporaria_e_reenviado_sem_afetar_o_outro(settings):
    flaky, ok = FakeChannel("whatsapp", fail_times=2), FakeChannel("telegram")
    hub, _, _ = make_hub(settings, channels=[flaky, ok])
    hub.ingest(payload(1), None)
    hub.process_pending(sleep=lambda s: None)
    assert len(flaky.sent) == 1 and len(ok.sent) == 1


def test_nitro_desligada_gera_um_aviso_e_retomada_outro(settings):
    hub, chans, clock = make_hub(settings)
    hub.heartbeat({"node": "bispo-Nitro-V15", "fps": 25.0, "camera_ok": True})
    clock.t += 301
    hub.tick()
    clock.t += 600
    hub.tick()
    hub.heartbeat({"node": "bispo-Nitro-V15"})
    hub.process_pending(sleep=lambda s: None)
    texts = [t for k, t, _ in chans[0].sent if k == "text"]
    assert len(texts) == 2
    assert texts[0].startswith("⏸️ Vigilância pausada")
    assert texts[1].startswith("▶️ Vigilância retomada")


def test_camera_sem_sinal_no_mediamtx(settings):
    state = {"ready": True}
    hub, chans, clock = make_hub(settings, probe=lambda: state["ready"])
    hub.tick()
    state["ready"] = False
    clock.t += 91
    hub.tick()
    state["ready"] = True
    clock.t += 30
    hub.tick()
    hub.process_pending(sleep=lambda s: None)
    texts = [t for k, t, _ in chans[0].sent if k == "text"]
    assert "sem sinal" in texts[0] and "voltou" in texts[1]


def test_relatorio_mensal_enviado_uma_vez_no_dia_1(settings):
    hub, chans, clock = make_hub(settings, now=datetime(2026, 10, 8, 12, 0))
    hub.ingest(payload(1, ts=datetime(2026, 10, 9, 22, 0).timestamp()), jpeg())
    hub.process_pending(sleep=lambda s: None)
    hub.tick()  # primeira execução não manda o mês anterior
    clock.t = datetime(2026, 11, 1, 7, 59).timestamp()
    hub.tick()  # antes da hora
    clock.t = datetime(2026, 11, 1, 8, 0).timestamp()
    hub.tick()
    hub.tick()
    hub.process_pending(sleep=lambda s: None)
    docs = [(name, content) for k, name, content in chans[0].sent if k == "document"]
    assert [name for name, _ in docs] == ["vigia_relatorio_2026-10.pdf"]
    assert docs[0][1][:5] == b"%PDF-"


def test_retencao_apaga_eventos_e_fotos_antigos(settings):
    hub, _, clock = make_hub(settings, now=datetime(2026, 10, 8, 12, 0))
    hub.ingest(payload(1, ts=datetime(2026, 6, 1).timestamp()), jpeg())
    hub.ingest(payload(2, ts=datetime(2026, 10, 1).timestamp()), jpeg())
    old_photo = hub.store.data_dir / hub.store.between(0, 1e12)[0].photo
    hub.tick()
    assert [e.id for e in hub.store.between(0, 1e12)] == [payload(2)["id"]]
    assert not old_photo.exists()


# ---- relatório -----------------------------------------------------------
def test_mes_anterior_e_limites():
    assert previous_month(datetime(2026, 1, 5).date()) == (2025, 12)
    start, end = month_bounds(2026, 12)
    assert datetime.fromtimestamp(start) == datetime(2026, 12, 1)
    assert datetime.fromtimestamp(end) == datetime(2027, 1, 1)


def test_resumo_e_pdf_com_fotos(settings, tmp_path):
    store = EventStore(tmp_path / "s")
    for i, hour in enumerate([1, 23, 23], start=1):
        store.add(payload(i, ts=datetime(2026, 9, 10, hour).timestamp()), jpeg(), 0)
    events = store.between(*month_bounds(2026, 9))
    s = summarize(events)
    assert s.total == 3 and s.by_kind["Permanência"] == 3
    assert s.by_period["Noite (18h-24h)"] == 2 and s.by_period["Madrugada (0h-6h)"] == 1
    pdf = build_report_pdf(events, 2026, 9, store.read_photo)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000
    assert build_report_pdf([], 2026, 9, store.read_photo)[:5] == b"%PDF-"


def test_legenda_whatsapp():
    text = format_whatsapp(Event(kind="loitering", camera_id="frente", message="Oi", zone="portao"))
    assert "*Alerta de suspeito*" in text and "_portao_" in text


# ---- API -----------------------------------------------------------------
def test_api_exige_token_e_recebe_evento(settings):
    hub, chans, _ = make_hub(settings)
    client = TestClient(create_app(hub, TOKEN))
    data = {"event": json.dumps(payload(7))}
    files = {"photo": ("a.jpg", jpeg(), "image/jpeg")}
    assert client.post("/events", data=data, files=files).status_code == 401
    bad = {"Authorization": "Bearer çã".encode("latin-1")}
    assert client.post("/events", data=data, files=files, headers=bad).status_code == 401
    r = client.post("/events", data=data, files=files, headers=AUTH)
    assert r.json() == {"status": "ok"}
    r = client.post("/events", data=data, files=files, headers=AUTH)
    assert r.json() == {"status": "duplicate"}
    assert client.get("/health").json()["events"] == 1


def test_api_rejeita_id_que_nao_e_hex(settings):
    hub, _, _ = make_hub(settings)
    client = TestClient(create_app(hub, TOKEN))
    bad = payload(1) | {"id": "../../etc/passwd"}
    r = client.post("/events", data={"event": json.dumps(bad)}, headers=AUTH)
    assert r.status_code == 422


def test_api_heartbeat_e_relatorio_manual(settings):
    hub, chans, _ = make_hub(settings)
    client = TestClient(create_app(hub, TOKEN))
    r = client.post("/heartbeat", json={"node": "nitro", "fps": 20.0}, headers=AUTH)
    assert r.status_code == 200 and hub.node.online
    r = client.post("/reports/monthly?month=2026-09", headers=AUTH)
    assert r.json()["month"] == "2026-09"
    assert client.post("/reports/monthly?month=2026-13", headers=AUTH).status_code == 422


# ---- painel, cadastro, alarme ---------------------------------------------------
def panel_client(settings, **kw):
    hub, chans, clock = make_hub(settings)
    app = create_app(hub, TOKEN, panel_password="senha-painel", **kw)
    return TestClient(app), hub, chans


def test_painel_exige_login_e_cookie_libera_api(settings):
    client, _, _ = panel_client(settings)
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/api/state").status_code == 401
    r = client.post("/login", data={"password": "errada"}, follow_redirects=False)
    assert r.headers["location"] == "/login?erro=senha"
    r = client.post("/login", data={"password": "senha-painel"}, follow_redirects=False)
    assert r.headers["location"] == "/" and "vigia_sessao" in r.cookies
    assert client.get("/api/state").json()["alarm"]["active"] is False
    assert "Vigia" in client.get("/").text
    client.cookies.set("vigia_sessao", "9999999999.assinatura-falsa")
    assert client.get("/api/state").status_code == 401


def test_cadastro_de_pessoa_upload_status_e_remocao(settings):
    client, hub, _ = panel_client(settings)
    pid = client.post("/api/people", json={"name": "  Ana   Maria "}, headers=AUTH).json()["id"]
    files = [("files", ("a.jpg", jpeg(), "image/jpeg")), ("files", ("b.jpg", jpeg(), "image/jpeg"))]
    added = client.post(f"/api/people/{pid}/photos", files=files, headers=AUTH).json()["added"]
    bad = [("files", ("x.jpg", b"nao-e-imagem", "image/jpeg"))]
    assert client.post(f"/api/people/{pid}/photos", files=bad, headers=AUTH).status_code == 422

    [ana] = client.get("/api/faces/manifest", headers=AUTH).json()["people"]
    assert ana["name"] == "Ana Maria" and [p["status"] for p in ana["photos"]] == ["pending"] * 2
    r = client.post(f"/api/faces/photos/{added[0]}/status", json={"status": "ok"}, headers=AUTH)
    assert r.status_code == 200
    r = client.post(f"/api/faces/photos/{added[0]}/status", json={"status": "xx"}, headers=AUTH)
    assert r.status_code == 422
    assert client.get(f"/api/faces/photos/{added[0]}.jpg", headers=AUTH).content[:2] == b"\xff\xd8"

    photo_file = hub.store.face_photo_path(added[1])
    assert client.delete(f"/api/people/{pid}", headers=AUTH).status_code == 200
    assert client.get("/api/people", headers=AUTH).json()["people"] == []
    assert not photo_file.exists()  # biometria apagada do disco


def test_captura_pela_camera(settings):
    client, _, _ = panel_client(settings, capture=lambda count, interval: [jpeg()] * count)
    pid = client.post("/api/people", json={"name": "Bia"}, headers=AUTH).json()["id"]
    r = client.post(f"/api/people/{pid}/capture?count=3", headers=AUTH)
    assert len(r.json()["added"]) == 3
    assert client.post("/api/people/999/capture", headers=AUTH).status_code == 404


def test_evento_com_alarme_dispara_e_info_nao_vai_para_os_canais(settings):
    hub, chans, clock = make_hub(settings)
    known = payload(1) | {"kind": "face_known", "severity": "info", "subject": "Ana"}
    hub.ingest(known, None)
    clock.t += 1
    stranger = payload(2) | {"kind": "face_unknown", "severity": "critico", "meta": {"alarm": True}}
    hub.ingest(stranger, jpeg())
    hub.process_pending(sleep=lambda s: None)
    assert [k for k, *_ in chans[0].sent] == ["alert"]  # só o desconhecido
    assert hub.alarm.state()["active"] is True
    hub.alarm.stop()
    assert hub.alarm.state()["active"] is False
    [last, first] = hub.store.recent(10)
    assert first.subject == "Ana" and last.kind == "face_unknown"
    assert hub.store.recent(10, since_received=last.received_at) == []


def test_alarme_expira_sozinho(settings, tmp_path):
    from vigia.hub.alarm import Alarm, siren_wav

    clock = Clock(0)
    alarm = Alarm(tmp_path, duration_s=30, play_sound=False, clock=clock)
    alarm.trigger("x")
    clock.t = 29
    assert alarm.active
    clock.t = 31
    assert not alarm.active
    assert siren_wav(0.5)[:4] == b"RIFF"


def test_migracao_adiciona_coluna_subject(tmp_path):
    import sqlite3

    db = tmp_path / "vigia.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE events (id TEXT PRIMARY KEY, timestamp REAL NOT NULL,"
        " camera_id TEXT NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL,"
        " zone TEXT, track_id INTEGER,"
        " message TEXT NOT NULL, meta TEXT NOT NULL, photo TEXT, received_at REAL NOT NULL);"
        "INSERT INTO events VALUES ('a', 1, 'frente', 'loitering', 'alerta', NULL, NULL, 'x', '{}',"
        " NULL, 1);"
    )
    con.commit()
    con.close()
    store = EventStore(tmp_path)
    assert store.recent(5)[0].subject is None
    assert store.add(payload(9) | {"subject": "Ana"}, None, 2).subject == "Ana"
