"""Prova end-to-end della sessione con provider finti: nessuna rete, nessuna scheda audio."""
from __future__ import annotations

import numpy as np
import pytest

from her import session as session_module
from her.audio.recorder import read_events
from her.audio.wavio import read_wav
from her.config import load_config
from her.render import render_session
from her.session import PodcastSession

SR = 24000


class FakePlayer:
    """Sostituisce la scheda audio: consuma i blocchi e li passa al registratore."""

    def __init__(self, sample_rate, device=None, on_audio=None):
        self.on_audio = on_audio
        self.played = []

    def start(self):
        return self

    def play(self, chunks, block_samples=2400):
        for chunk in chunks:
            self.played.append(chunk)
            if self.on_audio:
                self.on_audio(np.asarray(chunk, dtype=np.int16))
        return True

    def stop(self):
        pass

    def close(self):
        pass


def _fake_tts(text, cfg, sample_rate=SR, timeout=60.0):
    """Mezzo secondo di 'voce' per ogni frase."""
    tone = (np.sin(np.arange(sample_rate // 2) / 10) * 8000).astype(np.int16)
    yield tone[: sample_rate // 4]
    yield tone[sample_rate // 4:]


def _fake_llm(system_prompt, history, cfg, timeout=120.0, client=None, notice=None):
    last = history[-1]["content"]
    for token in ["Interessante", " quello che dici su ", last, ". ", "Vuoi che approfondisca?"]:
        yield token


def _raw_events(session_dir):
    import json

    lines = (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(session_module, "Player", FakePlayer)
    monkeypatch.setattr(session_module.tts_provider, "stream_speech", _fake_tts)
    monkeypatch.setattr(session_module.llm_provider, "stream_reply", _fake_llm)


def _run_text_session(tmp_path, monkeypatch, lines):
    it = iter(lines)
    monkeypatch.setattr("builtins.input", lambda *a: next(it, ""))
    cfg = load_config(overrides={"tts": {"voice_id": "fake"}})
    sess = PodcastSession(cfg, tmp_path / "s1", text_input=True)
    sess.run()
    return sess


def test_text_session_records_both_tracks(tmp_path, monkeypatch, patched):
    sess = _run_text_session(tmp_path, monkeypatch, ["Parlami di podcast", "E la latenza?"])
    assert sess.turns == 2

    # ordine di scrittura: il player finto consuma l'audio all'istante, quindi
    # i timestamp della modalità testo sono degeneri e non vanno riordinati
    events = _raw_events(sess.dir)
    assert [e["speaker"] for e in events] == ["host", "guest", "host", "guest"]
    assert "Parlami di podcast" in events[1]["text"]

    host, rate = read_wav(sess.dir / "host.wav")
    guest, _ = read_wav(sess.dir / "guest.wav")
    assert rate == SR
    assert host.size == guest.size              # tracce sempre allineate
    assert np.any(guest != 0)                   # l'ospite ha davvero parlato
    assert np.all(host == 0)                    # in modalità testo il microfono è spento


def test_the_persona_rules_reach_the_model(tmp_path, monkeypatch, patched):
    visti = []

    def _spia(system_prompt, history, cfg, **kw):
        visti.append(system_prompt)
        yield "va bene"

    monkeypatch.setattr(session_module.llm_provider, "stream_reply", _spia)
    _run_text_session(tmp_path, monkeypatch, ["dimmi qualcosa"])
    assert "LUNGHEZZA:" in visti[0] and "DOMANDE:" in visti[0]


def test_history_alternates_and_is_trimmed(tmp_path, monkeypatch, patched):
    sess = _run_text_session(tmp_path, monkeypatch, ["uno", "due", "tre"])
    roles = [m["role"] for m in sess.history]
    assert roles == ["user", "assistant"] * (len(roles) // 2)
    assert sess.history[-1]["role"] == "assistant"


def test_session_renders_to_a_podcast(tmp_path, monkeypatch, patched):
    sess = _run_text_session(tmp_path, monkeypatch, ["Domanda secca"])
    result = render_session(sess.dir, sess.cfg.render)
    audio, _ = read_wav(result.wav)
    assert audio.size > 0
    assert "Domanda secca" in result.transcript.read_text(encoding="utf-8")


def test_llm_failure_does_not_kill_the_session(tmp_path, monkeypatch, patched):
    def boom(*a, **k):
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(session_module.llm_provider, "stream_reply", boom)
    sess = _run_text_session(tmp_path, monkeypatch, ["ci sei?", "e adesso?"])
    assert sess.turns == 0                       # nessuna risposta registrata
    assert (sess.dir / "host.wav").exists()      # ma la sessione è chiusa bene
    assert [e["speaker"] for e in _raw_events(sess.dir)] == ["host", "host"]


def test_mic_turn_is_transcribed_and_answered(tmp_path, monkeypatch, patched):
    monkeypatch.setattr(
        session_module.stt_provider,
        "transcribe",
        lambda audio, sr, cfg, **kw: "domanda dal microfono",
    )
    cfg = load_config(overrides={"tts": {"voice_id": "fake"}})
    sess = PodcastSession(cfg, tmp_path / "s2")
    sess.recorder.write_host(np.zeros(SR, dtype=np.int16))     # 1s di orologio
    sess._handle_turn(np.ones(SR // 2, dtype=np.int16), 0.5, 1.0)
    sess.close()

    events = read_events(sess.dir)
    assert events[0]["text"] == "domanda dal microfono"
    assert events[1]["speaker"] == "guest"
    assert events[1]["start"] >= events[0]["end"] - 0.5
    assert sess.turns == 1


def test_full_recording_exists_before_any_montage(tmp_path, monkeypatch, patched):
    """La registrazione completa si scrive alla chiusura, non al montaggio:
    se il montaggio non parte (o la finestra viene chiusa), c'è comunque."""
    from her.audio.wavio import read_wav

    sess = _run_text_session(tmp_path, monkeypatch, ["prima domanda", "seconda domanda"])
    integrale = sess.dir / "registrazione-integrale.wav"
    assert integrale.exists()

    audio, rate = read_wav(integrale)
    host, _ = read_wav(sess.dir / "host.wav")
    assert rate == SR
    assert audio.size == host.size          # stessa durata delle tracce
    assert np.any(audio != 0)               # e contiene la voce dell'ospite

    # nessun montaggio è stato eseguito in questo test
    assert not (sess.dir / "podcast.wav").exists()


def test_an_untranscribed_turn_is_not_thrown_away(tmp_path, monkeypatch, patched):
    """Se la trascrizione non capisce, l'audio resta comunque nel montato."""
    monkeypatch.setattr(session_module.stt_provider, "transcribe", lambda audio, sr, cfg, **kw: "   ")
    cfg = load_config(overrides={"tts": {"voice_id": "fake"}})
    sess = PodcastSession(cfg, tmp_path / "s3")
    sess.recorder.write_host(np.zeros(SR, dtype=np.int16))
    sess._handle_turn(np.ones(SR // 2, dtype=np.int16), 0.5, 1.0)
    sess.close()

    events = _raw_events(sess.dir)
    assert len(events) == 1
    assert events[0]["speaker"] == "host" and events[0]["kind"] == "unclear"
    assert events[0]["end"] == 1.0
    assert sess.turns == 0                       # nessuna risposta dell'ospite


def test_resuming_keeps_the_conversation_and_the_audio(tmp_path, monkeypatch, patched):
    """Riprendere = l'ospite si ricorda, e l'audio si aggiunge in coda."""
    from her.audio.wavio import read_wav

    prima = _run_text_session(tmp_path, monkeypatch, ["parliamo di radio"])
    battute_prima = len(prima.history)
    durata_prima = read_wav(prima.dir / "host.wav")[0].size
    assert battute_prima >= 2

    it = iter(["e dei podcast?"])
    monkeypatch.setattr("builtins.input", lambda *a: next(it, ""))
    cfg = load_config(overrides={"tts": {"voice_id": "fake"}})
    dopo = PodcastSession(cfg, prima.dir, text_input=True, resume=True)
    dopo.run()

    # l'ospite sapeva già di cosa si era parlato
    assert dopo.history[0]["content"] == "parliamo di radio"
    assert len(dopo.history) > battute_prima
    # e la traccia si è allungata invece di ripartire da zero
    assert read_wav(dopo.dir / "host.wav")[0].size > durata_prima
    testi = [e["text"] for e in _raw_events(dopo.dir)]
    assert "parliamo di radio" in testi and "e dei podcast?" in testi


def test_the_session_writes_a_log(tmp_path, monkeypatch, patched):
    sess = _run_text_session(tmp_path, monkeypatch, ["una domanda"])
    log = (sess.dir / "sessione.log").read_text(encoding="utf-8")
    assert "avvio" in log and "chiusura regolare" in log


def test_a_broken_turn_is_logged_and_the_session_survives(tmp_path, monkeypatch, patched):
    """Il guasto di un turno non deve fermare la registrazione."""
    chiamate = []

    def a_volte_esplode(audio, sr, cfg, **kw):
        chiamate.append(1)
        if len(chiamate) == 1:
            raise RuntimeError("connessione persa")
        return "seconda domanda"

    monkeypatch.setattr(session_module.stt_provider, "transcribe", a_volte_esplode)
    cfg = load_config(overrides={"tts": {"voice_id": "fake"}})
    sess = PodcastSession(cfg, tmp_path / "s4")
    sess.recorder.write_host(np.zeros(SR, dtype=np.int16))
    sess._handle_turn(np.ones(SR // 2, dtype=np.int16), 0.5, 1.0)     # va storto
    sess._handle_turn(np.ones(SR // 2, dtype=np.int16), 1.5, 2.0)     # e questo no
    sess.close()

    assert sess.turns == 1
    log = (sess.dir / "sessione.log").read_text(encoding="utf-8")
    assert "connessione persa" in log
    assert [e["speaker"] for e in _raw_events(sess.dir)] == ["host", "guest"]


def test_a_dead_microphone_is_reported_not_ignored(tmp_path, monkeypatch, patched):
    """Il thread che ascolta non può morire in silenzio: la sessione sembrerebbe viva."""
    cfg = load_config(overrides={"tts": {"voice_id": "fake"}})
    sess = PodcastSession(cfg, tmp_path / "s5")

    class MicRotto:
        def frames(self, timeout=0.5):
            yield np.zeros(480, dtype=np.int16)
            raise OSError("dispositivo scomparso")

        def close(self):
            pass

    sess._mic = MicRotto()
    sess._mic_loop()
    sess.close()

    assert sess.mic_failed
    log = (sess.dir / "sessione.log").read_text(encoding="utf-8")
    assert "microfono si è fermato" in log and "dispositivo scomparso" in log


def test_the_director_reacts_to_what_the_guest_just_said(tmp_path, monkeypatch, patched):
    """La regia deve agganciarsi alla risposta dell'ospite, non alla domanda."""
    visti = {}

    def finto_llm(system_prompt, history, cfg, **kw):
        visti["system"] = system_prompt
        visti["richiesta"] = history[-1]["content"]
        visti["modello"] = cfg.model
        yield "chiedile se ci crede davvero"

    monkeypatch.setattr("her.suggester.stream_reply", finto_llm)
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-finta")

    cfg = load_config("gemini", {"tts": {"voice_id": "fake"}})
    cfg.persona.briefing = "SCALETTA: si parla di radio libere"
    it = iter(["parliamo di vinile"])
    monkeypatch.setattr("builtins.input", lambda *a: next(it, ""))
    sess = PodcastSession(cfg, tmp_path / "regia", text_input=True)
    sess.run()

    import time
    for _ in range(50):                       # la regia gira in un thread suo
        if sess.suggester.suggestions:
            break
        time.sleep(0.02)

    assert [s.text for s in sess.suggester.suggestions] == ["chiedile se ci crede davvero"]
    # ha visto la risposta dell'ospite, non solo la domanda del conduttore
    assert "Interessante quello che dici su parliamo di vinile" in visti["richiesta"]
    assert "parliamo di vinile" in visti["richiesta"]
    assert visti["richiesta"].rstrip().endswith("La riga da passare al conduttore:")
    # la scaletta invece non gliela diamo: se la legge il conduttore
    assert "radio libere" not in visti["system"]
    assert "ULTIMA risposta dell'ospite" in visti["system"]
    assert visti["modello"] == cfg.suggester.model     # con il suo modello, non quello dell'ospite
    assert "chiedile se ci crede" in (sess.dir / "suggerimenti.md").read_text(encoding="utf-8")


def test_the_outline_can_be_given_to_the_director_on_request(tmp_path, monkeypatch, patched):
    visti = {}

    def finto_llm(system_prompt, history, cfg, **kw):
        visti["system"] = system_prompt
        yield "vai di ironia"

    monkeypatch.setattr("her.suggester.stream_reply", finto_llm)
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-finta")
    cfg = load_config("gemini", {"tts": {"voice_id": "fake"},
                                 "suggester": {"use_briefing": True}})
    cfg.persona.briefing = "SCALETTA: si parla di radio libere"
    it = iter(["ciao"])
    monkeypatch.setattr("builtins.input", lambda *a: next(it, ""))
    sess = PodcastSession(cfg, tmp_path / "regia2", text_input=True)
    sess.run()

    import time
    for _ in range(50):
        if sess.suggester.suggestions:
            break
        time.sleep(0.02)
    assert "radio libere" in visti["system"]


def test_a_broken_director_never_stops_the_recording(tmp_path, monkeypatch, patched):
    def esplode(*a, **k):
        raise RuntimeError("429 quota finita")
        yield  # pragma: no cover

    monkeypatch.setattr("her.suggester.stream_reply", esplode)
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-finta")
    cfg = load_config("gemini", {"tts": {"voice_id": "fake"}})
    sess = _run_text_session_with(tmp_path, monkeypatch, cfg, ["una domanda", "e un'altra"])
    assert sess.turns == 2                                # la puntata è andata avanti


def _run_text_session_with(tmp_path, monkeypatch, cfg, lines):
    it = iter(lines)
    monkeypatch.setattr("builtins.input", lambda *a: next(it, ""))
    sess = PodcastSession(cfg, tmp_path / "sx", text_input=True)
    sess.run()
    return sess


def test_the_director_can_be_switched_off(tmp_path, monkeypatch, patched):
    def mai(*a, **k):  # pragma: no cover - non deve essere chiamato
        raise AssertionError("la regia doveva essere spenta")

    monkeypatch.setattr("her.suggester.stream_reply", mai)
    cfg = load_config("gemini", {"tts": {"voice_id": "fake"}, "suggester": {"enabled": False}})
    sess = _run_text_session_with(tmp_path, monkeypatch, cfg, ["ciao"])
    assert not sess.suggester.available
