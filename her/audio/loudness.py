"""Misura del volume percepito (LUFS) e compressione della dinamica.

Misurare il livello di una voce con l'RMS dei frame più forti sembra sensato ma
non lo è: basta un colpo sul tavolo o una plosiva perché il conto si alzi di
qualche dB, e un microfono che a orecchio è basso risulti «già a posto».

Qui si usa il metodo dello standard broadcast (ITU-R BS.1770): filtro
K-weighting, che pesa le frequenze come le pesa l'orecchio, blocchi da 400 ms e
due cancelli — uno assoluto e uno relativo — che buttano via silenzi e istanti
isolati. È lo stesso numero con cui si normalizzano radio e podcast.
"""
from __future__ import annotations

import numpy as np

#: parametri del filtro K-weighting (BS.1770-4)
_SHELF = {"gain_db": 3.999843853973347, "q": 0.7071752369554196, "freq": 1681.974450955533}
_HIGHPASS = {"q": 0.5003270373238773, "freq": 38.13547087602444}

ABSOLUTE_GATE = -70.0      # LUFS: sotto è silenzio
RELATIVE_GATE = 10.0       # LU sotto la media: sotto è pausa, non parlato


def _shelf_coeffs(sr: int) -> tuple[np.ndarray, np.ndarray]:
    a_gain = 10 ** (_SHELF["gain_db"] / 40.0)
    w0 = 2 * np.pi * _SHELF["freq"] / sr
    alpha = np.sin(w0) / (2 * _SHELF["q"])
    cos_w0, root = np.cos(w0), np.sqrt(a_gain)
    b = np.array([
        a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 + 2 * root * alpha),
        -2 * a_gain * ((a_gain - 1) + (a_gain + 1) * cos_w0),
        a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 - 2 * root * alpha),
    ])
    a = np.array([
        (a_gain + 1) - (a_gain - 1) * cos_w0 + 2 * root * alpha,
        2 * ((a_gain - 1) - (a_gain + 1) * cos_w0),
        (a_gain + 1) - (a_gain - 1) * cos_w0 - 2 * root * alpha,
    ])
    return b, a


def _highpass_coeffs(sr: int) -> tuple[np.ndarray, np.ndarray]:
    w0 = 2 * np.pi * _HIGHPASS["freq"] / sr
    alpha = np.sin(w0) / (2 * _HIGHPASS["q"])
    cos_w0 = np.cos(w0)
    b = np.array([(1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2])
    a = np.array([1 + alpha, -2 * cos_w0, 1 - alpha])
    return b, a


def _response(b: np.ndarray, a: np.ndarray, freqs: np.ndarray, sr: int) -> np.ndarray:
    z = np.exp(-2j * np.pi * freqs / sr)
    return (b[0] + b[1] * z + b[2] * z**2) / (a[0] + a[1] * z + a[2] * z**2)


def k_weight(x: np.ndarray, sr: int, block: int = 1 << 18) -> np.ndarray:
    """Applica il filtro K-weighting, a blocchi per non tenere tutto in memoria."""
    if x.size == 0:
        return x
    overlap = min(4096, max(64, x.size // 4))
    out = np.zeros(x.size, dtype=np.float32)
    step = max(block - 2 * overlap, 1)
    for start in range(0, x.size, step):
        chunk = x[max(0, start - overlap): start + step + overlap]
        n = chunk.size
        freqs = np.fft.rfftfreq(n, 1.0 / sr)
        shelf, hp = _shelf_coeffs(sr), _highpass_coeffs(sr)
        response = _response(*shelf, freqs, sr) * _response(*hp, freqs, sr)
        filtered = np.fft.irfft(np.fft.rfft(chunk) * response, n=n)
        head = start - max(0, start - overlap)
        piece = filtered[head: head + min(step, x.size - start)]
        out[start: start + piece.size] = piece
    return out


#: nel programma l'audio viaggia sempre in scala int16, anche quando è float
FULL_SCALE = 32768.0


def loudness_lufs(x: np.ndarray, sr: int, full_scale: float = FULL_SCALE) -> float | None:
    """Volume percepito dell'intera traccia, in LUFS. None se è muta.

    `x` è in scala int16 (il tipo può essere int16 o float: qui dentro le
    tracce restano in quella scala anche dopo i guadagni).
    """
    if x.size == 0:
        return None
    audio = np.asarray(x, dtype=np.float32) / full_scale
    weighted = k_weight(audio, sr)

    block = int(sr * 0.4)
    hop = max(1, int(sr * 0.1))
    if weighted.size < block:
        block, hop = weighted.size, max(1, weighted.size)
    starts = range(0, max(1, weighted.size - block + 1), hop)
    power = np.array([float(np.mean(weighted[s: s + block] ** 2)) for s in starts])
    power = power[power > 0]
    if power.size == 0:
        return None

    loud = -0.691 + 10 * np.log10(power)
    kept = power[loud > ABSOLUTE_GATE]
    if kept.size == 0:
        return None
    threshold = (-0.691 + 10 * np.log10(float(np.mean(kept)))) - RELATIVE_GATE
    kept = kept[(-0.691 + 10 * np.log10(kept)) > threshold]
    if kept.size == 0:
        return None
    return float(-0.691 + 10 * np.log10(float(np.mean(kept))))


def compress(
    x: np.ndarray,
    sr: int,
    threshold_db: float = -24.0,
    ratio: float = 3.0,
    attack_s: float = 0.01,
    release_s: float = 0.18,
    knee_db: float = 6.0,
) -> np.ndarray:
    """Compressore leggero: avvicina le parole piano a quelle forti.

    Una voce sintetica è già compressa e suona «piena»; una voce vera al
    microfono ha picchi e valli, e a parità di misura sembra più lontana.
    Qui l'inviluppo si calcola su frame da 10 ms e il guadagno risultante viene
    interpolato: fa lo stesso lavoro di un compressore campione per campione,
    ma abbastanza in fretta da girare su un'ora di registrazione.
    """
    audio = np.asarray(x, dtype=np.float32)
    if audio.size == 0 or ratio <= 1.0:
        return audio

    frame = max(1, int(sr * 0.01))
    usable = (audio.size // frame) * frame
    if usable < frame:
        return audio
    frames = audio[:usable].reshape(-1, frame) / 32768.0
    rms = np.sqrt(np.mean(frames * frames, axis=1)) + 1e-9
    level_db = 20 * np.log10(rms)

    # inviluppo con attacco veloce e rilascio lento, come un compressore vero
    attack = np.exp(-frame / (sr * max(attack_s, 1e-4)))
    release = np.exp(-frame / (sr * max(release_s, 1e-4)))
    envelope = np.empty_like(level_db)
    previous = level_db[0]
    for i, value in enumerate(level_db):
        coeff = attack if value > previous else release
        previous = value + coeff * (previous - value)
        envelope[i] = previous

    over = envelope - threshold_db
    gain_db = np.zeros_like(over)
    knee = max(knee_db, 1e-6)
    in_knee = (over > -knee / 2) & (over < knee / 2)
    above = over >= knee / 2
    gain_db[above] = (over[above]) * (1 / ratio - 1)
    gain_db[in_knee] = ((over[in_knee] + knee / 2) ** 2 / (2 * knee)) * (1 / ratio - 1)

    gains = 10 ** (gain_db / 20.0)
    per_sample = np.interp(
        np.arange(audio.size),
        np.arange(gains.size) * frame + frame / 2,
        gains,
        left=gains[0],
        right=gains[-1],
    ).astype(np.float32)
    return audio * per_sample
