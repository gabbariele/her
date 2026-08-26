"""Registratore multitraccia + timeline degli eventi.

Due tracce separate e sincronizzate:
  * `host.wav`  - il microfono, registrato in continuo dall'inizio alla fine;
  * `guest.wav` - la voce dell'ospite, piazzata al secondo esatto in cui è
                  stata riprodotta, con silenzio in mezzo.
Sommandole si riottiene la sessione integrale; tenendole separate puoi
rimontare, tagliare i vuoti e mixare le due voci in modo indipendente.
`events.jsonl` è la mappa dei turni (chi, quando, cosa ha detto).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from .wavio import WavWriter


class MultitrackRecorder:
    def __init__(self, out_dir: str | Path, sample_rate: int, wall_clock: bool = False):
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        self.wall_clock = wall_clock
        self._host = WavWriter(self.dir / "host.wav", sample_rate)
        self._guest = WavWriter(self.dir / "guest.wav", sample_rate)
        self._events = open(self.dir / "events.jsonl", "a", encoding="utf-8")
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._closed = False

    # -- orologio della sessione ------------------------------------------
    def now(self) -> float:
        """Secondi dall'inizio della sessione.

        In modalità microfono il tempo lo detta la traccia host: è l'unico
        orologio che non può andare fuori sincrono con l'audio registrato.
        """
        if self.wall_clock:
            return time.monotonic() - self._t0
        return self._host.samples_written / self.sample_rate

    # -- scrittura ---------------------------------------------------------
    def write_host(self, samples: np.ndarray) -> None:
        with self._lock:
            if not self._closed:
                self._host.write(samples)

    def write_guest(self, samples: np.ndarray) -> tuple[float, float]:
        """Piazza un blocco sulla traccia ospite. Ritorna (inizio, fine) in secondi."""
        samples = np.asarray(samples, dtype=np.int16).reshape(-1)
        with self._lock:
            if self._closed:
                return (0.0, 0.0)
            target = int(self.now() * self.sample_rate)
            gap = target - self._guest.samples_written
            if gap > 0:
                self._guest.write_silence(gap)
            start = self._guest.samples_written / self.sample_rate
            self._guest.write(samples)
            end = self._guest.samples_written / self.sample_rate
        return (start, end)

    # -- timeline ----------------------------------------------------------
    def log_event(self, speaker: str, start: float, end: float, text: str, **extra: Any) -> dict:
        event = {
            "speaker": speaker,
            "start": round(float(start), 3),
            "end": round(float(end), 3),
            "text": text,
            **extra,
        }
        with self._lock:
            if not self._closed:
                self._events.write(json.dumps(event, ensure_ascii=False) + "\n")
                self._events.flush()
        return event

    def write_meta(self, meta: dict) -> None:
        (self.dir / "session.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- chiusura ----------------------------------------------------------
    @property
    def duration(self) -> float:
        return max(self._host.samples_written, self._guest.samples_written) / self.sample_rate

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            total = max(self._host.samples_written, self._guest.samples_written)
            self._host.write_silence(total - self._host.samples_written)
            self._guest.write_silence(total - self._guest.samples_written)
            self._host.close()
            self._guest.close()
            self._events.close()

    def __enter__(self) -> "MultitrackRecorder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_events(session_dir: str | Path) -> list[dict]:
    path = Path(session_dir) / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    events.sort(key=lambda e: (e["start"], e["end"]))
    return events
