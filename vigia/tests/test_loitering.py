from vigia.rules.loitering import LoiteringTracker


def make(threshold=10.0, grace=2.0):
    return LoiteringTracker({"portao": threshold}, default_threshold_s=99, grace_period_s=grace)


def feed(t, ids, start, end, step=1.0, zone="portao"):
    """Simula frames contínuos de `start` a `end` (inclusive) e acumula os alertas."""
    hits, now = [], start
    while now <= end + 1e-9:
        hits += t.update({zone: set(ids)}, now=now)
        now += step
    return hits


def test_dispara_apos_limiar():
    t = make()
    assert feed(t, {1}, 0, 9) == []
    hits = feed(t, {1}, 10, 10)
    assert len(hits) == 1 and hits[0].track_id == 1 and hits[0].zone == "portao"


def test_nao_repete_alerta_para_mesmo_track():
    t = make()
    assert len(feed(t, {1}, 0, 30)) == 1


def test_periodo_de_graca_mantem_cronometro():
    t = make(grace=2.0)
    feed(t, {1}, 0, 3)
    feed(t, set(), 4, 4)  # oclusão curta (<= graça)
    assert len(feed(t, {1}, 5, 10)) == 1  # cronômetro não zerou


def test_ausencia_longa_zera_cronometro():
    t = make(grace=2.0)
    feed(t, {1}, 0, 5)
    feed(t, set(), 6, 12)  # sumiu > graça
    assert feed(t, {1}, 13, 16) == []
    assert t.dwell("portao", 1) == 3


def test_reaparicao_sem_frames_intermediarios_reinicia():
    t = make(grace=2.0)
    t.update({"portao": {1}}, now=0)
    assert t.update({"portao": {1}}, now=50) == []
    assert t.dwell("portao", 1) == 0


def test_limiar_padrao_para_zona_sem_config():
    t = make()
    assert t.threshold("garagem") == 99
