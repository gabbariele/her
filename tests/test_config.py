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


def test_voice_id_can_come_from_the_environment(monkeypatch):
    from her.cli import _load

    class Args:
        preset = None
        context = None

    monkeypatch.setenv("HER_VOICE_ID", "voce-dal-env")
    assert _load(Args()).tts.voice_id == "voce-dal-env"


def test_preset_voice_wins_over_the_environment(monkeypatch, tmp_path):
    from her.cli import _load

    preset = tmp_path / "p.yaml"
    preset.write_text("tts:\n  voice_id: dal-preset\n", encoding="utf-8")

    class Args:
        context = None

    Args.preset = str(preset)
    monkeypatch.setenv("HER_VOICE_ID", "voce-dal-env")
    assert _load(Args()).tts.voice_id == "dal-preset"


def test_placeholder_keys_count_as_missing(monkeypatch):
    from her.config import api_key

    monkeypatch.setenv("HER_TEST_KEY", "sk-...")
    assert api_key("HER_TEST_KEY") is None
    monkeypatch.setenv("HER_TEST_KEY", "  sk-vera123  ")
    assert api_key("HER_TEST_KEY") == "sk-vera123"


def test_mixing_provider_and_model_is_caught_early():
    import pytest

    with pytest.raises(ValueError, match="è di openai"):
        load_config(overrides={"stt": {"provider": "gemini"}})       # modello di default = gpt-4o-transcribe
    with pytest.raises(ValueError, match="è di gemini"):
        load_config(overrides={"llm": {"model": "gemini-3.5-flash"}})  # provider di default = openai


def test_gemini_preset_is_coherent():
    cfg = load_config("gemini")
    assert cfg.stt.provider == "gemini" and cfg.stt.model.startswith("gemini")
    assert cfg.llm.provider == "gemini" and cfg.llm.model.startswith("gemini")
    assert cfg.llm.thinking in ("off", False)


def test_switching_provider_switches_the_model_too():
    from her.cli import _overrides

    class Args:
        stt = "gemini"
        llm = "gemini"
        stt_model = None
        llm_model = "gemini-2.5-flash"

    out = _overrides(Args())
    assert out["stt"]["model"].startswith("gemini")     # scelto per noi
    assert out["llm"]["model"] == "gemini-2.5-flash"    # quello chiesto esplicitamente


def test_pause_can_be_set_from_command_line_and_env(monkeypatch):
    from her.cli import _load, _overrides

    class Args:
        preset = "gemini"
        context = None
        pausa = 2.5

    assert _overrides(Args())["vad"]["silence_ms"] == 2500
    assert _load(Args()).vad.silence_ms == 2500

    Args.pausa = None
    monkeypatch.setenv("HER_PAUSA", "2")
    assert _load(Args()).vad.silence_ms == 2000        # dal .env
    monkeypatch.setenv("HER_PAUSA", "un-po-tanto")
    with pytest.raises(ValueError, match="HER_PAUSA"):
        _load(Args())


def test_presets_speak_italian_to_elevenlabs():
    for name in ("gemini", "intervista", "veloce", "esperto-tech"):
        assert load_config(name).tts.language == "it", name


def test_persona_rules_are_appended_to_the_prompt():
    cfg = load_config("gemini")
    prompt = cfg.persona.effective_prompt()
    assert cfg.persona.system_prompt.strip() in prompt
    assert "LUNGHEZZA:" in prompt and "4-6 frasi" in prompt
    assert "DOMANDE:" in prompt and "una risposta su tre" in prompt
    # e la regola che tiene le risposte diverse fra loro c'è sempre
    assert "VARIETÀ:" in prompt


def test_short_and_talkative_are_really_different():
    breve = load_config("gemini", {"persona": {"length": "breve", "questions": "spesso"}})
    lungo = load_config("gemini", {"persona": {"length": "monologo", "questions": "mai"}})
    assert "2 o 3 frasi" in breve.persona.effective_prompt()
    assert "rilanciando con una domanda" in breve.persona.effective_prompt()
    assert "due o tre minuti" in lungo.persona.effective_prompt()
    assert "non fare domande" in lungo.persona.effective_prompt().lower()


def test_token_ceiling_never_truncates_the_requested_length():
    cfg = load_config("gemini", {"persona": {"length": "monologo"}, "llm": {"max_output_tokens": 100}})
    assert cfg.llm.max_output_tokens >= 1600          # alzato al minimo che serve
    corto = load_config("gemini", {"persona": {"length": "breve"}, "llm": {"max_output_tokens": 4000}})
    assert corto.llm.max_output_tokens == 4000        # una scelta esplicita più alta resta


def test_invalid_length_says_what_is_allowed():
    with pytest.raises(ValueError, match="breve, media, lunga, monologo"):
        load_config("gemini", {"persona": {"length": "chilometrica"}})


def test_length_and_questions_from_the_env(monkeypatch):
    from her.cli import _load

    class Args:
        preset = "gemini"
        context = None
        pausa = None
        lunghezza = None
        domande = None

    monkeypatch.setenv("HER_LUNGHEZZA", "monologo")
    monkeypatch.setenv("HER_DOMANDE", "mai")
    cfg = _load(Args())
    assert cfg.persona.length == "monologo" and cfg.persona.questions == "mai"
    assert cfg.llm.max_output_tokens >= 1600

    Args.lunghezza = "breve"                          # la riga di comando vince sul .env
    assert _load(Args()).persona.length == "breve"
