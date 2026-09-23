from vigia.events.engine import EventEngine
from vigia.events.models import Event


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Collector:
    def __init__(self):
        self.events = []

    def handle(self, e):
        self.events.append(e)

    def close(self):
        pass


class Broken:
    def handle(self, e):
        raise RuntimeError("boom")

    def close(self):
        pass


def ev(zone="portao", track=1):
    return Event(kind="loitering", camera_id="frente", message="x", zone=zone, track_id=track)


def test_cooldown_por_zona_ignora_troca_de_id():
    clock, sink = FakeClock(), Collector()
    eng = EventEngine([sink], cooldown_s=60, clock=clock)
    assert eng.emit(ev(track=1))
    clock.t = 10
    assert not eng.emit(ev(track=2))  # mesmo lugar, ID trocado -> suprimido
    clock.t = 61
    assert eng.emit(ev(track=3))
    assert len(sink.events) == 2


def test_zonas_diferentes_nao_se_bloqueiam():
    sink = Collector()
    eng = EventEngine([sink], cooldown_s=60, clock=FakeClock())
    assert eng.emit(ev(zone="portao"))
    assert eng.emit(ev(zone="garagem"))


def test_sink_quebrado_nao_derruba_os_outros():
    sink = Collector()
    eng = EventEngine([Broken(), sink], cooldown_s=0, clock=FakeClock())
    eng.emit(ev())
    assert len(sink.events) == 1
