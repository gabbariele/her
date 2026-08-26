import pytest

from her.config import Config, load_config, load_env


def test_defaults_are_consistent():
    cfg = Config().sync()
    assert cfg.vad.sample_rate == cfg.audio.sample_rate
    assert cfg.vad.frame_len == cfg.audio.sample_rate * cfg.audio.frame_ms // 1000


def test_preset_by_name_from_presets_dir():
    cfg = load_config("intervista")
    assert cfg.persona.name == "Nova"
    assert cfg.llm.provider == "openai"


def test_overrides_win_over_preset():
    cfg = load_config("intervista", {"tts": {"voice_id": "xyz"}, "llm": {"model": "gpt-4o-mini"}})
    assert cfg.tts.voice_id == "xyz"
    assert cfg.llm.model == "gpt-4o-mini"
    assert cfg.persona.name == "Nova"          # il resto del preset resta


def test_unknown_key_is_an_error():
    with pytest.raises(ValueError, match="sconosciuta"):
        load_config(overrides={"llm": {"banana": 1}})


def test_missing_preset_is_an_error():
    with pytest.raises(FileNotFoundError):
        load_config("non-esiste")


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('OPENAI_API_KEY="dal-file"\nHER_TEST_X=1\n# commento\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "gia-presente")
    monkeypatch.delenv("HER_TEST_X", raising=False)
    load_env(env)
    import os

    assert os.environ["OPENAI_API_KEY"] == "gia-presente"
    assert os.environ["HER_TEST_X"] == "1"
