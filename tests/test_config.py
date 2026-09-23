from vigia.config import load_config, parse_source


def test_parse_source():
    assert parse_source("0") == 0
    assert parse_source("rtsp://x@1.2.3.4/stream1") == "rtsp://x@1.2.3.4/stream1"


def test_env_sobrescreve_fonte(tmp_path, monkeypatch):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("camera:\n  source: 0\n")
    monkeypatch.setenv("VIGIA_CAMERA_SOURCE", "rtsp://u:p@10.0.0.2:554/stream2")
    cfg, _ = load_config(cfg_file)
    assert cfg.camera.source == "rtsp://u:p@10.0.0.2:554/stream2"


def test_fallback_de_ocupacao_ligado_por_padrao_e_desligavel(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("loitering:\n  grace_period_s: 3\n")
    cfg, _ = load_config(cfg_file)
    assert cfg.loitering.occupancy_fallback is True

    cfg_file.write_text("loitering:\n  occupancy_fallback: false\n")
    cfg, _ = load_config(cfg_file)
    assert cfg.loitering.occupancy_fallback is False
