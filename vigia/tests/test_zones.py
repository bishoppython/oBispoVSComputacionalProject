import pytest

from vigia.rules.zones import Zone, load_zones, save_zones

SQUARE = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]]


def test_contains_em_pixels():
    z = Zone(name="a", kind="loitering", polygon=SQUARE)
    assert z.contains((300, 200), w=1000, h=1000)
    assert not z.contains((800, 800), w=1000, h=1000)


def test_independe_da_resolucao():
    z = Zone(name="a", kind="loitering", polygon=SQUARE)
    assert z.contains((150, 100), w=500, h=500)
    assert z.contains((600, 400), w=2000, h=2000)


def test_roundtrip_yaml(tmp_path):
    p = tmp_path / "zones.yaml"
    save_zones(p, [Zone(name="portao", kind="loitering", polygon=SQUARE, threshold_s=30)])
    [z] = load_zones(p)
    assert z.name == "portao" and z.threshold_s == 30


def test_validacoes():
    with pytest.raises(ValueError):
        Zone(name="a", kind="loitering", polygon=[[0, 0], [1, 1]])
    with pytest.raises(ValueError):
        Zone(name="a", kind="invalido", polygon=SQUARE)
