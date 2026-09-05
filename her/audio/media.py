"""Caricare un file audio qualsiasi e portarlo al passo della sessione.

Il WAV lo legge la libreria standard. Per mp3 e m4a serve ffmpeg: se non c'è,
si dice come rimediare invece di fallire in modo oscuro.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .wavio import read_wav


class MediaError(RuntimeError):
    pass


def resample(audio: np.ndarray, da: int, a: int) -> np.ndarray:
    """Cambia frequenza di campionamento passando per il dominio della frequenza.

    Interpolare i campioni sarebbe più semplice ma su una musica si sente:
    scendendo di frequenza compaiono fischi che prima non c'erano.
    """
    if da == a or audio.size == 0:
        return audio.astype(np.float32)
    x = audio.astype(np.float32)
    nuovo = int(round(x.size * a / da))
    spettro = np.fft.rfft(x)
    tenuti = min(spettro.size, nuovo // 2 + 1)
    ridotto = np.zeros(nuovo // 2 + 1, dtype=complex)
    ridotto[:tenuti] = spettro[:tenuti]
    return (np.fft.irfft(ridotto, n=nuovo) * (nuovo / x.size)).astype(np.float32)


def load_audio(path: str | Path, sample_rate: int) -> np.ndarray:
    """Audio mono, in scala int16, alla frequenza della sessione."""
    path = Path(path)
    if not path.exists():
        raise MediaError(f"file non trovato: {path}")

    if path.suffix.lower() == ".wav":
        campioni, sr = read_wav(path)
        return resample(campioni, sr, sample_rate)

    if not shutil.which("ffmpeg"):
        raise MediaError(
            f"{path.name} non è un WAV e senza ffmpeg non posso convertirlo. "
            "Converti il file in WAV (anche con un sito online) oppure installa ffmpeg."
        )
    with tempfile.TemporaryDirectory() as tmp:
        convertito = Path(tmp) / "audio.wav"
        esito = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
             "-ac", "1", "-ar", str(sample_rate), str(convertito)],
            capture_output=True, text=True,
        )
        if esito.returncode or not convertito.exists():
            raise MediaError(f"ffmpeg non è riuscito a leggere {path.name}: "
                             f"{esito.stderr.strip()[:200]}")
        campioni, _ = read_wav(convertito)
        return campioni.astype(np.float32)
