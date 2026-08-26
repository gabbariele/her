"""Riproduzione dell'audio dell'ospite, con possibilità di interruzione."""
from __future__ import annotations

import threading
from typing import Callable, Iterable, Optional

import numpy as np

from .devices import sd


class Player:
    """Scrittura bloccante sulla scheda audio: la riproduzione va a tempo reale.

    `on_audio` viene chiamata per ogni blocco effettivamente inviato in uscita:
    è l'aggancio con cui il registratore piazza l'audio sulla traccia dell'ospite.
    """

    def __init__(self, sample_rate: int, device=None, on_audio: Optional[Callable[[np.ndarray], None]] = None):
        self.sample_rate = sample_rate
        self.device = device
        self.on_audio = on_audio
        self._stream = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> "Player":
        module = sd()
        self._stream = module.OutputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            device=self.device,
        )
        self._stream.start()
        return self

    def play(self, chunks: Iterable[np.ndarray], block_samples: int = 2400) -> bool:
        """Riproduce i blocchi in arrivo. Ritorna False se è stata interrotta."""
        if self._stream is None:
            self.start()
        self._stop.clear()
        pending = np.zeros(0, dtype=np.int16)
        for chunk in chunks:
            if self._stop.is_set():
                break
            chunk = np.asarray(chunk, dtype=np.int16).reshape(-1)
            if chunk.size == 0:
                continue
            pending = np.concatenate([pending, chunk]) if pending.size else chunk
            while pending.size >= block_samples and not self._stop.is_set():
                self._write(pending[:block_samples])
                pending = pending[block_samples:]
        if pending.size and not self._stop.is_set():
            self._write(pending)
        interrupted = self._stop.is_set()
        if interrupted:
            self._recover()
        return not interrupted

    def _write(self, block: np.ndarray) -> None:
        with self._lock:
            if self._stream is None:
                return
            self._stream.write(block.reshape(-1, 1))
        if self.on_audio is not None:
            self.on_audio(block)

    def stop(self) -> None:
        """Taglia subito la riproduzione (barge-in)."""
        self._stop.set()
        stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass

    def _recover(self) -> None:
        with self._lock:
            if self._stream is None:
                return
            try:
                self._stream.stop()
                self._stream.start()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None

    def __enter__(self) -> "Player":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()


class NullPlayer:
    """Ripiego senza scheda audio: consuma i blocchi a tempo reale.

    Serve dove un'uscita audio non c'è (server, sessione remota, `--text` su una
    macchina senza altoparlanti): non senti l'ospite, ma la traccia `guest.wav`
    viene registrata con gli stessi tempi che avrebbe avuto in riproduzione.
    """

    def __init__(self, sample_rate: int, device=None, on_audio: Optional[Callable[[np.ndarray], None]] = None):
        self.sample_rate = sample_rate
        self.on_audio = on_audio
        self._stop = threading.Event()

    def start(self) -> "NullPlayer":
        return self

    def play(self, chunks: Iterable[np.ndarray], block_samples: int = 2400) -> bool:
        import time

        self._stop.clear()
        for chunk in chunks:
            if self._stop.is_set():
                break
            chunk = np.asarray(chunk, dtype=np.int16).reshape(-1)
            if chunk.size == 0:
                continue
            started = time.monotonic()
            if self.on_audio is not None:
                self.on_audio(chunk)
            remaining = chunk.size / self.sample_rate - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
        return not self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        pass

    def __enter__(self) -> "NullPlayer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
