"""Cattura dal microfono: frame di dimensione fissa su una coda."""
from __future__ import annotations

import queue
import threading
from typing import Iterator

import numpy as np

from .devices import sd


class MicStream:
    """Legge il microfono in un thread di sistema e consegna frame int16 mono."""

    def __init__(self, sample_rate: int, frame_len: int, device=None, maxsize: int = 200):
        self.sample_rate = sample_rate
        self.frame_len = frame_len
        self.device = device
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._stream = None
        self._closed = threading.Event()
        self.dropped_frames = 0

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        try:
            self._q.put_nowait(np.array(indata, dtype=np.int16).reshape(-1).copy())
        except queue.Full:
            self.dropped_frames += 1

    def start(self) -> "MicStream":
        module = sd()
        self._stream = module.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_len,
            channels=1,
            dtype="int16",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        return self

    def frames(self, timeout: float = 0.5) -> Iterator[np.ndarray]:
        """Genera frame finché lo stream non viene chiuso."""
        while not self._closed.is_set():
            try:
                yield self._q.get(timeout=timeout)
            except queue.Empty:
                continue

    def close(self) -> None:
        self._closed.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def __enter__(self) -> "MicStream":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()
