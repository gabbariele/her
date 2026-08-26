"""Lettura/scrittura WAV PCM 16 bit mono con la sola stdlib + numpy."""
from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np


def pcm_to_array(data: bytes) -> np.ndarray:
    """Byte PCM signed 16 bit little endian -> array int16."""
    if len(data) % 2:
        data = data[:-1]
    return np.frombuffer(data, dtype="<i2")


def array_to_pcm(samples: np.ndarray) -> bytes:
    return np.asarray(samples, dtype="<i2").tobytes()


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """WAV in memoria (serve per l'upload alle API di trascrizione)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(array_to_pcm(samples))
    return buf.getvalue()


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(array_to_pcm(samples))
    return path


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Ritorna (samples int16 mono, sample_rate). I file multicanale vengono mixati."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError(f"{path}: supportato solo PCM 16 bit (trovato {width * 8} bit)")
    samples = pcm_to_array(raw)
    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, rate


class WavWriter:
    """Writer incrementale: si può scrivere mentre la sessione è in corso."""

    def __init__(self, path: str | Path, sample_rate: int):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wf = wave.open(str(self.path), "wb")
        self._wf.setnchannels(1)
        self._wf.setsampwidth(2)
        self._wf.setframerate(sample_rate)
        self.samples_written = 0

    def write(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.int16)
        if samples.size == 0:
            return
        self._wf.writeframes(array_to_pcm(samples))
        self.samples_written += samples.size

    def write_silence(self, n_samples: int) -> None:
        if n_samples > 0:
            self.write(np.zeros(int(n_samples), dtype=np.int16))

    def close(self) -> None:
        if self._wf is not None:
            self._wf.close()
            self._wf = None
