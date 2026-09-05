"""Post-produzione: dalle tracce grezze al podcast montato.

Il montaggio usa la timeline (`events.jsonl`) invece di indovinare dove sono i
silenzi: ogni turno viene estratto dalla sua traccia e riappoggiato in fila,
comprimendo le pause di elaborazione a `max_gap_s`. Le sovrapposizioni (quando
interrompi l'ospite) restano sovrapposte.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio.loudness import compress, loudness_lufs
from .audio.media import MediaError, load_audio
from .audio.recorder import read_events
from .audio.wavio import read_wav, write_wav
from .config import RenderConfig


@dataclass
class Levels:
    """Com'erano le due voci e cosa è stato fatto per pareggiarle."""

    host_lufs: float | None = None
    guest_lufs: float | None = None
    host_gain_db: float = 0.0
    guest_gain_db: float = 0.0
    host_compressed: bool = False
    guest_compressed: bool = False
    #: la correzione ha toccato il tetto: la voce resta sotto il target
    host_short_db: float = 0.0
    guest_short_db: float = 0.0

    @property
    def gap_db(self) -> float:
        if self.host_lufs is None or self.guest_lufs is None:
            return 0.0
        return abs(self.host_lufs - self.guest_lufs)


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
    #: spezzoni della tua voce rimessi nel montato guardando l'audio
    recovered: list[dict] = field(default_factory=list)
    #: timeline ricostruita dall'audio perché events.jsonl mancava
    derived_timeline: bool = False
    #: dove è entrata la sigla, e dove la coda musicale
    jingle_at: float | None = None
    outro_at: float | None = None
    #: cose da riferire a chi ha lanciato il montaggio
    notes: list[str] = field(default_factory=list)

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


def _frame_energy(track: np.ndarray, frame: int) -> np.ndarray:
    usable = (track.size // frame) * frame
    if usable < frame:
        return np.zeros(0, dtype=np.float32)
    frames = track[:usable].reshape(-1, frame).astype(np.float32) / 32768.0
    return np.mean(frames * frames, axis=1)


def speech_mask(track: np.ndarray, frame: int, margin_db: float = 25.0,
                floor_dbfs: float = -55.0) -> np.ndarray:
    """Quali frame contengono voce: sopra il fondo, e non troppo sotto i picchi."""
    energy = _frame_energy(track, frame)
    if energy.size == 0:
        return np.zeros(0, dtype=bool)
    db = 10.0 * np.log10(np.maximum(energy, 1e-12))
    if not np.isfinite(db).any():
        return np.zeros(energy.size, dtype=bool)
    return db > max(float(np.max(db)) - margin_db, floor_dbfs)


def _dilate(mask: np.ndarray, frames: int) -> np.ndarray:
    if frames <= 0 or mask.size == 0:
        return mask
    window = np.ones(2 * frames + 1)
    return np.convolve(mask.astype(np.float32), window, mode="same") > 0


def _mask_to_spans(mask: np.ndarray, frame: int, sr: int) -> list[tuple[float, float]]:
    spans, start = [], None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        elif not on and start is not None:
            spans.append((start * frame / sr, i * frame / sr))
            start = None
    if start is not None:
        spans.append((start * frame / sr, mask.size * frame / sr))
    return spans


def recover_host_events(
    host: np.ndarray, guest: np.ndarray, events: list[dict], sr: int, cfg: RenderConfig
) -> list[dict]:
    """Il parlato del conduttore che nella timeline non c'è.

    Il montaggio si basa sui turni riconosciuti, ma la trascrizione può
    perderne pezzi: senza questo recupero, quello che hai detto sparirebbe dal
    montato per colpa di uno strumento che serviva solo a capire le parole.
    Qui si guarda l'audio e basta.
    """
    frame = max(1, int(sr * 0.05))
    mask = speech_mask(host, frame)
    if mask.size == 0:
        return []

    if not cfg.recover_over_guest:
        # dove parla l'ospite non si recupera: senza cuffie quella è la sua
        # voce rientrata nel microfono, e la si sentirebbe doppia
        guest_mask = _dilate(speech_mask(guest, frame), 4)
        common = min(mask.size, guest_mask.size)
        mask[:common] &= ~guest_mask[:common]

    mask = _dilate(mask, int(round(cfg.recover_pad_s * sr / frame)))

    # mai sovrapporsi a un turno già in timeline: sarebbe la stessa voce due volte
    for ev in events:
        if ev["speaker"] != "host":
            continue
        start = max(0, int(float(ev["start"]) * sr) // frame)
        end = min(mask.size, int(np.ceil(float(ev["end"]) * sr / frame)))
        mask[start:end] = False

    return [
        {"speaker": "host", "start": round(a, 3), "end": round(b, 3), "text": "", "kind": "recuperato"}
        for a, b in _mask_to_spans(mask, frame, sr)
        if b - a >= cfg.recover_min_s
    ]


def derive_events_from_audio(
    host: np.ndarray, guest: np.ndarray, sr: int, cfg: RenderConfig
) -> list[dict]:
    """Una timeline ricavata dal solo audio, quando quella scritta non c'è.

    Se `events.jsonl` è andato perduto il montaggio non saprebbe dove tagliare
    e restituirebbe la registrazione intera. Le due tracce però dicono già
    tutto: la voce dell'ospite è esattamente dove la sua traccia non è muta.
    """
    frame = max(1, int(sr * 0.05))
    pad = int(round(cfg.recover_pad_s * sr / frame))
    guest_spans = _mask_to_spans(_dilate(speech_mask(guest, frame), pad), frame, sr)
    events = [
        {"speaker": "guest", "start": round(a, 3), "end": round(b, 3), "text": "", "kind": "audio"}
        for a, b in guest_spans
        if b - a >= cfg.recover_min_s
    ]
    events += recover_host_events(host, guest, [], sr, cfg)
    return sorted(events, key=lambda e: (e["start"], e["end"]))


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


def _material(track: np.ndarray, spans: list[tuple[float, float]] | None, sr: int) -> np.ndarray:
    """Solo i pezzi in cui quella voce parla: il resto è silenzio e falserebbe."""
    if not spans:
        return track
    pieces = [_slice(track, a, b, sr) for a, b in spans]
    pieces = [p for p in pieces if p.size]
    return np.concatenate(pieces) if pieces else track


def prepare_tracks(
    tracks: dict, events: list[dict], sr: int, cfg: RenderConfig
) -> tuple[dict, Levels]:
    """Porta le due voci allo stesso volume percepito, e le rende ascoltabili insieme.

    Tre passaggi per traccia: misura in LUFS (lo standard dei podcast), guadagno
    per arrivare al target, e per la voce al microfono una compressione leggera —
    senza, le parole dette piano restano sotto quelle della voce sintetica, che
    è compressa in partenza.
    """
    levels = Levels()
    out: dict = {}
    for speaker, track in tracks.items():
        spans = [(float(e["start"]), float(e["end"])) for e in events if e["speaker"] == speaker]
        measured = loudness_lufs(_material(track, spans or None, sr), sr)
        setattr(levels, f"{speaker}_lufs", measured)

        # 1. porta la voce al volume di riferimento
        auto_db = 0.0
        if cfg.match_loudness and measured is not None:
            voluto = cfg.target_lufs - measured
            auto_db = float(np.clip(voluto, -cfg.max_match_db, cfg.max_match_db))
            # se serviva più del consentito, la voce resta sotto: va detto,
            # perché il rimedio non è nel montaggio ma nel microfono
            setattr(levels, f"{speaker}_short_db", round(float(voluto - auto_db), 1))
        audio = track.astype(np.float32) * _db_to_gain(auto_db)

        # 2. comprimi la dinamica (solo dove serve: la voce sintetica è già densa)
        if (cfg.compress_host if speaker == "host" else cfg.compress_guest) and measured is not None:
            audio = compress(
                audio,
                sr,
                threshold_db=cfg.target_lufs + cfg.compress_threshold_offset_db,
                ratio=cfg.compress_ratio,
            )
            setattr(levels, f"{speaker}_compressed", True)
            after = loudness_lufs(_material(audio, spans or None, sr), sr) if cfg.match_loudness else None
            if after is not None:
                # la compressione abbassa il volume: si recupera, ma il tetto
                # vale sulla correzione totale, o su una traccia quasi muta si
                # finirebbe per amplificare solo il fruscio
                total = float(np.clip(auto_db + (cfg.target_lufs - after),
                                      -cfg.max_match_db, cfg.max_match_db))
                audio *= _db_to_gain(total - auto_db)
                auto_db = total

        # 3. il ritocco manuale si applica per ultimo, così non viene mangiato
        manual_db = cfg.host_gain_db if speaker == "host" else cfg.guest_gain_db
        if manual_db:
            audio = audio * _db_to_gain(manual_db)

        setattr(levels, f"{speaker}_gain_db", auto_db + manual_db)
        out[speaker] = audio
    return out, levels


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


def normalize_phrase(text: str) -> str:
    """Confronto indulgente: la trascrizione non scrive due volte uguale.

    Accenti, apostrofi e punteggiatura spariscono, così «questo è L'altra
    intelligenza» e «questo e laltra intelligenza» sono la stessa cosa.
    """
    piatto = unicodedata.normalize("NFKD", text or "")
    piatto = "".join(c for c in piatto if not unicodedata.combining(c)).lower()
    piatto = piatto.replace("'", "").replace("’", "")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", piatto)).strip()


def place_jingle(plan: list[dict], cfg: RenderConfig, durata: float) -> float | None:
    """Infila la sigla dopo la frase che la annuncia, spostando in avanti il resto.

    La sigla entra *sotto* la coda della frase — è quello che fa suonare una
    sigla come una sigla, invece che come un file attaccato dopo.
    """
    if durata <= 0 or not cfg.jingle_after.strip():
        return None
    cercata = normalize_phrase(cfg.jingle_after)
    indice = next(
        (i for i, item in enumerate(plan)
         if item["speaker"] == "host" and cercata in normalize_phrase(item.get("text", ""))),
        None,
    )
    if indice is None:
        return None

    inizio = max(0.0, plan[indice]["end"] - cfg.jingle_overlap_s)
    riprende = inizio + durata + cfg.jingle_tail_s
    spostamento = max(0.0, riprende - plan[indice]["end"])
    for item in plan[indice + 1:]:
        item["start"] = round(item["start"] + spostamento, 3)
        item["end"] = round(item["end"] + spostamento, 3)
    return round(inizio, 3)


def pad_events(events: list[dict], cfg: RenderConfig, duration: float) -> list[dict]:
    """Allarga ogni turno di un filo prima e dopo.

    L'endpointer chiude il turno appena sente silenzio, e taglia la coda: senza
    un margine il montato mangia l'ultima sillaba e l'attacco della successiva.
    Il margine non può invadere il turno precedente della stessa voce, o la
    stessa frase finirebbe due volte nel montaggio.
    """
    padded: list[dict] = []
    last_end: dict[str, float] = {}
    for ev in sorted(events, key=lambda e: (e["start"], e["end"])):
        speaker = ev["speaker"]
        start = max(0.0, float(ev["start"]) - cfg.edge_pad_in_s, last_end.get(speaker, 0.0))
        end = min(duration, float(ev["end"]) + cfg.edge_pad_out_s)
        if end <= start:
            start, end = float(ev["start"]), float(ev["end"])
        padded.append({**ev, "start": round(start, 3), "end": round(end, 3)})
        last_end[speaker] = end
    return padded


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
    trattate, _ = prepare_tracks({"host": host, "guest": guest}, events, sr, cfg)
    mix = _mix_full(trattate["host"], trattate["guest"], cfg)
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
    # le due voci vanno pareggiate e rese ascoltabili insieme: un microfono è
    # quasi sempre più basso, e più dinamico, di una voce sintetica
    trattate, levels = prepare_tracks(tracks, all_events, sr, cfg)

    # registrazione integrale: tutto quello che è successo, in un file solo,
    # con i tempi veri. È la copia di sicurezza da cui si riparte sempre.
    integrale = _mix_full(trattate["host"], trattate["guest"], cfg)
    full_path = write_wav(session_dir / "registrazione-integrale.wav", integrale, sr)

    events = [e for e in all_events if e["speaker"] in tracks]
    if cfg.drop_greeting:
        events = [e for e in events if e.get("kind") != "greeting"]

    derived = False
    if not events:
        # timeline persa: la si ricava dall'audio, invece di rinunciare a tagliare
        events = derive_events_from_audio(host, guest, sr, cfg)
        derived = bool(events)
    if not events:
        # niente timeline: il montato è la registrazione integrale, meglio di niente
        out = write_wav(session_dir / "podcast.wav", integrale, sr)
        return RenderResult(out, full_path, _to_mp3(out, cfg), _no_transcript(session_dir),
                            _no_transcript(session_dir, "srt"), integrale.size / sr,
                            raw_duration, [], levels)

    recovered: list[dict] = []
    if cfg.recover_host_audio and not derived:
        # quello che hai detto non deve dipendere da cosa ha capito la
        # trascrizione: i pezzi mancanti si ritrovano guardando l'audio
        recovered = recover_host_events(host, guest, events, sr, cfg)
        events = sorted(events + recovered, key=lambda e: (e["start"], e["end"]))

    plan = plan_timeline(pad_events(events, cfg, host.size / sr), cfg)

    note: list[str] = []
    sigla, sigla_a = _load_extra(cfg.jingle_file, cfg.jingle_gain_db, sr, note, "sigla"), None
    if sigla is not None:
        sigla_a = place_jingle(plan, cfg, sigla.size / sr)
        if sigla_a is None:
            note.append(f"sigla non inserita: nel parlato non compare «{cfg.jingle_after}»")
    coda = _load_extra(cfg.outro_file, cfg.outro_gain_db, sr, note, "coda musicale")

    fine_parlato = max(p["end"] for p in plan)
    coda_a = round(fine_parlato + cfg.outro_lead_s, 3) if coda is not None else None
    total = fine_parlato + cfg.tail_s
    if sigla is not None and sigla_a is not None:
        total = max(total, sigla_a + sigla.size / sr + cfg.tail_s)
    if coda is not None and coda_a is not None:
        total = max(total, coda_a + coda.size / sr + cfg.tail_s)
    mixdown = np.zeros(int(round(total * sr)) + 1, dtype=np.float32)
    fade_n = int(sr * cfg.fade_ms / 1000)

    for item in plan:
        audio = _slice(trattate[item["speaker"]], item["src_start"], item["src_end"], sr)
        if audio.size == 0:
            continue
        audio = _fade(audio, fade_n)
        at = int(round(item["start"] * sr))
        end = min(at + audio.size, mixdown.size)
        mixdown[at:end] += audio[: end - at]

    for musica, quando in ((sigla, sigla_a), (coda, coda_a)):
        if musica is None or quando is None:
            continue
        at = int(round(quando * sr))
        fine = min(at + musica.size, mixdown.size)
        mixdown[at:fine] += musica[: fine - at]

    out = write_wav(session_dir / "podcast.wav", _normalize(mixdown, cfg.peak_dbfs), sr)
    transcript = _write_transcript(session_dir, plan, sigla_a, coda_a)
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
        jingle_at=sigla_a,
        outro_at=coda_a,
        notes=note,
        unmatched_host_s=unmatched_host_seconds(host, events, sr),
        recovered=recovered,
        derived_timeline=derived,
    )


def _mix_full(host: np.ndarray, guest: np.ndarray, cfg: RenderConfig) -> np.ndarray:
    """Somma due tracce già portate al volume giusto."""
    n = max(host.size, guest.size)
    mix = np.zeros(n, dtype=np.float32)
    mix[: host.size] += host.astype(np.float32)
    mix[: guest.size] += guest.astype(np.float32)
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


def _load_extra(percorso: str, gain_db: float, sr: int, note: list[str], come: str):
    """Carica sigla o coda musicale, se il file c'è. Un problema non ferma il montaggio."""
    if not percorso:
        return None
    path = Path(percorso)
    if not path.exists():
        return None
    try:
        audio = load_audio(path, sr) * _db_to_gain(gain_db)
    except MediaError as exc:
        note.append(f"{come} non usata: {exc}")
        return None
    if audio.size == 0:
        return None
    # una musica che entra e esce di netto si sente: mezzo secondo di respiro
    audio = _fade(audio, int(sr * 0.5))
    note.append(f"{come}: {path.name}, {audio.size / sr:.1f}s")
    return audio


def _label_text(item: dict) -> str:
    return item["text"] or "(non trascritto)"


def _write_transcript(session_dir: Path, plan: list[dict],
                      sigla_a: float | None = None, coda_a: float | None = None) -> Path:
    lines = [f"# Trascrizione - {session_dir.name}", ""]
    segnalibri = [(t, nome) for t, nome in ((sigla_a, "sigla"), (coda_a, "coda musicale"))
                  if t is not None]
    for item in plan:
        for t, nome in list(segnalibri):
            if t <= item["start"]:
                lines.append(f"*[{_timecode(t)[:-4]}] — {nome} —*")
                lines.append("")
                segnalibri.remove((t, nome))
        who = _speaker_label(session_dir, item["speaker"])
        lines.append(f"**[{_timecode(item['start'])[:-4]}] {who}:** {_label_text(item)}".rstrip())
        lines.append("")
    for t, nome in segnalibri:
        lines.append(f"*[{_timecode(t)[:-4]}] — {nome} —*")
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
