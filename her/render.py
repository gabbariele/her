"""Post-produzione: dalle tracce grezze al podcast montato.

Il montaggio usa la timeline (`events.jsonl`) invece di indovinare dove sono i
silenzi: ogni turno viene estratto dalla sua traccia e riappoggiato in fila,
comprimendo le pause di elaborazione a `max_gap_s`. Le sovrapposizioni (quando
interrompi l'ospite) restano sovrapposte.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio.recorder import read_events
from .audio.wavio import read_wav, write_wav
from .config import RenderConfig


@dataclass
class Levels:
    """Com'erano le due voci e quanto sono state corrette."""

    host_dbfs: float | None = None
    guest_dbfs: float | None = None
    host_gain_db: float = 0.0
    guest_gain_db: float = 0.0

    @property
    def gap_db(self) -> float:
        if self.host_dbfs is None or self.guest_dbfs is None:
            return 0.0
        return abs(self.host_dbfs - self.guest_dbfs)


@dataclass
class RenderResult:
    wav: Path
    #: registrazione integrale, non montata: le due voci su un unico file
    full: Path
    mp3: Path | None
    transcript: Path
    srt: Path
    duration: float
    raw_duration: float
    segments: list[dict]
    levels: Levels = field(default_factory=Levels)
    #: secondi di voce del conduttore rimasti fuori dai turni riconosciuti
    unmatched_host_s: float = 0.0

    @property
    def saved(self) -> float:
        return max(0.0, self.raw_duration - self.duration)


def _db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def speech_level_dbfs(
    track: np.ndarray, sr: int, spans: list[tuple[float, float]] | None = None
) -> float | None:
    """Livello del parlato in dBFS, ignorando le pause.

    Misurare tutta la traccia darebbe un numero senza senso: in una traccia
    ci sono più silenzi che voce. Qui si guardano solo i pezzi in cui la
    persona parla davvero, e all'interno di quelli solo i frame sopra il
    fondo, così le virgole non abbassano la media.
    """
    if spans:
        pieces = [_slice(track, a, b, sr) for a, b in spans]
        pieces = [p for p in pieces if p.size]
        audio = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
    else:
        audio = track.astype(np.float32)
    if audio.size == 0:
        return None

    frame = max(1, int(sr * 0.05))
    usable = (audio.size // frame) * frame
    if usable < frame:
        return None
    frames = audio[:usable].reshape(-1, frame) / 32768.0
    energy = np.mean(frames * frames, axis=1)
    energy = energy[energy > 0]
    if energy.size == 0:
        return None
    db = 10.0 * np.log10(energy)
    # solo i frame vicini ai più forti: è lì che c'è la voce
    floor = max(np.max(db) - 25.0, -60.0)
    voiced = energy[db >= floor]
    if voiced.size == 0:                    # traccia quasi muta: meglio di niente
        voiced = energy
    level = float(10.0 * np.log10(np.mean(voiced)))
    return level if np.isfinite(level) else None


def unmatched_host_seconds(host: np.ndarray, events: list[dict], sr: int) -> float:
    """Quanti secondi di voce del conduttore restano fuori dai turni riconosciuti.

    Serve a rispondere alla domanda «ho perso qualcosa?»: se hai parlato mentre
    l'ospite parlava, o prima del via, quell'audio è nella registrazione
    integrale ma non nel montato, e conviene dirlo invece di lasciarlo scoprire.
    """
    if host.size == 0:
        return 0.0
    frame = max(1, int(sr * 0.05))
    usable = (host.size // frame) * frame
    if usable < frame:
        return 0.0
    frames = host[:usable].reshape(-1, frame).astype(np.float32) / 32768.0
    energy = np.mean(frames * frames, axis=1)
    db = 10.0 * np.log10(np.maximum(energy, 1e-12))
    speech = db > max(np.max(db) - 25.0, -55.0)

    for ev in events:
        if ev["speaker"] != "host":
            continue
        start = max(0, int(float(ev["start"]) * sr) // frame)
        end = min(speech.size, int(np.ceil(float(ev["end"]) * sr / frame)))
        speech[start:end] = False
    return float(np.count_nonzero(speech) * frame / sr)


def measure_levels(
    tracks: dict, events: list[dict], sr: int, cfg: RenderConfig
) -> Levels:
    """Quanto sono distanti le due voci, e di quanto vanno corrette."""
    levels = Levels()
    measured = {}
    for speaker, track in tracks.items():
        spans = [(float(e["start"]), float(e["end"])) for e in events if e["speaker"] == speaker]
        measured[speaker] = speech_level_dbfs(track, sr, spans or None)
    levels.host_dbfs, levels.guest_dbfs = measured.get("host"), measured.get("guest")

    if not cfg.match_loudness:
        levels.host_gain_db = cfg.host_gain_db
        levels.guest_gain_db = cfg.guest_gain_db
        return levels

    for speaker, extra in (("host", cfg.host_gain_db), ("guest", cfg.guest_gain_db)):
        level = measured.get(speaker)
        correction = 0.0
        if level is not None and np.isfinite(level):
            correction = float(np.clip(cfg.target_dbfs - level, -cfg.max_match_db, cfg.max_match_db))
        setattr(levels, f"{speaker}_gain_db", correction + extra)
    return levels


def _fade(audio: np.ndarray, n: int) -> np.ndarray:
    """Fade in/out simmetrico: senza, ogni taglio fa 'click'."""
    if n <= 0 or audio.size == 0:
        return audio
    n = int(min(n, audio.size // 2))
    if n <= 0:
        return audio
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    audio = audio.copy()
    audio[:n] *= ramp
    audio[-n:] *= ramp[::-1]
    return audio


def _slice(track: np.ndarray, start: float, end: float, sr: int) -> np.ndarray:
    i0 = max(0, int(round(start * sr)))
    i1 = min(track.size, int(round(end * sr)))
    if i1 <= i0:
        return np.zeros(0, dtype=np.float32)
    return track[i0:i1].astype(np.float32)


def plan_timeline(events: list[dict], cfg: RenderConfig) -> list[dict]:
    """Calcola la nuova posizione di ogni turno dopo il taglio delle pause."""
    plan: list[dict] = []
    cursor = float(cfg.lead_in_s)
    prev_end = None
    for ev in events:
        duration = max(0.0, float(ev["end"]) - float(ev["start"]))
        if prev_end is None:
            pos = cursor
        else:
            gap = float(ev["start"]) - prev_end
            # gap negativo = i due turni si sovrappongono davvero: lo conservo
            pos = cursor + (gap if gap < 0 else min(gap, cfg.max_gap_s))
            pos = max(0.0, pos)
        plan.append(
            {
                "speaker": ev["speaker"],
                "text": ev.get("text", ""),
                "src_start": float(ev["start"]),
                "src_end": float(ev["end"]),
                "start": round(pos, 3),
                "end": round(pos + duration, 3),
            }
        )
        cursor = max(cursor, pos + duration)
        prev_end = max(prev_end or 0.0, float(ev["end"]))
    return plan


def write_full_mix(session_dir: str | Path, cfg: RenderConfig | None = None) -> Path:
    """Somma le due tracce e salva `registrazione-integrale.wav`.

    È il primo file prodotto e il più semplice: nessun taglio, nessuna
    timeline, solo le due voci coi tempi veri. Se il montaggio non riesce,
    o non fa in tempo, questo c'è comunque.
    """
    session_dir = Path(session_dir)
    cfg = cfg or RenderConfig()
    host, sr = read_wav(session_dir / "host.wav")
    guest, sr_g = read_wav(session_dir / "guest.wav")
    if sr_g != sr:
        raise ValueError("host.wav e guest.wav hanno sample rate diversi")
    events = read_events(session_dir)
    levels = measure_levels({"host": host, "guest": guest}, events, sr, cfg)
    mix = _mix_full(host, guest, cfg, levels)
    return write_wav(session_dir / "registrazione-integrale.wav", mix, sr)


def render_session(session_dir: str | Path, cfg: RenderConfig | None = None) -> RenderResult:
    session_dir = Path(session_dir)
    cfg = cfg or RenderConfig()
    host, sr = read_wav(session_dir / "host.wav")
    guest, sr_g = read_wav(session_dir / "guest.wav")
    if sr_g != sr:
        raise ValueError("host.wav e guest.wav hanno sample rate diversi")
    tracks = {"host": host, "guest": guest}
    raw_duration = max(host.size, guest.size) / sr

    all_events = read_events(session_dir)
    # le due voci vanno pareggiate: un microfono è quasi sempre più basso di
    # una voce sintetica, e la differenza si sente subito
    levels = measure_levels(tracks, all_events, sr, cfg)

    # registrazione integrale: tutto quello che è successo, in un file solo,
    # con i tempi veri. È la copia di sicurezza da cui si riparte sempre.
    integrale = _mix_full(host, guest, cfg, levels)
    full_path = write_wav(session_dir / "registrazione-integrale.wav", integrale, sr)

    events = [e for e in all_events if e["speaker"] in tracks]
    if cfg.drop_greeting:
        events = [e for e in events if e.get("kind") != "greeting"]
    if not events:
        # niente timeline: il montato è la registrazione integrale, meglio di niente
        out = write_wav(session_dir / "podcast.wav", integrale, sr)
        return RenderResult(out, full_path, _to_mp3(out, cfg), _no_transcript(session_dir),
                            _no_transcript(session_dir, "srt"), integrale.size / sr,
                            raw_duration, [], levels)

    plan = plan_timeline(events, cfg)
    total = max(p["end"] for p in plan) + cfg.tail_s
    mixdown = np.zeros(int(round(total * sr)) + 1, dtype=np.float32)
    gains = {"host": _db_to_gain(levels.host_gain_db), "guest": _db_to_gain(levels.guest_gain_db)}
    fade_n = int(sr * cfg.fade_ms / 1000)

    for item in plan:
        audio = _slice(tracks[item["speaker"]], item["src_start"], item["src_end"], sr)
        if audio.size == 0:
            continue
        audio = _fade(audio * gains[item["speaker"]], fade_n)
        at = int(round(item["start"] * sr))
        end = min(at + audio.size, mixdown.size)
        mixdown[at:end] += audio[: end - at]

    out = write_wav(session_dir / "podcast.wav", _normalize(mixdown, cfg.peak_dbfs), sr)
    transcript = _write_transcript(session_dir, plan)
    srt = _write_srt(session_dir, plan)
    return RenderResult(
        wav=out,
        full=full_path,
        mp3=_to_mp3(out, cfg),
        transcript=transcript,
        srt=srt,
        duration=mixdown.size / sr,
        raw_duration=raw_duration,
        segments=plan,
        levels=levels,
        unmatched_host_s=unmatched_host_seconds(host, events, sr),
    )


def _mix_full(host: np.ndarray, guest: np.ndarray, cfg: RenderConfig, levels: Levels) -> np.ndarray:
    n = max(host.size, guest.size)
    mix = np.zeros(n, dtype=np.float32)
    mix[: host.size] += host.astype(np.float32) * _db_to_gain(levels.host_gain_db)
    mix[: guest.size] += guest.astype(np.float32) * _db_to_gain(levels.guest_gain_db)
    return _normalize(mix, cfg.peak_dbfs)


def _normalize(mix: np.ndarray, peak_dbfs: float) -> np.ndarray:
    mix = np.nan_to_num(mix, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0:
        target = _db_to_gain(peak_dbfs) * 32767.0
        mix = mix * (target / peak)
    return np.clip(mix, -32768, 32767).astype(np.int16)


def _timecode(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _speaker_label(session_dir: Path, speaker: str) -> str:
    meta_path = session_dir / "session.json"
    if speaker == "guest" and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return meta.get("persona", {}).get("name") or "Ospite"
        except (json.JSONDecodeError, OSError):
            pass
    return "Conduttore" if speaker == "host" else "Ospite"


def _label_text(item: dict) -> str:
    return item["text"] or "(non trascritto)"


def _write_transcript(session_dir: Path, plan: list[dict]) -> Path:
    lines = [f"# Trascrizione - {session_dir.name}", ""]
    for item in plan:
        who = _speaker_label(session_dir, item["speaker"])
        lines.append(f"**[{_timecode(item['start'])[:-4]}] {who}:** {_label_text(item)}".rstrip())
        lines.append("")
    path = session_dir / "transcript.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_srt(session_dir: Path, plan: list[dict]) -> Path:
    blocks = []
    for i, item in enumerate(plan, start=1):
        who = _speaker_label(session_dir, item["speaker"])
        blocks.append(
            f"{i}\n{_timecode(item['start'])} --> {_timecode(item['end'])}\n"
            f"{who}: {_label_text(item)}\n"
        )
    path = session_dir / "transcript.srt"
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def _no_transcript(session_dir: Path, ext: str = "md") -> Path:
    path = session_dir / f"transcript.{ext}"
    if not path.exists():
        path.write_text("", encoding="utf-8")
    return path


def _to_mp3(wav_path: Path, cfg: RenderConfig) -> Path | None:
    if not cfg.mp3 or not shutil.which("ffmpeg"):
        return None
    mp3_path = wav_path.with_suffix(".mp3")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-codec:a", "libmp3lame", "-b:a", cfg.mp3_bitrate, str(mp3_path)],
        capture_output=True,
        text=True,
    )
    return mp3_path if proc.returncode == 0 else None
