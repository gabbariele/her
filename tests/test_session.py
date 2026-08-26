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
