import json

import numpy as np

from her.audio.wavio import read_wav, write_wav
from her.config import RenderConfig
from her.render import plan_timeline, render_session

SR = 24000


def _session(tmp_path, events, host_spans=(), guest_spans=(), length=30.0):
    host = np.zeros(int(length * SR), dtype=np.int16)
    guest = np.zeros(int(length * SR), dtype=np.int16)
    for a, b in host_spans:
        host[int(a * SR):int(b * SR)] = 6000
    for a, b in guest_spans:
        guest[int(a * SR):int(b * SR)] = 5000
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_plan_compresses_dead_air():
    events = [
        {"speaker": "host", "start": 1.0, "end": 3.0, "text": "domanda"},
        {"speaker": "guest", "start": 8.0, "end": 11.0, "text": "risposta"},
    ]
    plan = plan_timeline(events, RenderConfig(max_gap_s=0.5, lead_in_s=0.0))
    assert plan[0]["start"] == 0.0 and plan[0]["end"] == 2.0
    assert plan[1]["start"] == 2.5          # 5s di attesa ridotti a 0.5
    assert plan[1]["end"] == 5.5


def test_plan_keeps_short_pauses_as_they_are():
    events = [
        {"speaker": "host", "start": 0.0, "end": 2.0, "text": "a"},
        {"speaker": "guest", "start": 2.2, "end": 3.0, "text": "b"},
    ]
    plan = plan_timeline(events, RenderConfig(max_gap_s=1.0, lead_in_s=0.0))
    assert abs(plan[1]["start"] - 2.2) < 1e-6


def test_plan_preserves_overlap():
    events = [
        {"speaker": "guest", "start": 0.0, "end": 4.0, "text": "monologo"},
        {"speaker": "host", "start": 3.0, "end": 5.0, "text": "interruzione"},
    ]
    plan = plan_timeline(events, RenderConfig(max_gap_s=0.4, lead_in_s=0.0))
    assert plan[1]["start"] < plan[0]["end"]


def test_render_produces_shorter_audio_and_texts(tmp_path):
    events = [
        {"speaker": "host", "start": 1.0, "end": 3.0, "text": "domanda"},
        {"speaker": "guest", "start": 8.0, "end": 11.0, "text": "risposta"},
        {"speaker": "host", "start": 20.0, "end": 21.0, "text": "grazie"},
    ]
    d = _session(tmp_path, events, host_spans=[(1, 3), (20, 21)], guest_spans=[(8, 11)])
    result = render_session(d, RenderConfig(max_gap_s=0.45, mp3=False))

    assert result.raw_duration == 30.0
    assert 7.0 < result.duration < 9.0
    assert result.saved > 20.0

    audio, rate = read_wav(result.wav)
    assert rate == SR
    assert np.max(np.abs(audio)) > 25000            # normalizzato vicino al fondo scala
    assert audio.size == int(round(result.duration * SR))

    transcript = result.transcript.read_text(encoding="utf-8")
    assert "domanda" in transcript and "risposta" in transcript
    srt = result.srt.read_text(encoding="utf-8")
    assert "-->" in srt and srt.startswith("1\n")


def test_render_without_events_falls_back_to_full_mix(tmp_path):
    d = _session(tmp_path, [], host_spans=[(1, 2)], guest_spans=[(4, 5)], length=10.0)
    (d / "events.jsonl").write_text("", encoding="utf-8")
    result = render_session(d, RenderConfig(mp3=False))
    assert abs(result.duration - 10.0) < 0.01


def test_gains_are_applied(tmp_path):
    events = [
        {"speaker": "host", "start": 0.0, "end": 1.0, "text": "a"},
        {"speaker": "guest", "start": 1.0, "end": 2.0, "text": "b"},
    ]
    d = _session(tmp_path, events, host_spans=[(0, 1)], guest_spans=[(1, 2)], length=3.0)
    result = render_session(d, RenderConfig(mp3=False, guest_gain_db=-12.0, lead_in_s=0.0))
    audio, _ = read_wav(result.wav)
    host_peak = int(np.max(np.abs(audio[: SR])))
    guest_peak = int(np.max(np.abs(audio[SR: 2 * SR])))
    assert guest_peak < host_peak / 2


def test_full_recording_is_always_written(tmp_path):
    events = [
        {"speaker": "host", "start": 1.0, "end": 3.0, "text": "domanda"},
        {"speaker": "guest", "start": 8.0, "end": 11.0, "text": "risposta"},
    ]
    d = _session(tmp_path, events, host_spans=[(1, 3)], guest_spans=[(8, 11)], length=15.0)
    result = render_session(d, RenderConfig(mp3=False))

    integrale, rate = read_wav(result.full)
    assert result.full.name == "registrazione-integrale.wav"
    assert rate == SR
    assert abs(integrale.size / SR - 15.0) < 0.01        # dura quanto la sessione vera
    # contiene entrambe le voci, ai loro tempi originali
    assert np.max(np.abs(integrale[int(1.5 * SR):int(2.5 * SR)])) > 1000
    assert np.max(np.abs(integrale[int(9 * SR):int(10 * SR)])) > 1000
    assert np.max(np.abs(integrale[int(5 * SR):int(6 * SR)])) == 0   # il silenzio resta
    # il montato invece è più corto
    assert result.duration < result.raw_duration


def test_latest_session_is_found_for_monta_bat(tmp_path, monkeypatch):
    """`her render` senza argomenti (cioè monta.bat) prende l'ultima puntata."""
    from her.cli import latest_session

    root = tmp_path / "sessions"
    for name in ("20260101-100000", "20260102-100000"):
        (root / name).mkdir(parents=True)
        write_wav(root / name / "host.wav", np.zeros(SR, dtype=np.int16), SR)
    # una cartella senza registrazione non è una puntata
    (root / "appunti").mkdir()

    import os
    os.utime(root / "20260101-100000", (1_000_000, 1_000_000))    # la vecchia
    os.utime(root / "20260102-100000", (2_000_000, 2_000_000))    # la più recente
    assert latest_session(str(root)).name == "20260102-100000"
    assert latest_session(str(tmp_path / "vuoto")) is None


def test_sessions_report_flags_a_missing_montage(tmp_path, capsys):
    from her.cli import cmd_sessions

    class Args:
        sessions = str(tmp_path / "sessions")

    d = _session(tmp_path / "sessions" / "20260826-2100", [], host_spans=[(0, 1)], length=2.0)
    (d / "registrazione-integrale.wav").write_bytes(b"RIFF")
    cmd_sessions(Args())
    out = capsys.readouterr().out
    assert "host.wav" in out and "registrazione-integrale.wav" in out
    assert "MANCA" in out and "podcast.wav" in out
    assert "monta.bat" in out
