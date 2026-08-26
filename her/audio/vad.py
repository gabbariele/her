"""Rilevamento del parlato ed endpointing (capire quando hai finito di parlare).

VAD a energia con soglia adattiva sul rumore di fondo: nessuna dipendenza da
compilare, e in cuffia con un microfono decente funziona benissimo. Se hai
installato `webrtcvad` viene usato quello, che è più robusto in ambienti rumorosi.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

_EPS = 1e-9


def rms_dbfs(frame: np.ndarray) -> float:
    """Livello RMS del frame in dBFS (0 dB = fondo scala)."""
    x = np.asarray(frame, dtype=np.float32) / 32768.0
    if x.size == 0:
        return -120.0
    return float(20.0 * np.log10(np.sqrt(np.mean(x * x)) + _EPS))


@dataclass
class VadConfig:
    sample_rate: int = 24000
    frame_ms: int = 20
    #: quanti dB sopra il rumore di fondo per considerare "parlato"
    threshold_db: float = 10.0
    #: pavimento assoluto: sotto questo livello è sempre silenzio
    floor_db: float = -50.0
    #: silenzio necessario per considerare finito il turno
    silence_ms: int = 700
    #: parlato minimo perché un turno sia valido (filtra colpi di tosse e click)
    min_speech_ms: int = 350
    #: audio conservato prima dell'attacco, per non tagliare la prima sillaba
    preroll_ms: int = 300
    #: taglio di sicurezza per monologhi lunghi
    max_utterance_s: float = 120.0
    #: secondi di calibrazione del rumore di fondo a inizio sessione
    calibration_s: float = 1.0

    @property
    def frame_len(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000)


class Endpointer:
    """Macchina a stati sui frame del microfono.

    `push(frame)` ritorna:
      * `("start", None)` quando inizi a parlare,
      * `("end", audio)` quando smetti (audio = il turno, senza la coda di silenzio),
      * `None` altrimenti.
    """

    def __init__(self, cfg: VadConfig):
        self.cfg = cfg
        self.noise_db = -60.0
        self._calibrated_frames = 0
        self._speaking = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._buf: list[np.ndarray] = []
        self._preroll: list[np.ndarray] = []
        self._preroll_max = max(1, int(cfg.preroll_ms / cfg.frame_ms))
        self._silence_needed = max(1, int(cfg.silence_ms / cfg.frame_ms))
        self._speech_needed = max(1, int(cfg.min_speech_ms / cfg.frame_ms))
        self._max_frames = int(cfg.max_utterance_s * 1000 / cfg.frame_ms)
        self._calib_frames = max(1, int(cfg.calibration_s * 1000 / cfg.frame_ms))

    # -- stato ------------------------------------------------------------
    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def hangover_s(self) -> float:
        return self._silence_needed * self.cfg.frame_ms / 1000.0

    @property
    def threshold_db(self) -> float:
        return max(self.noise_db + self.cfg.threshold_db, self.cfg.floor_db)

    def reset(self) -> None:
        self._speaking = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._buf.clear()
        self._preroll.clear()

    # -- ingresso ---------------------------------------------------------
    def push(self, frame: np.ndarray) -> Optional[tuple[str, Optional[np.ndarray]]]:
        level = rms_dbfs(frame)

        if self._calibrated_frames < self._calib_frames:
            # media mobile sul rumore di fondo iniziale
            n = self._calibrated_frames
            self.noise_db = level if n == 0 else (self.noise_db * n + level) / (n + 1)
            self._calibrated_frames += 1
            return None

        is_speech = level > self.threshold_db

        if not self._speaking:
            if not is_speech:
                # aggiorna lentamente il fondo: il rumore ambientale cambia
                self.noise_db = 0.98 * self.noise_db + 0.02 * level
                self._preroll.append(frame)
                if len(self._preroll) > self._preroll_max:
                    self._preroll.pop(0)
                self._speech_frames = 0
                return None
            self._speech_frames += 1
            self._preroll.append(frame)
            if len(self._preroll) > self._preroll_max + self._speech_needed:
                self._preroll.pop(0)
            if self._speech_frames >= self._speech_needed:
                self._speaking = True
                self._silence_frames = 0
                self._buf = list(self._preroll)
                self._preroll = []
                return ("start", None)
            return None

        # stiamo già parlando
        self._buf.append(frame)
        if is_speech:
            self._silence_frames = 0
        else:
            self._silence_frames += 1

        too_long = len(self._buf) >= self._max_frames
        if self._silence_frames >= self._silence_needed or too_long:
            audio = self._collect(drop_tail=not too_long)
            self.reset()
            return ("end", audio)
        return None

    def flush(self) -> Optional[np.ndarray]:
        """Chiude un turno rimasto aperto (fine sessione)."""
        if not self._speaking:
            return None
        audio = self._collect(drop_tail=True)
        self.reset()
        return audio

    def _collect(self, drop_tail: bool) -> np.ndarray:
        frames = self._buf
        if drop_tail and self._silence_frames:
            frames = frames[: len(frames) - self._silence_frames] or self._buf
        if not frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(frames).astype(np.int16)
