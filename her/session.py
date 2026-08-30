"""Il loop della registrazione: ascolta, capisce, risponde, registra tutto."""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import TextIO, Iterator, Optional

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
from .suggester import Suggester, Suggestion
from .text import iter_sentences

_END = object()  # sentinella di fine risposta sulla coda audio

#: file su cui viene ricopiato tutto quello che compare a schermo. Senza, dopo
#: una registrazione andata storta non resta niente da guardare.
_LOG: "TextIO | None" = None


def open_log(path: Path) -> None:
    global _LOG
    close_log()
    try:
        _LOG = open(path, "a", encoding="utf-8")
        _log(f"--- avvio {datetime.now().isoformat(timespec='seconds')} ---")
    except OSError:
        _LOG = None


def close_log() -> None:
    global _LOG
    if _LOG is not None:
        try:
            _LOG.close()
        finally:
            _LOG = None


def _log(text: str, level: str = "info") -> None:
    if _LOG is None:
        return
    try:
        stamp = datetime.now().strftime("%H:%M:%S")
        _LOG.write(f"{stamp} [{level}] {text}\n")
        _LOG.flush()
    except (OSError, ValueError):
        pass


class Ansi:
    HOST = "\033[96m"
    GUEST = "\033[95m"
    CUE = "\033[93m"
    DIM = "\033[2m"
    WARN = "\033[93m"
    OFF = "\033[0m"


#: la regia scrive da un thread suo: senza questo lucchetto le sue righe si
#: infilano in mezzo a quelle della conversazione
_PRINT_LOCK = threading.Lock()


def _out(text: str, stream=None) -> None:
    stream = stream or sys.stdout
    with _PRINT_LOCK:
        stream.write(text + "\n")
        stream.flush()


def _say(color: str, who: str, text: str) -> None:
    _out(f"{color}{who}:{Ansi.OFF} {text}")
    _log(f"{who}: {text}", "voce")


def _note(text: str) -> None:
    _out(f"{Ansi.DIM}· {text}{Ansi.OFF}")
    _log(text)


def _warn(text: str) -> None:
    _out(f"{Ansi.WARN}! {text}{Ansi.OFF}", sys.stderr)
    _log(text, "ERRORE")


def _cue(text: str) -> None:
    """Il suggerimento della regia: si distingue a colpo d'occhio dal parlato."""
    _out(f"\n{Ansi.CUE}   → regia: {text}{Ansi.OFF}")
    _log(f"regia: {text}", "regia")


def _crash(what: str, exc: BaseException) -> None:
    """Un guasto vero: a schermo il minimo, sul registro tutto."""
    _warn(f"{what}: {type(exc).__name__}: {exc}")
    _log("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), "TRACCIA")


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

    def __init__(
        self,
        cfg: Config,
        out_dir: str | Path,
        text_input: bool = False,
        resume: bool = False,
    ):
        self.cfg = cfg.sync()
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.text_input = text_input
        self.resumed = resume
        open_log(self.dir / "sessione.log")
        self.history: list[dict] = load_history(self.dir) if resume else []
        #: prompt del preset + regole di lunghezza e di domande
        self.system_prompt = cfg.persona.effective_prompt()
        self.recorder = MultitrackRecorder(
            self.dir, cfg.audio.sample_rate, wall_clock=text_input, resume=resume
        )
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
        self._reply_ready_at = 0.0
        self.suggester = Suggester(
            cfg.suggester,
            briefing=cfg.persona.briefing,
            persona_name=cfg.persona.name,
            out_path=self.dir / "suggerimenti.md",
            on_suggestion=self._show_cue,
            on_error=self._suggester_error,
        )
        self._suggester_warned = False
        #: guardie sullo stato dell'ascolto
        self.mic_failed = False
        self._last_frame = time.monotonic()
        self._silence_warned = False

    # -- ciclo di vita -----------------------------------------------------
    def run(self) -> Path:
        self._write_meta()
        if self.resumed:
            _note(f"ripresa da {self.recorder.resumed_from / 60:.1f} minuti già registrati, "
                  f"{len(self.history)} battute in memoria")
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
        self.suggester.close()
        self.recorder.close()
        self._write_meta(final=True)
        self._write_full_mix()
        _log("--- chiusura regolare ---")
        close_log()

    def _write_full_mix(self) -> None:
        """Le due voci in un file solo, scritto subito dopo la registrazione.

        Non aspetta il montaggio: se qualcosa va storto dopo (o la finestra
        viene chiusa), la registrazione completa è già sul disco.
        """
        if self.recorder.duration <= 0:
            return
        try:
            from .render import write_full_mix

            path = write_full_mix(self.dir)
            _note(f"registrazione completa: {path}")
        except Exception as exc:
            _warn(f"registrazione completa non scritta: {exc}")

    def _write_meta(self, final: bool = False) -> None:
        meta = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "sample_rate": self.cfg.audio.sample_rate,
            "persona": {
                "name": self.cfg.persona.name,
                "length": self.cfg.persona.length,
                "questions": self.cfg.persona.questions,
                "system_prompt": self.system_prompt,
            },
            "stt": {"provider": self.cfg.stt.provider, "model": self.cfg.stt.model},
            "llm": {"provider": self.cfg.llm.provider, "model": self.cfg.llm.model},
            "tts": {"provider": self.cfg.tts.provider, "model": self.cfg.tts.model,
                    "voice_id": self.cfg.tts.voice_id},
            "turns": self.turns,
            "resumed": self.resumed,
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
        if self.endpointer.heard_speech_while_calibrating:
            _warn("ho sentito parlare durante la calibrazione: aspetta il «tocca a te» "
                  "prima di iniziare, o le prime parole non finiscono nel montato")
        _note(f"soglia voce: {self.endpointer.threshold_db:.0f} dBFS")
        print(f"{Ansi.DIM}· premi INVIO quando hai finito la puntata "
              f"(così il montaggio fa in tempo a scriversi){Ansi.OFF}", flush=True)
        threading.Thread(target=self._wait_for_enter, name="stop", daemon=True).start()
        self._announce_suggester()
        self._greet()
        print(f"{Ansi.HOST}→ tocca a te: parla pure.{Ansi.OFF}\n", flush=True)

        while not self._stop.is_set():
            try:
                audio, start, end = self._utterances.get(timeout=0.3)
            except queue.Empty:
                self._check_alive()
                continue
            try:
                self._handle_turn(audio, start, end)
            except Exception as exc:
                # qualunque cosa sia andata storta, la registrazione continua
                _crash("turno non completato", exc)
                self._speaking.clear()
                self._listening.set()

    def _show_cue(self, suggestion: Suggestion) -> None:
        attesa = time.monotonic() - self._reply_ready_at if self._reply_ready_at else 0.0
        _cue(suggestion.text)
        _log(f"regia in {attesa:.1f}s dopo la risposta", "regia")

    def _suggester_error(self, message: str) -> None:
        """La regia è un di più: se non funziona lo dice una volta e sta zitta."""
        if not self._suggester_warned:
            self._suggester_warned = True
            _warn(message)
        else:
            _log(message, "regia")

    def _check_alive(self) -> None:
        """Se il microfono smette di mandare audio, dirlo invece di stare zitti."""
        if self.mic_failed or self._speaking.is_set():
            return
        fermo = time.monotonic() - self._last_frame
        if fermo > 5.0 and not self._silence_warned:
            self._silence_warned = True
            _warn(f"il microfono non manda audio da {fermo:.0f}s: controlla che non sia "
                  "staccato o occupato da un altro programma")
        elif fermo <= 5.0:
            self._silence_warned = False

    def _wait_for_enter(self) -> None:
        """Chiusura pulita: Ctrl-C su Windows può ammazzare il processo prima
        che il montaggio venga scritto, INVIO no."""
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            return
        if not self._stop.is_set():
            _note("chiudo la puntata…")
            self._stop.set()

    def _mic_loop(self) -> None:
        """Il thread che ascolta. Se muore, la sessione resta aperta ma sorda:
        per questo qui dentro non si può lasciar passare nessuna eccezione."""
        assert self._mic is not None
        sr = self.cfg.audio.sample_rate
        try:
            for frame in self._mic.frames():
                if self._stop.is_set():
                    break
                self._last_frame = time.monotonic()
                try:
                    self._process_frame(frame, sr)
                except Exception as exc:
                    # un turno perso è meglio di un microfono che smette di
                    # funzionare senza dirlo
                    _crash("errore nell'ascolto (turno saltato)", exc)
                    self.endpointer.reset()
        except Exception as exc:
            _crash("il microfono si è fermato", exc)
            self.mic_failed = True
            _warn("ascolto interrotto: chiudi con INVIO e riprendi con riprendi.bat")

    def _process_frame(self, frame: np.ndarray, sr: int) -> None:
        self.recorder.write_host(frame)
        if not self._listening.is_set():
            return
        event = self.endpointer.push(frame)
        if event is None:
            return
        kind, audio = event
        if kind == "start":
            if self._speaking.is_set() and self.cfg.session.barge_in:
                self.player.stop()
                _note("interrotto dall'utente")
            return
        if audio is None or audio.size == 0:
            return
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
    def _announce_suggester(self) -> None:
        motivo = self.suggester.check()
        if motivo == "spenta":
            return
        if motivo:
            _warn(f"regia non attiva ({motivo}): registri lo stesso, senza suggerimenti")
            self.suggester.disabled_reason = motivo
            return
        _note(f"regia attiva ({self.cfg.suggester.model}): reagisce a quello che dice "
              f"{self.cfg.persona.name} e ti passa una riga mentre lei parla")

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
            # non capito ≠ non detto: l'audio c'è, e nel montato ci resta.
            # Sparire dal montaggio quello che hai detto è il danno peggiore.
            self.recorder.log_event("host", start, end, "", kind="unclear")
            _note("(non trascritto: lo tengo lo stesso nel montato)")
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
        """LLM -> frasi -> TTS -> coda audio. Gira in un thread a parte.

        Il testo dell'LLM viene scaricato alla massima velocità in un thread
        suo: se lo si leggesse dentro al ciclo della sintesi, il flusso
        resterebbe fermo ad aspettare che l'altoparlante finisca la frase
        precedente, e la regia scatterebbe a fine risposta invece che all'inizio.
        """
        parts: list[str] = []
        token_q: queue.Queue = queue.Queue()

        def scarica_testo() -> None:
            try:
                for token in llm_provider.stream_reply(
                    self.system_prompt, self.history, self.cfg.llm, notice=_warn
                ):
                    parts.append(token)
                    token_q.put(token)
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                token_q.put(_END)
                # l'ospite ha finito di formulare: la regia può reagire adesso,
                # mentre la voce sta ancora pronunciando le prime frasi
                testo = "".join(parts).strip()
                if testo:
                    result["reply_ready"] = self._reply_ready_at = time.monotonic()
                    self.suggester.consider(
                        self.history + [{"role": "assistant", "content": testo}]
                    )

        threading.Thread(target=scarica_testo, name="llm", daemon=True).start()

        try:
            for sentence in iter_sentences(self._drain(token_q)):
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

    def _drain(self, coda: queue.Queue) -> Iterator:
        """Svuota una coda fino alla sentinella di fine."""
        while True:
            item = coda.get()
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
        if not greeting or self.resumed:
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
            # marcato come saluto: il montaggio lo lascia fuori, la
            # registrazione integrale invece ce l'ha
            self.recorder.log_event(
                "guest", self._guest_span[0], self._guest_span[-1], greeting, kind="greeting"
            )
        self.history.append({"role": "assistant", "content": greeting})
        _say(Ansi.GUEST, self.cfg.persona.name, greeting)


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
