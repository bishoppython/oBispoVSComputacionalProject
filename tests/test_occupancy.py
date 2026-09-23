from vigia.rules.occupancy import OccupancyTracker


def make(threshold=10.0, grace=2.0):
    return OccupancyTracker({"portao": threshold}, default_threshold_s=99, grace_period_s=grace)


def feed(t, count, start, end, step=1.0, zone="portao"):
    """Simula frames contínuos de `start` a `end` (inclusive) e acumula os alertas."""
    hits, now = [], start
    while now <= end + 1e-9:
        hits += t.update({zone: count}, now=now)
        now += step
    return hits


def test_dispara_apos_limiar():
    t = make()
    assert feed(t, 1, 0, 9) == []
    hits = feed(t, 1, 10, 10)
    assert len(hits) == 1 and hits[0].zone == "portao" and hits[0].occupied_s == 10


def test_um_alerta_por_episodio():
    t = make()
    assert len(feed(t, 1, 0, 40)) == 1


def test_troca_de_id_nao_zera_cronometro():
    """O caso que motiva a regra: a contagem não depende do track_id."""
    t = make()
    feed(t, 1, 0, 6)  # track 1
    assert len(feed(t, 1, 7, 10)) == 1  # "outro" track, mesma ocupação


def test_periodo_de_graca_tolera_oclusao_curta():
    t = make(grace=2.0)
    feed(t, 1, 0, 4)
    feed(t, 0, 5, 5)  # zona vazia por <= graça (último frame ocupado em t=4)
    assert len(feed(t, 1, 6, 10)) == 1


def test_zona_vazia_longa_inicia_novo_episodio():
    t = make(grace=2.0)
    assert len(feed(t, 1, 0, 12)) == 1
    feed(t, 0, 13, 20)  # vazia > graça
    assert t.occupied_for("portao") is None
    assert feed(t, 1, 21, 30) == []
    assert len(feed(t, 1, 31, 31)) == 1  # novo episódio, novo alerta


def test_reaparicao_sem_frames_intermediarios_reinicia():
    t = make(grace=2.0)
    t.update({"portao": 1}, now=0)
    assert t.update({"portao": 1}, now=50) == []
    assert t.occupied_for("portao") == 0


def test_zonas_independentes():
    t = OccupancyTracker({"portao": 5, "garagem": 20}, grace_period_s=2)
    hits = []
    for now in range(0, 6):
        hits += t.update({"portao": 2, "garagem": 1}, now=now)
    assert [h.zone for h in hits] == ["portao"]


def test_limiar_padrao_para_zona_sem_config():
    assert make().threshold("garagem") == 99
