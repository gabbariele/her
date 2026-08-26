"""Interfaccia a riga di comando di `her`."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import (
    DEFAULT_MODELS,
    ELEVEN_KEYS,
    LENGTH_RULES,
    QUESTION_RULES,
    GEMINI_KEYS,
    OPENAI_KEYS,
    Config,
    api_key,
    load_config,
    load_env,
)
from .render import render_session
from .session import PodcastSession, new_session_dir

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"


def _overrides(args: argparse.Namespace) -> dict:
    out: dict = {"audio": {}, "vad": {}, "llm": {}, "stt": {},
                 "tts": {}, "session": {}, "render": {}, "persona": {}}
    if getattr(args, "pausa", None) is not None:
        out["vad"]["silence_ms"] = int(float(args.pausa) * 1000)
    if getattr(args, "lunghezza", None):
        out["persona"]["length"] = args.lunghezza
    if getattr(args, "domande", None):
        out["persona"]["questions"] = args.domande
    if getattr(args, "voice", None):
        out["tts"]["voice_id"] = args.voice
    if getattr(args, "tts_model", None):
        out["tts"]["model"] = args.tts_model
    for section in ("llm", "stt"):
        provider = getattr(args, section, None)
        model = getattr(args, f"{section}_model", None)
        if provider:
            out[section]["provider"] = provider
            # cambiare provider senza dire quale modello: ne scegliamo uno sensato,
            # altrimenti resterebbe quello dell'altro provider e la chiamata fallirebbe
            if not model:
                out[section]["model"] = DEFAULT_MODELS[(provider, section)]
        if model:
            out[section]["model"] = model
    if getattr(args, "input_device", None) is not None:
        out["audio"]["input_device"] = _device(args.input_device)
    if getattr(args, "output_device", None) is not None:
        out["audio"]["output_device"] = _device(args.output_device)
    if getattr(args, "barge_in", False):
        out["session"]["barge_in"] = True
    if getattr(args, "no_render", False):
        out["session"]["autorender"] = False
    if getattr(args, "max_gap", None) is not None:
        out["render"]["max_gap_s"] = args.max_gap
    if getattr(args, "no_mp3", False):
        out["render"]["mp3"] = False
    return {k: v for k, v in out.items() if v}


def _mmss(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def _device(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _load(args: argparse.Namespace) -> Config:
    preset = getattr(args, "preset", None) or os.environ.get("HER_PRESET") or None
    cfg = load_config(preset, _overrides(args))
    if not cfg.tts.voice_id:
        # comodo per chi non vuole toccare i preset: basta HER_VOICE_ID nel .env
        cfg.tts.voice_id = os.environ.get("HER_VOICE_ID", "")
    # le manopole del carattere si possono girare dal .env, senza aprire i preset
    if os.environ.get("HER_LUNGHEZZA") and not getattr(args, "lunghezza", None):
        cfg.persona.length = os.environ["HER_LUNGHEZZA"].strip().lower()
    if os.environ.get("HER_DOMANDE") and not getattr(args, "domande", None):
        cfg.persona.questions = os.environ["HER_DOMANDE"].strip().lower()
    if os.environ.get("HER_INDICAZIONI") and not getattr(args, "indicazioni", None):
        cfg.persona.notes = os.environ["HER_INDICAZIONI"].strip()
    if getattr(args, "indicazioni", None):
        cfg.persona.notes = args.indicazioni
    cfg.sync()
    pausa = os.environ.get("HER_PAUSA")
    if pausa and getattr(args, "pausa", None) is None:
        try:
            cfg.vad.silence_ms = int(float(pausa.replace(",", ".")) * 1000)
        except ValueError:
            raise ValueError(f"HER_PAUSA deve essere un numero di secondi, non {pausa!r}") from None
    context_file = getattr(args, "context", None)
    if context_file:
        extra = Path(context_file).read_text(encoding="utf-8").strip()
        cfg.persona.system_prompt = f"{cfg.persona.system_prompt}\n\n{extra}"
    return cfg


# -- comandi ---------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    cfg = _load(args)
    rows = [
        ("OpenAI", api_key(*OPENAI_KEYS)),
        ("Gemini", api_key(*GEMINI_KEYS)),
        ("ElevenLabs", api_key(*ELEVEN_KEYS)),
    ]
    print("Chiavi API:")
    for name, key in rows:
        print(f"  {'OK ' if key else '-- '} {name:<12} {('…' + key[-4:]) if key else 'assente'}")
    print("\nConfigurazione attiva:")
    thinking = f", thinking: {cfg.llm.thinking}" if cfg.llm.provider == "gemini" else ""
    print(f"  STT   {cfg.stt.provider}/{cfg.stt.model} (lingua: {cfg.stt.language})")
    print(f"  LLM   {cfg.llm.provider}/{cfg.llm.model}{thinking}")
    print(f"  TTS   {cfg.tts.provider}/{cfg.tts.model} voce: {cfg.tts.voice_id or 'NON IMPOSTATA'}"
          f" (lingua: {cfg.tts.language or 'automatica'})")
    print(f"  Audio {cfg.audio.sample_rate} Hz · attesa prima della risposta: "
          f"{cfg.vad.silence_ms / 1000:.1f}s")
    print(f"  Ospite: {cfg.persona.name} · risposte: {cfg.persona.length} "
          f"· domande al conduttore: {cfg.persona.questions}")

    needed = {"openai": OPENAI_KEYS, "gemini": GEMINI_KEYS}
    missing = []
    for provider in (cfg.stt.provider, cfg.llm.provider):
        if provider in needed and not api_key(*needed[provider]):
            missing.append(provider)
    if not api_key(*ELEVEN_KEYS):
        missing.append("elevenlabs")
    if not cfg.tts.voice_id:
        missing.append("tts.voice_id")
    if missing:
        print(f"\nManca: {', '.join(sorted(set(missing)))}")
        return 1
    print("\nTutto pronto: `her record`")
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    from .audio.devices import format_devices

    print("Dispositivi audio:")
    print(format_devices())
    return 0


def cmd_voices(args: argparse.Namespace) -> int:
    from .providers.tts import list_voices

    voices = list_voices()
    needle = (args.search or "").lower()
    for voice in voices:
        name = voice.get("name", "?")
        if needle and needle not in name.lower():
            continue
        labels = voice.get("labels") or {}
        tags = ", ".join(f"{k}={v}" for k, v in labels.items() if v)
        print(f"  {voice.get('voice_id')}  {name:<22} {tags}")
    print(f"\n{len(voices)} voci. Copia l'id e mettilo in HER_VOICE_ID dentro il file .env.")
    print("Per un podcast in italiano scegli una voce italiana o multilingua: la lingua "
          "viene imposta al modello, ma l'accento resta quello di chi ha inciso la voce.")
    return 0


def cmd_say(args: argparse.Namespace) -> int:
    """Prova rapida della voce scelta."""
    from .audio.wavio import write_wav
    from .providers.tts import synthesize

    cfg = _load(args)
    audio = synthesize(args.text, cfg.tts, cfg.audio.sample_rate)
    out = Path(args.out or "prova-voce.wav")
    write_wav(out, audio, cfg.audio.sample_rate)
    print(f"{out} ({audio.size / cfg.audio.sample_rate:.1f}s)")
    if not args.no_play:
        try:
            from .audio.player import Player

            with Player(cfg.audio.sample_rate, device=cfg.audio.output_device) as player:
                player.play([audio])
        except Exception as exc:
            print(f"(riproduzione non disponibile: {exc})")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not cfg.tts.voice_id:
        print("Nessuna voce impostata: scegline una con `her voices` e passa --voice <id>.", file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else new_session_dir(args.sessions, args.name)
    print(f"Sessione: {out_dir}")
    session = PodcastSession(cfg, out_dir, text_input=args.text)
    session.run()
    print(f"\nRegistrato: {session.recorder.duration:.1f}s in {out_dir}")
    if cfg.session.autorender:
        return _render(out_dir, cfg)
    print(f"Monta quando vuoi con: her render {out_dir}")
    return 0


def latest_session(root: str = "sessions") -> Path | None:
    """L'ultima puntata registrata: è quasi sempre quella che si vuole montare."""
    base = Path(root)
    if not base.exists():
        return None
    sessions = [d for d in base.iterdir() if d.is_dir() and (d / "host.wav").exists()]
    if not sessions:
        return None
    return max(sessions, key=lambda d: d.stat().st_mtime)


def cmd_render(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if args.session:
        session_dir = Path(args.session)
    else:
        session_dir = latest_session(args.sessions)
        if session_dir is None:
            print(f"Nessuna puntata trovata in {args.sessions}/. "
                  "Indica la cartella: her render sessions\\<nome>", file=sys.stderr)
            return 1
        print(f"Ultima puntata: {session_dir}")
    if not (session_dir / "host.wav").exists():
        print(f"{session_dir} non sembra una sessione (manca host.wav).", file=sys.stderr)
        return 1
    return _render(session_dir, cfg)


def _render(session_dir: Path, cfg: Config) -> int:
    result = render_session(session_dir, cfg.render)
    print(f"\nMontato:   {result.wav}  ({_mmss(result.duration)}, tagliati {_mmss(result.saved)} di vuoti)")
    if result.mp3:
        print(f"MP3:       {result.mp3}")
    print(f"Integrale: {result.full}  ({_mmss(result.raw_duration)}, tutto, pause comprese)")
    print(f"Testi:     {result.transcript} · {result.srt}")
    print("\nDa pubblicare è il file «podcast»: le due voci insieme, senza i vuoti.")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Cosa offre davvero la tua chiave: i nomi dei modelli cambiano spesso."""
    from .providers.models import list_models

    cfg = _load(args)
    provider = args.provider or cfg.llm.provider
    models = list_models(provider)
    needle = (args.search or "").lower()
    shown = 0
    for model in models:
        if not model["usable"]:
            continue
        if needle and needle not in model["id"].lower():
            continue
        shown += 1
        print(f"  {model['id']:<42} {model['name']}".rstrip())
    print(f"\n{shown} modelli utilizzabili su {provider}.")
    print("Usa il nome con  --llm-model <nome>  /  --stt-model <nome>, o mettilo nel preset.")
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    for path in sorted(PRESET_DIR.glob("*.yaml")):
        print(f"  {path.stem:<16} {path}")
    return 0


# -- parser ----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="her",
        description="Registra un podcast conversando in tempo reale con un ospite AI.",
    )
    parser.add_argument("--version", action="version", version=f"her {__version__}")
    parser.add_argument("--env", default=".env", help="file con le chiavi API (default: .env)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, full: bool = True) -> None:
        p.add_argument("-p", "--preset", help="preset YAML (nome in presets/ o percorso)")
        p.add_argument("--context", help="file di testo da aggiungere al contesto dell'ospite")
        p.add_argument("--lunghezza", choices=list(LENGTH_RULES),
                       help="quanto parla l'ospite (default: media)")
        p.add_argument("--domande", choices=list(QUESTION_RULES),
                       help="quanto spesso rilancia con una domanda (default: raramente)")
        p.add_argument("--indicazioni", metavar="TESTO",
                       help="indicazione libera sul carattere (es. \"sii più ironica\")")
        if full:
            p.add_argument("--voice", help="voice_id ElevenLabs")
            p.add_argument("--tts-model", help="modello ElevenLabs (es. eleven_flash_v2_5)")
            p.add_argument("--llm", choices=["openai", "gemini"])
            p.add_argument("--llm-model")
            p.add_argument("--stt", choices=["openai", "gemini"])
            p.add_argument("--stt-model")
            p.add_argument("--input-device")
            p.add_argument("--output-device")

    p_check = sub.add_parser("check", help="verifica chiavi e configurazione")
    common(p_check)
    p_check.set_defaults(func=cmd_check)

    p_dev = sub.add_parser("devices", help="elenca i dispositivi audio")
    p_dev.set_defaults(func=cmd_devices)

    p_voices = sub.add_parser("voices", help="elenca le voci ElevenLabs")
    p_voices.add_argument("--search", help="filtra per nome")
    p_voices.set_defaults(func=cmd_voices)

    p_say = sub.add_parser("say", help="prova la voce su una frase")
    common(p_say)
    p_say.add_argument("text")
    p_say.add_argument("-o", "--out")
    p_say.add_argument("--no-play", action="store_true")
    p_say.set_defaults(func=cmd_say)

    p_rec = sub.add_parser("record", help="registra una puntata")
    common(p_rec)
    p_rec.add_argument("--out", help="cartella della sessione")
    p_rec.add_argument("--sessions", default="sessions", help="cartella radice delle sessioni")
    p_rec.add_argument("--name", help="nome della sessione")
    p_rec.add_argument("--text", action="store_true", help="scrivi invece di parlare (per provare)")
    p_rec.add_argument("--pausa", type=float, metavar="SECONDI",
                       help="silenzio da aspettare prima che l'ospite risponda (default: 1.2)")
    p_rec.add_argument("--barge-in", action="store_true", help="puoi interrompere l'ospite (usa le cuffie)")
    p_rec.add_argument("--no-render", action="store_true", help="non montare a fine registrazione")
    p_rec.add_argument("--max-gap", type=float, help="pausa massima nel montaggio (s)")
    p_rec.add_argument("--no-mp3", action="store_true")
    p_rec.set_defaults(func=cmd_record)

    p_ren = sub.add_parser("render", help="monta una sessione già registrata")
    common(p_ren, full=False)
    p_ren.add_argument("session", nargs="?", help="cartella della puntata (default: l'ultima)")
    p_ren.add_argument("--sessions", default="sessions", help="cartella radice delle puntate")
    p_ren.add_argument("--max-gap", type=float, help="pausa massima fra i turni (s)")
    p_ren.add_argument("--no-mp3", action="store_true")
    p_ren.set_defaults(func=cmd_render)

    p_mod = sub.add_parser("models", help="elenca i modelli disponibili con la tua chiave")
    common(p_mod)
    p_mod.add_argument("--provider", choices=["openai", "gemini"], help="default: quello del preset")
    p_mod.add_argument("--search", help="filtra per nome")
    p_mod.set_defaults(func=cmd_models)

    p_pre = sub.add_parser("presets", help="elenca i preset disponibili")
    p_pre.set_defaults(func=cmd_presets)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env(args.env)
    if os.environ.get("HER_NO_COLOR"):
        from . import session as session_module

        for attr in ("HOST", "GUEST", "DIM", "WARN", "OFF"):
            setattr(session_module.Ansi, attr, "")
    from .audio.devices import AudioUnavailable
    from .providers.llm import LlmError
    from .providers.models import ModelsError
    from .providers.stt import SttError
    from .providers.tts import TtsError

    try:
        return args.func(args)
    except (AudioUnavailable, SttError, LlmError, TtsError, ModelsError,
            FileNotFoundError, ValueError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
