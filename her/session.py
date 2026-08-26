"""Il loop della registrazione: ascolta, capisce, risponde, registra tutto."""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

from .audio.mic import MicStream
from .audio.devices import AudioUnavailable
from .audio.player import NullPlayer, Player
from .audio.recorder import MultitrackRecorder
from .audio.vad import Endpointer
from .config import Config
from .providers import llm as llm_provider
from .providers import stt as stt_provider
from .providers import tts as tts_provider
from .text import iter_sentences

_END = object()  # sentinella di fine risposta sulla coda audio


class Ansi:
    HOST = "\033[96m"
    GUEST = "\033[95m"
    DIM = "\033[2m"
    WARN = "\033[93m"
    OFF = "\033[0m"


def _say(color: str, who: str, text: str) -> None:
    print(f"{color}{who}:{Ansi.OFF} {text}", flush=True)


def _note(text: str) -> None:
    print(f"{Ansi.DIM}· {text}{Ansi.OFF}", flush=True)


def _warn(text: str) -> None:
    print(f"{Ansi.WARN}! {text}{Ansi.OFF}", file=sys.stderr, flush=True)


def new_session_dir(root: str | Path = "sessions", name: str | None = None) -> Path:
    stamp = name or datetime.now().strftime("%Y%m%d-%H%M%S")
    path = Path(root) / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


class PodcastSession:
    """Orchestra microfono -> STT -> LLM -> TTS -> altoparlanti, registrando tutto.

    Il parallelismo serve solo alla latenza: mentre l'LLM sta ancora generando
    la frase 2, la frase 1 è già in sintesi o in riproduzione.
    """

    def __init__(self, cfg: Config, out_dir: str | Path, text_input: bool = False):
        self.cfg = cfg.sync()
        self.dir = Path(out_dir)
        self.text_input = text_input
        self.history: list[dict] = []
        self.recorder = MultitrackRecorder(self.dir, cfg.audio.sample_rate, wall_clock=text_input)
        self.player = Player(
            cfg.audio.sample_rate,
            device=cfg.audio.output_device,
            on_audio=self._on_guest_audio,
        )
        self.endpointer = Endpointer(cfg.vad)
        self._utterances: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._listening = threading.Event()
        self._speaking = threading.Event()
        self._mic: Optional[MicStream] = None
        self._mic_thread: Optional[threading.Thread] = None
        self._guest_span: list[float] = []
        self.turns = 0

    # -- ciclo di vita -----------------------------------------------------
    def run(self) -> Path:
        self._write_meta()
        try:
            self.player.start()
        except AudioUnavailable as exc:
            _warn(f"{exc}\n  Proseguo senza riproduzione: l'ospite viene registrato ma non lo senti.")
            self.player = NullPlayer(
                self.cfg.audio.sample_rate, on_audio=self._on_guest_audio
            )
        try:
            if self.text_input:
                self._run_text()
            else:
                self._run_mic()
        except KeyboardInterrupt:
            print()
            _note("interrotto")
        finally:
            self.close()
        return self.dir

    def close(self) -> None:
        self._stop.set()
        if self._mic is not None:
            self._mic.close()
        if self._mic_thread is not None:
            self._mic_thread.join(timeout=2.0)
        self.player.close()
        self.recorder.close()
        self._write_meta(final=True)

    def _write_meta(self, final: bool = False) -> None:
        meta = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "sample_rate": self.cfg.audio.sample_rate,
            "persona": {"name": self.cfg.persona.name, "system_prompt": self.cfg.persona.system_prompt},
            "stt": {"provider": self.cfg.stt.provider, "model": self.cfg.stt.model},
            "llm": {"provider": self.cfg.llm.provider, "model": self.cfg.llm.model},
            "tts": {"provider": self.cfg.tts.provider, "model": self.cfg.tts.model,
                    "voice_id": self.cfg.tts.voice_id},
            "turns": self.turns,
        }
        if final:
            meta["duration"] = round(self.recorder.duration, 2)
        self.recorder.write_meta(meta)

    # -- modalità microfono ------------------------------------------------
    def _run_mic(self) -> None:
        cfg = self.cfg
        self._mic = MicStream(cfg.audio.sample_rate, cfg.vad.frame_len, device=cfg.audio.input_device)
        self._mic.start()
        self._listening.set()
        self._mic_thread = threading.Thread(target=self._mic_loop, name="mic", daemon=True)
        self._mic_thread.start()

        _note(f"calibrazione del rumore di fondo ({cfg.vad.calibration_s:g}s): resta in silenzio…")
        time.sleep(cfg.vad.calibration_s + 0.3)
        _note(f"soglia voce: {self.endpointer.threshold_db:.0f} dBFS · Ctrl-C per chiudere")
        self._greet()
        print()

        while not self._stop.is_set():
            try:
                audio, start, end = self._utterances.get(timeout=0.3)
            except queue.Empty:
                continue
            self._handle_turn(audio, start, end)

    def _mic_loop(self) -> None:
        assert self._mic is not None
        sr = self.cfg.audio.sample_rate
        for frame in self._mic.frames():
            if self._stop.is_set():
                break
            self.recorder.write_host(frame)
            if not self._listening.is_set():
                continue
            event = self.endpointer.push(frame)
            if event is None:
                continue
            kind, audio = event
            if kind == "start":
                if self._speaking.is_set() and self.cfg.session.barge_in:
                    self.player.stop()
                    _note("interrotto dall'utente")
                continue
            if audio is None or audio.size == 0:
                continue
            end = self.recorder.now() - self.endpointer.hangover_s
            start = max(0.0, end - audio.size / sr)
            self._utterances.put((audio, start, end))

    # -- modalità testo (per provare senza microfono) ----------------------
    def _run_text(self) -> None:
        _note("modalità testo: scrivi e premi Invio (riga vuota o Ctrl-D per chiudere)")
        self._greet()
        while not self._stop.is_set():
            try:
                line = input(f"{Ansi.HOST}tu>{Ansi.OFF} ").strip()
            except EOFError:
                break
            if not line:
                break
            now = self.recorder.now()
            self.recorder.log_event("host", now, now, line, source="text")
            self._reply_to(line)

    # -- un turno ----------------------------------------------------------
    def _handle_turn(self, audio: np.ndarray, start: float, end: float) -> None:
        t0 = time.monotonic()
        try:
            text = stt_provider.transcribe(
                audio, self.cfg.audio.sample_rate, self.cfg.stt, notice=_warn
            )
        except Exception as exc:  # una sessione non si butta via per un errore di rete
            _warn(f"trascrizione fallita: {exc}")
            return
        if not text.strip():
            _note("(turno vuoto, ignorato)")
            return
        self.recorder.log_event("host", start, end, text, stt_ms=int((time.monotonic() - t0) * 1000))
        _say(Ansi.HOST, "tu", text)
        self._reply_to(text)

    def _reply_to(self, user_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        audio_q: queue.Queue = queue.Queue(maxsize=64)
        result: dict = {}
        worker = threading.Thread(
            target=self._produce_reply, args=(audio_q, result), name="reply", daemon=True
        )
        t0 = time.monotonic()
        worker.start()

        self._speaking.set()
        if self.cfg.session.half_duplex and not self.cfg.session.barge_in:
            self._listening.clear()
        self._guest_span = []
        try:
            self.player.play(self._drain(audio_q))
        finally:
            worker.join(timeout=5.0)
            self._speaking.clear()
            self.endpointer.reset()
            self._listening.set()

        text = (result.get("text") or "").strip()
        if result.get("error"):
            _warn(result["error"])
        if not text:
            self.history.pop()
            return
        self.history.append({"role": "assistant", "content": text})
        self.history = llm_provider.trim_history(self.history, self.cfg.llm.history_turns)
        self.turns += 1
        if self._guest_span:
            self.recorder.log_event(
                "guest",
                self._guest_span[0],
                self._guest_span[-1],
                text,
                latency_ms=int((result.get("first_audio", time.monotonic()) - t0) * 1000),
            )
        _say(Ansi.GUEST, self.cfg.persona.name, text)
        if result.get("first_audio"):
            _note(f"latenza prima voce: {(result['first_audio'] - t0):.1f}s")
        print()

    def _produce_reply(self, audio_q: queue.Queue, result: dict) -> None:
        """LLM -> frasi -> TTS -> coda audio. Gira in un thread a parte."""
        parts: list[str] = []
        try:
            tokens = llm_provider.stream_reply(
                self.cfg.persona.system_prompt, self.history, self.cfg.llm, notice=_warn
            )
            for sentence in iter_sentences(_tee(tokens, parts)):
                if self._stop.is_set():
                    break
                for chunk in tts_provider.stream_speech(
                    sentence, self.cfg.tts, self.cfg.audio.sample_rate
                ):
                    if self._stop.is_set():
                        break
                    result.setdefault("first_audio", time.monotonic())
                    audio_q.put(chunk)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            result["text"] = "".join(parts)
            audio_q.put(_END)

    def _drain(self, audio_q: queue.Queue) -> Iterator[np.ndarray]:
        while True:
            item = audio_q.get()
            if item is _END:
                return
            yield item

    def _on_guest_audio(self, block: np.ndarray) -> None:
        start, end = self.recorder.write_guest(block)
        if not self._guest_span:
            self._guest_span = [start, end]
        else:
            self._guest_span[-1] = end

    # -- saluto iniziale ---------------------------------------------------
    def _greet(self) -> None:
        greeting = self.cfg.persona.greeting.strip()
        if not greeting:
            return
        self._guest_span = []
        self._speaking.set()
        if self.cfg.session.half_duplex:
            self._listening.clear()
        try:
            chunks = tts_provider.stream_speech(greeting, self.cfg.tts, self.cfg.audio.sample_rate)
            self.player.play(chunks)
        except Exception as exc:
            _warn(f"saluto non riprodotto: {exc}")
        finally:
            self._speaking.clear()
            self.endpointer.reset()
            self._listening.set()
        if self._guest_span:
            self.recorder.log_event("guest", self._guest_span[0], self._guest_span[-1], greeting)
        self.history.append({"role": "assistant", "content": greeting})
        _say(Ansi.GUEST, self.cfg.persona.name, greeting)


def _tee(tokens: Iterator[str], sink: list[str]) -> Iterator[str]:
    for token in tokens:
        sink.append(token)
        yield token


def load_history(session_dir: str | Path) -> list[dict]:
    """Ricostruisce la conversazione da una sessione già registrata."""
    from .audio.recorder import read_events

    history = []
    for ev in read_events(session_dir):
        role = "user" if ev["speaker"] == "host" else "assistant"
        if ev.get("text"):
            history.append({"role": role, "content": ev["text"]})
    return history


def dump_history(history: list[dict]) -> str:
    return json.dumps(history, ensure_ascii=False, indent=2)
