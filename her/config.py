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
    #: solo Gemini: off | low | medium | high | auto | numero di token.
    #: per trascrivere non serve ragionare, e ragionare costa tempo e soldi
    thinking: str = "off"


@dataclass
class LlmConfig:
    provider: str = "openai"       # openai | gemini
    model: str = "gpt-4o"
    temperature: float = 0.8
    max_output_tokens: int = 400
    #: quanti turni precedenti tenere nel contesto
    history_turns: int = 12
    #: solo Gemini: off | low | medium | high | auto | numero di token.
    #: "off" tiene la battuta pronta prima; alzalo se vuoi risposte più meditate
    thinking: str = "off"


@dataclass
class TtsConfig:
    provider: str = "elevenlabs"
    voice_id: str = ""
    model: str = "eleven_turbo_v2_5"
    #: lingua imposta al modello (ISO 639-1). Serve a evitare che una voce
    #: inglese legga l'italiano con l'accento sbagliato. Supportata da
    #: eleven_turbo_v2_5 e eleven_flash_v2_5; "" per non inviarla.
    language: str = "it"
    #: 0-4: più alto = meno latenza, leggermente meno qualità di pronuncia
    optimize_streaming_latency: int = 3
    stability: float = 0.45
    similarity_boost: float = 0.8
    style: float = 0.0
    use_speaker_boost: bool = True
    speed: float = 1.0


#: quanto deve essere lunga una risposta, e quanti token servono per non
#: troncarla a metà frase
LENGTH_RULES = {
    "breve": (
        "LUNGHEZZA: rispondi in 2 o 3 frasi. Vai dritto al punto.",
        220,
    ),
    "media": (
        "LUNGHEZZA: sviluppa la risposta in 4-6 frasi, senza tirarla per le lunghe.",
        500,
    ),
    "lunga": (
        "LUNGHEZZA: sviluppa la risposta in 8-12 frasi, come farebbe un ospite "
        "che è lì per raccontare qualcosa. Argomenta, fai almeno un esempio "
        "concreto, e chiudi dicendo cosa ne pensi. Resta comunque parlato: "
        "frasi brevi una dietro l'altra, non un saggio letto.",
        900,
    ),
    "monologo": (
        "LUNGHEZZA: prenditi tutto lo spazio che serve, anche due o tre minuti. "
        "Racconta, fai esempi, cambia angolazione. Resta parlato: frasi brevi "
        "una dietro l'altra, non un saggio letto.",
        1600,
    ),
}

#: come evitare che tutte le risposte suonino uguali
VARIETY_RULE = (
    "VARIETÀ: non rispondere sempre con lo stesso schema. Alterna: a volte parti "
    "da un esempio concreto o da un episodio, a volte dici subito cosa pensi e "
    "prendi posizione, a volte spieghi e basta. Non fare tutte e tre le cose "
    "nella stessa risposta e non usare due volte di fila la stessa apertura."
)

#: quanto spesso l'ospite può rimandare la palla al conduttore
QUESTION_RULES = {
    "mai": (
        "DOMANDE: non fare domande al conduttore. Le domande le fa lui, tu rispondi. "
        "Se una cosa non ti è chiara, chiedi solo il chiarimento indispensabile."
    ),
    "raramente": (
        "DOMANDE: non rimandare la palla al conduttore. Niente «e tu che ne pensi?», "
        "niente «vuoi che approfondisca?»: se c'è da approfondire, approfondisci. "
        "Una domanda ci sta solo una volta ogni cinque o sei risposte, e solo se "
        "nasce davvero dal discorso."
    ),
    "talvolta": (
        "DOMANDE: ogni tanto — diciamo una risposta su tre — chiudi rilanciando "
        "con una domanda al conduttore, se nasce dal discorso. Le altre volte "
        "chiudi e basta: niente «e tu che ne pensi?» di riempimento."
    ),
    "spesso": (
        "DOMANDE: quando è naturale, chiudi rilanciando con una domanda al conduttore."
    ),
}


@dataclass
class PersonaConfig:
    name: str = "Ospite"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    #: battuta di apertura pronunciata a inizio registrazione ("" = nessuna)
    greeting: str = ""
    #: breve | media | lunga | monologo
    length: str = "media"
    #: mai | raramente | spesso
    questions: str = "raramente"
    #: indicazioni libere da aggiungere al carattere, senza riscrivere il prompt
    #: (es. "sii più ironica", "parla più di musica"). Anche da HER_INDICAZIONI.
    notes: str = ""
    #: il materiale della puntata (appunti + pagine lette), montato da her.context
    briefing: str = ""

    def effective_prompt(self) -> str:
        """Il prompt del preset più le regole di lunghezza e di domande.

        Tenerle fuori dal testo scritto a mano serve a poterle cambiare dal
        `.env` senza riscrivere il personaggio.
        """
        parts = [self.system_prompt.strip(), VARIETY_RULE]
        if self.notes.strip():
            parts.append(f"INDICAZIONI PER OGGI: {self.notes.strip()}")
        if self.briefing.strip():
            parts.append(self.briefing.strip())
        if self.length:
            parts.append(LENGTH_RULES[_valid(self.length, LENGTH_RULES, "persona.length")][0])
        if self.questions:
            parts.append(QUESTION_RULES[_valid(self.questions, QUESTION_RULES, "persona.questions")])
        return "\n\n".join(p for p in parts if p)

    @property
    def min_output_tokens(self) -> int:
        if not self.length:
            return 0
        return LENGTH_RULES[_valid(self.length, LENGTH_RULES, "persona.length")][1]


def _valid(value: str, table: dict, where: str) -> str:
    key = str(value).strip().lower()
    if key not in table:
        raise ValueError(f"{where}: valore «{value}» non valido (usa: {', '.join(table)})")
    return key


@dataclass
class ContextConfig:
    #: file con gli appunti della puntata, caricato da solo se esiste
    file: str = "contesto.md"
    #: scaricare e leggere i link trovati negli appunti
    follow_links: bool = True
    #: farli condensare in punti dall'LLM (costa pochissimo e tiene corto il contesto)
    summarize: bool = True
    max_chars_per_link: int = 6000
    max_links: int = 8
    timeout: float = 20.0


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
    #: il saluto iniziale dell'ospite resta fuori dal montato (c'è comunque
    #: nella registrazione integrale)
    drop_greeting: bool = True
    #: silenzio davanti e in coda al montato
    lead_in_s: float = 0.3
    tail_s: float = 0.8
    #: fade su ogni segmento, in millisecondi: toglie i click ai tagli
    fade_ms: int = 12
    #: picco di normalizzazione in dBFS
    peak_dbfs: float = -1.0
    #: pareggia il volume delle due voci prima di mixarle: un microfono più
    #: basso della voce sintetica è la norma, e a orecchio dà molto fastidio
    match_loudness: bool = True
    #: livello di riferimento del parlato (RMS in dBFS) a cui portare le voci
    target_dbfs: float = -20.0
    #: quanto si può correggere al massimo, per non tirare su anche il rumore
    max_match_db: float = 18.0
    #: ritocco manuale per traccia, applicato dopo il pareggio (dB)
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
    context: ContextConfig = field(default_factory=ContextConfig)
    render: RenderConfig = field(default_factory=RenderConfig)

    def sync(self) -> "Config":
        """Allinea i parametri condivisi e intercetta gli abbinamenti impossibili."""
        self.vad.sample_rate = self.audio.sample_rate
        self.vad.frame_ms = self.audio.frame_ms
        check_model(self.stt.provider, self.stt.model, "stt")
        check_model(self.llm.provider, self.llm.model, "llm")
        # una risposta lunga con pochi token si tronca a metà frase: il tetto
        # non scende mai sotto quello che la lunghezza richiesta comporta
        self.llm.max_output_tokens = max(self.llm.max_output_tokens, self.persona.min_output_tokens)
        return self

    def to_dict(self) -> dict:
        return asdict(self)


#: modello sensato per ogni combinazione provider/sezione, usato quando si
#: cambia provider da riga di comando senza indicare anche il modello
DEFAULT_MODELS = {
    ("openai", "stt"): "gpt-4o-transcribe",
    ("gemini", "stt"): "gemini-3.5-flash-lite",
    ("openai", "llm"): "gpt-4o",
    ("gemini", "llm"): "gemini-3.5-flash-lite",
}


#: prefissi tipici di ogni provider, per accorgersi degli abbinamenti sbagliati
_MODEL_PREFIXES = {
    "openai": ("gpt-", "o1", "o3", "o4", "whisper", "chatgpt"),
    "gemini": ("gemini", "models/gemini", "learnlm", "gemma"),
}


def check_model(provider: str, model: str, section: str) -> None:
    """Un modello OpenAI con provider Gemini (o viceversa) darebbe un 404 oscuro."""
    other = "gemini" if provider == "openai" else "openai"
    if provider not in _MODEL_PREFIXES or other not in _MODEL_PREFIXES:
        return
    name = (model or "").strip().lower()
    if not name or name.startswith(_MODEL_PREFIXES[provider]):
        return
    if name.startswith(_MODEL_PREFIXES[other]):
        raise ValueError(
            f"{section}: il modello «{model}» è di {other}, ma {section}.provider è «{provider}». "
            f"Scegline uno di {provider} (l'elenco con `her models --provider {provider}`)."
        )


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
