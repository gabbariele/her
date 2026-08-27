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


def test_render_without_events_still_cuts_using_the_audio(tmp_path):
    d = _session(tmp_path, [], host_spans=[(1, 2)], guest_spans=[(4, 5)], length=10.0)
    (d / "events.jsonl").write_text("", encoding="utf-8")
    result = render_session(d, RenderConfig(mp3=False))
    assert result.derived_timeline
    assert result.duration < 5.0                       # non più i 10 secondi interi
    assert result.raw_duration == 10.0


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


def test_the_greeting_is_left_out_of_the_montage(tmp_path):
    events = [
        {"speaker": "guest", "start": 0.5, "end": 2.5, "text": "Ciao, eccomi!", "kind": "greeting"},
        {"speaker": "host", "start": 4.0, "end": 6.0, "text": "prima domanda"},
        {"speaker": "guest", "start": 8.0, "end": 10.0, "text": "prima risposta"},
    ]
    d = _session(tmp_path, events, host_spans=[(4, 6)], guest_spans=[(0.5, 2.5), (8, 10)], length=12.0)

    montato = render_session(d, RenderConfig(mp3=False))
    assert [s["text"] for s in montato.segments] == ["prima domanda", "prima risposta"]
    assert "eccomi" not in montato.transcript.read_text(encoding="utf-8")
    # ma nella registrazione integrale il saluto c'è ancora
    integrale, _ = read_wav(montato.full)
    assert np.max(np.abs(integrale[int(1 * SR):int(2 * SR)])) > 1000

    tenuto = render_session(d, RenderConfig(mp3=False, drop_greeting=False))
    assert len(tenuto.segments) == 3


def _rumore(seconds, ampiezza, seed):
    rng = np.random.default_rng(seed)
    return (rng.normal(0, ampiezza, int(seconds * SR))).astype(np.int16)


def _sessione_sbilanciata(tmp_path, ampiezza_host=900, ampiezza_guest=7000):
    """Microfono basso, voce sintetica alta: la situazione tipica."""
    host = np.zeros(20 * SR, dtype=np.int16)
    guest = np.zeros(20 * SR, dtype=np.int16)
    host[2 * SR:5 * SR] = _rumore(3, ampiezza_host, 1)
    guest[8 * SR:12 * SR] = _rumore(4, ampiezza_guest, 2)
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"speaker": "host", "start": 2, "end": 5, "text": "domanda"}) + "\n"
        + json.dumps({"speaker": "guest", "start": 8, "end": 12, "text": "risposta"}) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def test_the_two_voices_come_out_balanced(tmp_path):
    from her.render import speech_level_dbfs

    d = _sessione_sbilanciata(tmp_path)
    result = render_session(d, RenderConfig(mp3=False))

    # prima: il microfono era ~18 dB sotto la voce dell'ospite
    assert result.levels.gap_db > 12
    assert result.levels.host_gain_db > result.levels.guest_gain_db

    montato, _ = read_wav(result.wav)
    parti = [(s["start"], s["end"], s["speaker"]) for s in result.segments]
    livelli = {
        speaker: speech_level_dbfs(montato, SR, [(a, b)])
        for a, b, speaker in parti
    }
    # dopo: le due voci stanno entro 3 dB l'una dall'altra
    assert abs(livelli["host"] - livelli["guest"]) < 3.0


def test_balancing_can_be_turned_off(tmp_path):
    d = _sessione_sbilanciata(tmp_path)
    result = render_session(d, RenderConfig(mp3=False, match_loudness=False))
    assert result.levels.host_gain_db == 0.0 and result.levels.guest_gain_db == 0.0
    # i livelli vengono comunque misurati e riportati
    assert result.levels.gap_db > 12


def test_correction_is_capped_so_noise_is_not_amplified(tmp_path):
    d = _sessione_sbilanciata(tmp_path, ampiezza_host=8)      # microfono quasi muto
    result = render_session(d, RenderConfig(mp3=False, max_match_db=18.0))
    assert result.levels.host_gain_db <= 18.0 + 1e-6


def test_manual_trim_still_works_on_top(tmp_path):
    d = _sessione_sbilanciata(tmp_path)
    pari = render_session(d, RenderConfig(mp3=False))
    piu_alto = render_session(d, RenderConfig(mp3=False, host_gain_db=6.0))
    assert abs((piu_alto.levels.host_gain_db - pari.levels.host_gain_db) - 6.0) < 1e-6


def test_the_full_recording_is_balanced_too(tmp_path):
    from her.render import speech_level_dbfs, write_full_mix

    d = _sessione_sbilanciata(tmp_path)
    integrale, _ = read_wav(write_full_mix(d))
    host = speech_level_dbfs(integrale, SR, [(2, 5)])
    guest = speech_level_dbfs(integrale, SR, [(8, 12)])
    assert abs(host - guest) < 3.0


def test_a_silent_track_does_not_poison_the_mix(tmp_path):
    """Microfono staccato: il montato deve restare valido, non diventare rumore."""
    host = np.zeros(10 * SR, dtype=np.int16)                 # nessun segnale
    guest = np.zeros(10 * SR, dtype=np.int16)
    guest[2 * SR:5 * SR] = _rumore(3, 6000, 3)
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"speaker": "host", "start": 0.5, "end": 1.5, "text": "muto"}) + "\n"
        + json.dumps({"speaker": "guest", "start": 2, "end": 5, "text": "risposta"}) + "\n",
        encoding="utf-8",
    )
    result = render_session(tmp_path, RenderConfig(mp3=False))
    audio, _ = read_wav(result.wav)
    assert np.all(np.isfinite(audio.astype(np.float64)))
    assert np.max(np.abs(audio)) > 25000                     # la voce dell'ospite c'è


def test_untranscribed_turns_stay_in_the_montage(tmp_path):
    events = [
        {"speaker": "host", "start": 1.0, "end": 2.0, "text": "", "kind": "unclear"},
        {"speaker": "host", "start": 4.0, "end": 6.0, "text": "prima domanda"},
        {"speaker": "guest", "start": 8.0, "end": 10.0, "text": "risposta"},
    ]
    d = _session(tmp_path, events, host_spans=[(1, 2), (4, 6)], guest_spans=[(8, 10)], length=12.0)
    result = render_session(d, RenderConfig(mp3=False))

    assert len(result.segments) == 3                      # il «buongiorno» c'è ancora
    assert result.segments[0]["src_start"] == 1.0
    assert "(non trascritto)" in result.transcript.read_text(encoding="utf-8")


def test_speech_outside_the_recognised_turns_is_reported(tmp_path):
    from her.render import unmatched_host_seconds

    host = np.zeros(20 * SR, dtype=np.int16)
    host[1 * SR:3 * SR] = _rumore(2, 6000, 4)          # un "buongiorno" mai riconosciuto
    host[10 * SR:13 * SR] = _rumore(3, 6000, 5)        # un turno regolare
    events = [{"speaker": "host", "start": 10.0, "end": 13.0, "text": "domanda"}]

    perso = unmatched_host_seconds(host, events, SR)
    assert 1.5 < perso < 2.5
    # se il turno è riconosciuto, non risulta perso niente
    events.append({"speaker": "host", "start": 1.0, "end": 3.0, "text": "buongiorno"})
    assert unmatched_host_seconds(host, events, SR) < 0.3


def test_speech_the_transcript_lost_is_put_back(tmp_path):
    """Il montaggio non deve dipendere da cosa ha capito lo STT."""
    host = np.zeros(20 * SR, dtype=np.int16)
    guest = np.zeros(20 * SR, dtype=np.int16)
    host[1 * SR:3 * SR] = _rumore(2, 6000, 11)          # "buongiorno" mai trascritto
    host[12 * SR:15 * SR] = _rumore(3, 6000, 12)        # turno regolare
    guest[5 * SR:8 * SR] = _rumore(3, 6000, 13)
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"speaker": "guest", "start": 5, "end": 8, "text": "risposta"}) + "\n"
        + json.dumps({"speaker": "host", "start": 12, "end": 15, "text": "domanda"}) + "\n",
        encoding="utf-8")

    result = render_session(tmp_path, RenderConfig(mp3=False))
    assert len(result.recovered) == 1
    ripreso = result.recovered[0]
    assert ripreso["start"] < 1.2 and ripreso["end"] > 2.8      # con un po' di margine
    assert [s["speaker"] for s in result.segments] == ["host", "guest", "host"]
    assert "(non trascritto)" in result.transcript.read_text(encoding="utf-8")


def test_recovered_pieces_never_duplicate_a_recognised_turn(tmp_path):
    host = np.zeros(12 * SR, dtype=np.int16)
    host[2 * SR:6 * SR] = _rumore(4, 6000, 14)
    guest = np.zeros(12 * SR, dtype=np.int16)
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    # la trascrizione ha riconosciuto solo metà di quel turno
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"speaker": "host", "start": 2, "end": 4, "text": "prima metà"}) + "\n",
        encoding="utf-8")

    result = render_session(tmp_path, RenderConfig(mp3=False))
    pezzi = sorted((s["src_start"], s["src_end"]) for s in result.segments)
    for (a1, b1), (a2, b2) in zip(pezzi, pezzi[1:]):
        assert b1 <= a2 + 1e-6                                   # nessuna sovrapposizione
    assert sum(b - a for a, b in pezzi) > 3.5                    # ma il turno c'è tutto


def test_the_guests_voice_bleeding_into_the_mic_is_not_recovered(tmp_path):
    """Senza cuffie il microfono risente l'ospite: non va rimessa la sua voce."""
    host = np.zeros(12 * SR, dtype=np.int16)
    guest = np.zeros(12 * SR, dtype=np.int16)
    guest[3 * SR:7 * SR] = _rumore(4, 7000, 15)
    host[3 * SR:7 * SR] = _rumore(4, 2000, 16)          # rientro nel microfono
    host[9 * SR:11 * SR] = _rumore(2, 6000, 17)         # e una frase vera
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"speaker": "guest", "start": 3, "end": 7, "text": "risposta"}) + "\n",
        encoding="utf-8")

    result = render_session(tmp_path, RenderConfig(mp3=False))
    assert len(result.recovered) == 1
    assert result.recovered[0]["start"] > 7.0           # solo la frase vera
    # se lo si chiede esplicitamente, invece, si recupera anche il sovrapposto
    con_sovrapposti = render_session(tmp_path, RenderConfig(mp3=False, recover_over_guest=True))
    assert len(con_sovrapposti.recovered) == 2


def test_a_lost_timeline_is_rebuilt_from_the_audio(tmp_path):
    """Se events.jsonl sparisce, il montaggio non deve rinunciare a tagliare."""
    host = np.zeros(30 * SR, dtype=np.int16)
    guest = np.zeros(30 * SR, dtype=np.int16)
    host[2 * SR:5 * SR] = _rumore(3, 6000, 21)
    guest[12 * SR:17 * SR] = _rumore(5, 6000, 22)
    host[24 * SR:26 * SR] = _rumore(2, 6000, 23)
    write_wav(tmp_path / "host.wav", host, SR)
    write_wav(tmp_path / "guest.wav", guest, SR)
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")

    result = render_session(tmp_path, RenderConfig(mp3=False))
    assert result.derived_timeline
    assert [s["speaker"] for s in result.segments] == ["host", "guest", "host"]
    assert result.duration < 14.0                      # i vuoti sono stati tagliati
    assert result.raw_duration == 30.0


def test_two_silent_tracks_still_produce_a_file(tmp_path):
    write_wav(tmp_path / "host.wav", np.zeros(5 * SR, dtype=np.int16), SR)
    write_wav(tmp_path / "guest.wav", np.zeros(5 * SR, dtype=np.int16), SR)
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    result = render_session(tmp_path, RenderConfig(mp3=False))
    assert not result.derived_timeline and result.wav.exists()
