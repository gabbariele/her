import numpy as np

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
