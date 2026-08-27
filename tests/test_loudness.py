"""Misura del volume percepito e compressione."""
from __future__ import annotations

import numpy as np

from her.audio.loudness import compress, loudness_lufs

SR = 24000


def _rumore(seconds, ampiezza, seed):
    rng = np.random.default_rng(seed)
    return (rng.normal(0, ampiezza, int(seconds * SR))).astype(np.int16)


def test_louder_material_measures_louder():
    piano = loudness_lufs(_rumore(5, 800, 1), SR)
    forte = loudness_lufs(_rumore(5, 8000, 1), SR)
    assert forte - piano > 15


def test_silence_has_no_loudness():
    assert loudness_lufs(np.zeros(SR, dtype=np.int16), SR) is None
    assert loudness_lufs(np.zeros(0, dtype=np.int16), SR) is None


def test_pauses_do_not_drag_the_measure_down():
    """Il cancello relativo esiste per questo: i silenzi non contano."""
    voce = _rumore(5, 3000, 2)
    con_pause = np.zeros(15 * SR, dtype=np.int16)
    con_pause[: voce.size] = voce                    # 5s di voce e 10s di silenzio
    assert abs(loudness_lufs(voce, SR) - loudness_lufs(con_pause, SR)) < 1.5


def test_a_doubled_signal_is_six_db_louder():
    voce = _rumore(4, 3000, 3)
    doppio = (voce.astype(np.float32) * 2)
    assert abs((loudness_lufs(doppio, SR) - loudness_lufs(voce, SR)) - 6.02) < 0.1


def test_float_and_int_are_measured_on_the_same_scale():
    voce = _rumore(3, 3000, 4)
    assert abs(loudness_lufs(voce, SR) - loudness_lufs(voce.astype(np.float32), SR)) < 0.01


def test_compression_narrows_the_gap_between_loud_and_quiet():
    forte = _rumore(4, 6000, 5)
    piano = _rumore(4, 900, 6)
    prima = np.concatenate([forte, piano])
    dopo = compress(prima.astype(np.float32), SR, threshold_db=-22.0, ratio=4.0)

    def rms_db(x):
        return 20 * np.log10(np.sqrt(np.mean((np.asarray(x, np.float32) / 32768.0) ** 2)))

    dinamica_prima = rms_db(prima[: forte.size]) - rms_db(prima[forte.size:])
    dinamica_dopo = rms_db(dopo[: forte.size]) - rms_db(dopo[forte.size:])
    assert dinamica_dopo < dinamica_prima - 3.0


def test_compression_leaves_quiet_material_alone():
    piano = _rumore(3, 300, 7).astype(np.float32)
    assert np.allclose(compress(piano, SR, threshold_db=-22.0, ratio=4.0), piano, atol=1.0)


def test_ratio_one_is_a_no_op():
    voce = _rumore(2, 4000, 8).astype(np.float32)
    assert np.array_equal(compress(voce, SR, ratio=1.0), voce)
