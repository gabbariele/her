import numpy as np
import pytest

from her.audio.recorder import MultitrackRecorder, read_events
from her.audio.wavio import read_wav, wav_bytes, write_wav

SR = 24000


def test_wav_roundtrip(tmp_path):
    data = (np.sin(np.arange(SR) / 20) * 10000).astype(np.int16)
    path = write_wav(tmp_path / "a.wav", data, SR)
    back, rate = read_wav(path)
    assert rate == SR
    assert np.array_equal(back, data)


def test_wav_bytes_is_a_valid_wav():
    blob = wav_bytes(np.zeros(100, dtype=np.int16), SR)
    assert blob[:4] == b"RIFF" and blob[8:12] == b"WAVE"


def test_guest_is_placed_on_the_host_clock(tmp_path):
    rec = MultitrackRecorder(tmp_path, SR)
    rec.write_host(np.ones(2 * SR, dtype=np.int16))          # 2s di conduttore
    start, end = rec.write_guest(np.ones(SR, dtype=np.int16))  # 1s di ospite
    assert (start, end) == (2.0, 3.0)
    rec.close()

    host, _ = read_wav(tmp_path / "host.wav")
    guest, _ = read_wav(tmp_path / "guest.wav")
    assert host.size == guest.size                            # tracce allineate
    assert np.all(guest[: 2 * SR] == 0)                       # silenzio prima del turno
    assert np.all(guest[2 * SR: 3 * SR] == 1)


def test_events_are_sorted_and_reread(tmp_path):
    rec = MultitrackRecorder(tmp_path, SR, wall_clock=True)
    rec.log_event("guest", 5.0, 6.0, "seconda")
    rec.log_event("host", 1.0, 2.0, "prima")
    rec.close()
    events = read_events(tmp_path)
    assert [e["text"] for e in events] == ["prima", "seconda"]


def test_writes_after_close_are_ignored(tmp_path):
    rec = MultitrackRecorder(tmp_path, SR)
    rec.close()
    assert rec.write_guest(np.ones(10, dtype=np.int16)) == (0.0, 0.0)


def test_resuming_keeps_what_was_already_recorded(tmp_path):
    prima = MultitrackRecorder(tmp_path, SR)
    prima.write_host(np.full(2 * SR, 111, dtype=np.int16))
    prima.write_guest(np.full(SR, 222, dtype=np.int16))
    prima.log_event("host", 0.0, 2.0, "prima parte")
    prima.close()

    ripresa = MultitrackRecorder(tmp_path, SR, resume=True)
    assert abs(ripresa.resumed_from - 3.0) < 0.01          # riparte dalla fine
    assert abs(ripresa.now() - 3.0) < 0.01
    ripresa.write_host(np.full(SR, 33, dtype=np.int16))
    ripresa.log_event("host", 3.0, 4.0, "seconda parte")
    ripresa.close()

    host, _ = read_wav(tmp_path / "host.wav")
    guest, _ = read_wav(tmp_path / "guest.wav")
    assert host.size == guest.size == 4 * SR
    assert np.all(host[: 2 * SR] == 111)                   # la prima parte c'è
    assert np.all(host[3 * SR: 4 * SR] == 33)              # e la seconda pure
    assert np.all(guest[2 * SR: 3 * SR] == 222)
    assert [e["text"] for e in read_events(tmp_path)] == ["prima parte", "seconda parte"]
    assert not list(tmp_path.glob("*.bak"))                # niente copie lasciate in giro


def test_resuming_a_session_that_does_not_exist_starts_fresh(tmp_path):
    rec = MultitrackRecorder(tmp_path / "nuova", SR, resume=True)
    assert rec.resumed_from == 0.0
    rec.write_host(np.zeros(SR, dtype=np.int16))
    rec.close()
    assert (tmp_path / "nuova" / "host.wav").exists()


def test_resuming_at_a_different_sample_rate_is_refused(tmp_path):
    prima = MultitrackRecorder(tmp_path, 16000)
    prima.write_host(np.zeros(16000, dtype=np.int16))
    prima.close()
    with pytest.raises(ValueError, match="non posso riprendere"):
        MultitrackRecorder(tmp_path, SR, resume=True)
