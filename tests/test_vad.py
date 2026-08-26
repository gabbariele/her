import numpy as np

from her.audio.vad import Endpointer, VadConfig, rms_dbfs

CFG = VadConfig(sample_rate=16000, frame_ms=20, calibration_s=0.2,
                silence_ms=200, min_speech_ms=100, preroll_ms=100)


def _feed(ep, audio):
    events = []
    for i in range(0, len(audio) - CFG.frame_len + 1, CFG.frame_len):
        ev = ep.push(audio[i:i + CFG.frame_len])
        if ev:
            events.append(ev)
    return events


def _noise(frames, rng):
    return rng.normal(0, 60, frames * CFG.frame_len).astype(np.int16)


def _speech(frames, rng):
    return rng.normal(0, 6000, frames * CFG.frame_len).astype(np.int16)


def test_rms_dbfs_scale():
    assert rms_dbfs(np.zeros(160, dtype=np.int16)) < -100
    assert rms_dbfs(np.full(160, 32767, dtype=np.int16)) > -0.1


def test_detects_one_utterance():
    rng = np.random.default_rng(0)
    ep = Endpointer(CFG)
    events = _feed(ep, np.concatenate([_noise(40, rng), _speech(50, rng), _noise(40, rng)]))
    kinds = [e[0] for e in events]
    assert kinds == ["start", "end"]
    audio = events[1][1]
    # 1s di parlato + preroll, senza la coda di silenzio
    assert 0.9 < audio.size / CFG.sample_rate < 1.5


def test_silence_only_produces_nothing():
    rng = np.random.default_rng(1)
    ep = Endpointer(CFG)
    assert _feed(ep, _noise(200, rng)) == []


def test_short_click_is_ignored():
    rng = np.random.default_rng(2)
    ep = Endpointer(CFG)
    events = _feed(ep, np.concatenate([_noise(40, rng), _speech(2, rng), _noise(60, rng)]))
    assert events == []


def test_two_utterances():
    rng = np.random.default_rng(3)
    ep = Endpointer(CFG)
    audio = np.concatenate([_noise(40, rng), _speech(30, rng), _noise(30, rng),
                            _speech(30, rng), _noise(30, rng)])
    assert [e[0] for e in _feed(ep, audio)] == ["start", "end", "start", "end"]


def test_flush_closes_open_utterance():
    rng = np.random.default_rng(4)
    ep = Endpointer(CFG)
    _feed(ep, np.concatenate([_noise(40, rng), _speech(30, rng)]))
    assert ep.speaking
    tail = ep.flush()
    assert tail is not None and tail.size > 0
    assert not ep.speaking
