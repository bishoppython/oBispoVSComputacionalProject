from vigia.rules.identity import IdentityCfg, IdentityTracker, iou

BOX = (100, 100, 200, 400)


def tracker(**kw):
    return IdentityTracker(IdentityCfg(**kw))


def test_conhecido_so_apos_varios_votos():
    t = tracker(known_votes=3)
    t.update({1: BOX}, 0)
    assert t.observe(1, "Ana", 0.6, 0.1) is None
    assert t.observe(1, "Ana", 0.55, 0.4) is None
    hit = t.observe(1, "Ana", 0.7, 0.7)
    assert hit.kind == "known" and hit.name == "Ana" and hit.similarity == 0.7
    assert t.observe(1, "Ana", 0.6, 1.0) is None  # não repete


def test_desconhecido_exige_votos_e_nenhum_acerto():
    t = tracker(unknown_votes=3, known_votes=3)
    t.update({1: BOX}, 0)
    t.observe(1, "Ana", 0.5, 0.1)  # um acerto na janela bloqueia o "desconhecido"
    for i in range(5):
        assert t.observe(1, None, 0.1, 0.2 + i) is None

    t2 = tracker(unknown_votes=3)
    t2.update({2: BOX}, 0)
    t2.observe(2, None, 0.1, 0.1)
    t2.observe(2, "Ana", 0.2, 0.2)  # nome abaixo do limiar conta como desconhecido
    hit = t2.observe(2, None, 0.15, 0.3)
    assert hit.kind == "unknown" and hit.name is None


def test_zona_cinzenta_nao_vota():
    t = tracker(unknown_votes=2)
    t.update({1: BOX}, 0)
    for i in range(10):
        assert t.observe(1, "Ana", 0.38, i) is None  # entre 0.30 e 0.45
    assert t.get(1).status == "pending"


def test_nao_identificado_apos_tempo_sem_decisao():
    t = tracker(unidentified_after_s=20)
    assert t.update({1: BOX}, 0) == []
    assert t.update({1: BOX}, 19) == []
    [hit] = t.update({1: BOX}, 21)
    assert hit.kind == "unidentified" and hit.present_s == 21
    assert t.update({1: BOX}, 40) == []  # uma vez só


def test_identificado_nao_vira_nao_identificado():
    t = tracker(unidentified_after_s=5, known_votes=1)
    t.update({1: BOX}, 0)
    t.observe(1, "Ana", 0.6, 1)
    assert t.update({1: BOX}, 30) == []


def test_troca_de_id_herda_identidade_sem_novo_alerta():
    t = tracker(known_votes=1, forget_after_s=1, unidentified_after_s=5)
    t.update({1: BOX}, 0)
    t.observe(1, "Ana", 0.6, 0.5)
    t.update({}, 2)  # track 1 perdido
    t.update({7: (105, 110, 205, 405)}, 3)  # reaparece com outro ID no mesmo lugar
    ana = t.get(7)
    assert ana.status == "known" and ana.name == "Ana"
    assert t.update({7: (105, 110, 205, 405)}, 30) == []


def test_track_novo_longe_nao_herda():
    t = tracker(known_votes=1, forget_after_s=1)
    t.update({1: BOX}, 0)
    t.observe(1, "Ana", 0.6, 0.5)
    t.update({}, 2)
    t.update({8: (800, 100, 900, 400)}, 3)
    assert t.get(8).status == "pending"


def test_ritmo_de_amostragem():
    t = tracker(sample_interval_s=0.3, recheck_interval_s=2.0, known_votes=1)
    t.update({1: BOX}, 0)
    assert t.wants_face(1, 0)
    t.mark_sampled(1, 0)
    assert not t.wants_face(1, 0.2)
    assert t.wants_face(1, 0.31)
    t.observe(1, "Ana", 0.6, 0.31)
    assert not t.wants_face(1, 1.0)  # já decidido: reconfere a cada 2 s
    assert t.wants_face(1, 2.4)


def test_reconhecido_com_outro_nome_troca():
    t = tracker(known_votes=2, window=4)
    t.update({1: BOX}, 0)
    t.observe(1, "Ana", 0.6, 1)
    t.observe(1, "Ana", 0.6, 2)
    t.observe(1, "Bia", 0.7, 3)
    assert t.observe(1, "Bia", 0.7, 4) is None  # empate 2x2: mantém o nome atual
    hit = t.observe(1, "Bia", 0.7, 5)  # janela: Ana, Bia, Bia, Bia
    assert hit.kind == "known" and hit.name == "Bia"


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
