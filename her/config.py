"""Configurazione: valori di default + preset YAML + variabili d'ambiente."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from .audio.vad import VadConfig

DEFAULT_SYSTEM_PROMPT = (
    "Sei l'ospite di un podcast, in conversazione dal vivo con il conduttore. "
    "Parli in italiano, in modo colloquiale e diretto. Rispondi in 2-4 frasi: "
    "è una chiacchierata, non una conferenza. Non elencare punti numerati, non "
    "usare formattazione: quello che dici viene letto ad alta voce. Fai domande "
    "al conduttore quando è naturale farle."
)


@dataclass
class AudioConfig:
    sample_rate: int = 24000       # ElevenLabs esporta PCM a 24 kHz: niente resampling
    frame_ms: int = 20
    input_device: Any = None       # indice o nome (vedi `her devices`)
    output_device: Any = None


@dataclass
class SttConfig:
    provider: str = "openai"       # openai | gemini
    model: str = "gpt-4o-transcribe"
    language: str = "it"
    #: suggerimenti di vocabolario (nomi propri, sigle) per ridurre gli errori
    hint: str = ""


@dataclass
class LlmConfig:
    provider: str = "openai"       # openai | gemini
    model: str = "gpt-4o"
    temperature: float = 0.8
    max_output_tokens: int = 400
    #: quanti turni precedenti tenere nel contesto
    history_turns: int = 12


@dataclass
class TtsConfig:
    provider: str = "elevenlabs"
    voice_id: str = ""
    model: str = "eleven_turbo_v2_5"
    #: 0-4: più alto = meno latenza, leggermente meno qualità di pronuncia
    optimize_streaming_latency: int = 3
    stability: float = 0.45
    similarity_boost: float = 0.8
    style: float = 0.0
    use_speaker_boost: bool = True
    speed: float = 1.0


@dataclass
class PersonaConfig:
    name: str = "Ospite"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    #: battuta di apertura pronunciata a inizio registrazione ("" = nessuna)
    greeting: str = ""


@dataclass
class SessionConfig:
    #: microfono chiuso mentre l'ospite parla: evita rientri se usi gli altoparlanti
    half_duplex: bool = True
    #: interrompere l'ospite parlandogli sopra (richiede le cuffie)
    barge_in: bool = False
    #: renderizza il podcast automaticamente alla fine della registrazione
    autorender: bool = True


@dataclass
class RenderConfig:
    #: pausa massima lasciata fra un turno e l'altro (i vuoti vengono tagliati)
    max_gap_s: float = 0.45
    #: silenzio davanti e in coda al montato
    lead_in_s: float = 0.3
    tail_s: float = 0.8
    #: fade su ogni segmento, in millisecondi: toglie i click ai tagli
    fade_ms: int = 12
    #: picco di normalizzazione in dBFS
    peak_dbfs: float = -1.0
    #: guadagno per traccia (dB)
    host_gain_db: float = 0.0
    guest_gain_db: float = 0.0
    #: esporta anche l'mp3 (richiede ffmpeg nel PATH)
    mp3: bool = True
    mp3_bitrate: str = "192k"


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    render: RenderConfig = field(default_factory=RenderConfig)

    def sync(self) -> "Config":
        """Allinea i parametri condivisi fra sezioni diverse."""
        self.vad.sample_rate = self.audio.sample_rate
        self.vad.frame_ms = self.audio.frame_ms
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def _apply(obj: Any, data: dict, path: str = "") -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"chiave di configurazione sconosciuta: {path}{key}")
        current = getattr(obj, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply(current, value, f"{path}{key}.")
            continue
        ftype = known[key].type
        if value is not None and ftype in ("int", int):
            value = int(value)
        elif value is not None and ftype in ("float", float):
            value = float(value)
        elif value is not None and ftype in ("bool", bool):
            value = bool(value)
        setattr(obj, key, value)


def load_config(preset: str | Path | None = None, overrides: dict | None = None) -> Config:
    """Default -> preset YAML -> override da riga di comando."""
    cfg = Config()
    if preset:
        path = Path(preset)
        if not path.exists() and not path.suffix:
            path = Path(f"{preset}.yaml")
        if not path.exists():
            candidate = Path(__file__).resolve().parent.parent / "presets" / path.name
            if candidate.exists():
                path = candidate
        if not path.exists():
            raise FileNotFoundError(f"preset non trovato: {preset}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: il preset deve essere un dizionario YAML")
        _apply(cfg, data)
    if overrides:
        _apply(cfg, {k: v for k, v in overrides.items() if v is not None})
    return cfg.sync()


def load_env(path: str | Path = ".env") -> None:
    """Carica un .env senza dipendenze esterne (non sovrascrive l'ambiente)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def api_key(*names: str) -> str | None:
    """Prima chiave valorizzata fra quelle indicate.

    I segnaposto lasciati nel `.env` (`sk-...`, `...`) contano come assenti:
    altrimenti `her check` direbbe che è tutto a posto quando non lo è.
    """
    for name in names:
        value = (os.environ.get(name) or "").strip().strip('"').strip("'")
        if value and "..." not in value:
            return value
    return None


OPENAI_KEYS = ("OPENAI_API_KEY",)
GEMINI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
ELEVEN_KEYS = ("ELEVENLABS_API_KEY", "ELEVEN_API_KEY", "XI_API_KEY")
