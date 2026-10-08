import httpx
import numpy as np

from vigia.events.models import Event
from vigia.notify.hub import HubSink, Outbox, event_to_payload


class FakeClient:
    def __init__(self):
        self.up = True
        self.events = []
        self.heartbeats = []

    def post_event(self, payload, jpeg):
        if not self.up:
            raise httpx.ConnectError("hub fora")
        self.events.append((payload, jpeg))

    def post_heartbeat(self, status):
        if not self.up:
            raise httpx.ConnectError("hub fora")
        self.heartbeats.append(status)

    def close(self):
        pass


def ev(msg="x", frame=True):
    img = np.zeros((20, 30, 3), dtype=np.uint8) if frame else None
    return Event(kind="loitering", camera_id="frente", message=msg, zone="portao", frame=img)


def sink(tmp_path, client, **kw):
    return HubSink(client, Outbox(tmp_path / "outbox"), autostart=False, **kw)


def test_payload_sem_frame_e_serializavel():
    e = ev()
    e.meta["caminho"] = tmp = object()
    p = event_to_payload(e, "a" * 32)
    assert p["id"] == "a" * 32 and p["zone"] == "portao"
    assert p["meta"]["caminho"] == str(tmp)
    assert "frame" not in p


def test_evento_entregue_com_foto_e_outbox_esvaziada(tmp_path):
    client = FakeClient()
    s = sink(tmp_path, client)
    s.handle(ev())
    s.step(now=0)
    assert len(client.events) == 1
    payload, jpeg = client.events[0]
    assert jpeg[:2] == b"\xff\xd8"  # JPEG
    assert s.outbox.pending() == []


def test_hub_fora_guarda_na_outbox_e_reenvia_em_ordem(tmp_path):
    client = FakeClient()
    client.up = False
    s = sink(tmp_path, client, retry_s=30)
    s.handle(ev("primeiro"))
    s.handle(ev("segundo", frame=False))
    s.step(now=0)
    assert len(s.outbox.pending()) == 2

    client.up = True
    s.step(now=10)  # ainda em espera de reenvio
    assert client.events == []
    s.step(now=31)
    assert [p["message"] for p, _ in client.events] == ["primeiro", "segundo"]
    assert client.events[1][1] is None
    assert s.outbox.pending() == []


def test_outbox_sobrevive_a_reinicio(tmp_path):
    client = FakeClient()
    client.up = False
    s = sink(tmp_path, client)
    s.handle(ev("pendente"))
    s.close()

    client.up = True
    s2 = sink(tmp_path, client)
    s2.step(now=0)
    assert [p["message"] for p, _ in client.events] == ["pendente"]


def test_outbox_limita_tamanho_descartando_os_mais_antigos(tmp_path):
    box = Outbox(tmp_path, max_items=2)
    for i in range(3):
        box.put({"id": f"{i:032x}", "message": str(i)}, None)
    assert [box.load(p)[0]["message"] for p in box.pending()] == ["1", "2"]


def test_heartbeat_periodico_com_status(tmp_path):
    client = FakeClient()
    s = sink(tmp_path, client, heartbeat_s=60, status_fn=lambda: {"fps": 12.0, "camera_ok": True})
    s.step(now=0)
    s.step(now=30)
    s.step(now=61)
    assert len(client.heartbeats) == 2
    assert client.heartbeats[0]["fps"] == 12.0 and "node" in client.heartbeats[0]
