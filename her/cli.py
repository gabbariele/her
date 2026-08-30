"""Interfaccia a riga di comando di `her`."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, code_date
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


def context_notes(args: argparse.Namespace, cfg: Config) -> tuple[str, Path | None]:
    """Gli appunti della puntata: quelli indicati con --context, o contesto.md."""
    chosen = getattr(args, "context", None)
    path = Path(chosen) if chosen else Path(cfg.context.file)
    if not path.exists():
        if chosen:
            raise FileNotFoundError(f"file di contesto non trovato: {path}")
        return "", None
    return path.read_text(encoding="utf-8"), path


def prepare_context(args: argparse.Namespace, cfg: Config) -> str:
    """Legge gli appunti, segue i link e prepara il materiale per l'ospite."""
    from .context import build_briefing

    notes, path = context_notes(args, cfg)
    if not notes.strip():
        return ""
    print(f"Contesto: {path}")
    briefing = build_briefing(
        notes,
        cfg.context,
        cfg.llm,
        reload=getattr(args, "ricarica", False),
        notice=lambda msg: print(f"  {msg}"),
    )
    cfg.persona.briefing = briefing
    return briefing


def cmd_context(args: argparse.Namespace) -> int:
    """Mostra il materiale che l'ospite avrà in mano: si controlla prima di registrare."""
    from .context import TEMPLATE

    cfg = _load(args)
    path = Path(getattr(args, "context", None) or cfg.context.file)
    if not path.exists():
        path.write_text(TEMPLATE, encoding="utf-8")
        print(f"Creato {path}: scrivici il contesto della puntata e rilancia.")
        return 0
    briefing = prepare_context(args, cfg)
    if not briefing:
        print(f"{path} è vuoto: scrivici cosa deve sapere l'ospite.")
        return 0
    print("\n" + "=" * 72)
    print(briefing)
    print("=" * 72)
    print(f"\n{len(briefing)} caratteri, che l'ospite avrà presenti per tutta la puntata.")
    return 0


def _code_mtime() -> float:
    """Data del codice installato: un montato più vecchio è stato fatto con altre regole."""
    root = Path(__file__).resolve().parent
    return max((f.stat().st_mtime for f in root.rglob("*.py")), default=0.0)


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
    regia = os.environ.get("HER_REGIA", "").strip().lower()
    if regia in ("off", "no", "0", "spenta", "false"):
        cfg.suggester.enabled = False
    elif regia in ("on", "si", "sì", "1", "true"):
        cfg.suggester.enabled = True
    if getattr(args, "no_regia", False):
        cfg.suggester.enabled = False
    modello_regia = os.environ.get("HER_REGIA_MODELLO", "").strip()
    if modello_regia:
        cfg.suggester.model = modello_regia
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
    if getattr(args, "no_link", False):
        cfg.context.follow_links = False
    return cfg


# -- comandi ---------------------------------------------------------------
def cmd_check(args: argparse.Namespace) -> int:
    cfg = _load(args)
    rows = [
        ("OpenAI", api_key(*OPENAI_KEYS)),
        ("Gemini", api_key(*GEMINI_KEYS)),
        ("ElevenLabs", api_key(*ELEVEN_KEYS)),
    ]
    print(f"Programma: her {__version__}, codice del {code_date()}")
    print()
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
    if cfg.suggester.enabled:
        manca = "" if api_key(*(GEMINI_KEYS if cfg.suggester.provider == "gemini" else OPENAI_KEYS)) \
            else "  (MANCA LA CHIAVE)"
        print(f"  Regia: {cfg.suggester.provider}/{cfg.suggester.model}, "
              f"max {cfg.suggester.max_words} parole{manca}")
    else:
        print("  Regia: spenta")

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

    resume = args.continua is not None
    if resume:
        out_dir = Path(args.continua) if args.continua else (latest_session(args.sessions) or Path())
        if not (out_dir / "host.wav").exists():
            print("Nessuna puntata da riprendere: registrane una con registra.bat.", file=sys.stderr)
            return 1
    else:
        out_dir = Path(args.out) if args.out else new_session_dir(args.sessions, args.name)

    briefing = prepare_context(args, cfg)
    print(f"{'Riprendo' if resume else 'Sessione'}: {out_dir}")
    if briefing:
        # copia del materiale usato: fra un mese vorrai sapere cosa sapeva
        (out_dir / "contesto-usato.md").write_text(briefing, encoding="utf-8")
    session = PodcastSession(cfg, out_dir, text_input=args.text, resume=resume)
    session.run()
    print(f"\nRegistrato: {session.recorder.duration:.1f}s in {out_dir}")
    if not cfg.session.autorender:
        print("Monta quando vuoi: doppio clic su monta.bat")
        return 0
    try:
        return _render(out_dir, cfg)
    except Exception as exc:
        # le tracce sono già salvate: il montaggio si può sempre rifare
        print(f"\nMontaggio non riuscito: {exc}", file=sys.stderr)
        print("Le registrazioni sono al sicuro in "
              f"{out_dir}: rifai il montaggio con monta.bat", file=sys.stderr)
        return 1


def recorded_at(session_dir: Path) -> float:
    """Quando è stata *registrata* la puntata.

    Non la data della cartella: quella cambia a ogni montaggio, e basta
    rimontare una puntata vecchia perché diventi «l'ultima».
    """
    host = session_dir / "host.wav"
    if host.exists():
        return host.stat().st_mtime
    return session_dir.stat().st_mtime


def list_sessions(root: str = "sessions") -> list[Path]:
    """Le puntate, dalla più recente alla più vecchia."""
    base = Path(root)
    if not base.exists():
        return []
    sessions = [d for d in base.iterdir() if d.is_dir() and (d / "host.wav").exists()]
    return sorted(sessions, key=recorded_at, reverse=True)


def latest_session(root: str = "sessions") -> Path | None:
    sessions = list_sessions(root)
    return sessions[0] if sessions else None


def choose_session(root: str) -> list[Path]:
    """Chiede quale puntata montare, invece di indovinare."""
    from .audio.wavio import wav_duration

    sessions = list_sessions(root)
    if not sessions:
        return []
    print("Puntate registrate (la più recente per prima):\n")
    for i, session in enumerate(sessions[:20], start=1):
        stato = "già montata" if (session / "podcast.wav").exists() else "DA MONTARE"
        print(f"  {i}) {session.name}   {_mmss(wav_duration(session / 'host.wav'))}   {stato}")
    print()
    try:
        risposta = input("Quale monto? [numero, T = tutte, Invio = la più recente] ").strip().lower()
    except EOFError:
        risposta = ""
    if risposta in ("t", "tutte"):
        return sessions
    if risposta.isdigit() and 1 <= int(risposta) <= len(sessions[:20]):
        return [sessions[int(risposta) - 1]]
    return sessions[:1]


def cmd_render(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if args.session:
        targets = [Path(args.session)]
    elif args.tutte:
        targets = list_sessions(args.sessions)
    elif args.scegli:
        targets = choose_session(args.sessions)
    else:
        latest = latest_session(args.sessions)
        targets = [latest] if latest else []

    if not targets:
        print(f"Nessuna puntata trovata in {args.sessions}/. "
              "Indica la cartella: her render sessions\\<nome>", file=sys.stderr)
        return 1

    esito = 0
    for session_dir in targets:
        if not (session_dir / "host.wav").exists():
            print(f"{session_dir} non sembra una puntata (manca host.wav).", file=sys.stderr)
            esito = 1
            continue
        print(f"\n=== {session_dir} ===")
        esito = _render(session_dir, cfg) or esito
    return esito


def _render(session_dir: Path, cfg: Config) -> int:
    result = render_session(session_dir, cfg.render)
    print(f"\nMontato:   {result.wav}  ({_mmss(result.duration)}, tagliati {_mmss(result.saved)} di vuoti)")
    if result.mp3:
        print(f"MP3:       {result.mp3}")
    print(f"Integrale: {result.full}  ({_mmss(result.raw_duration)}, tutto, pause comprese)")
    print(f"Testi:     {result.transcript} · {result.srt}")
    if result.derived_timeline:
        print("\n!! events.jsonl mancante o vuoto: ho ricostruito i turni ascoltando le due")
        print("   tracce. I tagli ci sono, ma senza trascrizione e col saluto iniziale dentro.")
    elif not result.segments:
        print("\n!! Nessun turno e nessun parlato riconoscibile: il «montato» è la")
        print("   registrazione intera, senza tagli. Controlla con: stato.bat")
    _print_levels(result.levels)
    if result.recovered:
        quanti = len(result.recovered)
        durata = sum(r["end"] - r["start"] for r in result.recovered)
        pezzi = "spezzone" if quanti == 1 else "spezzoni"
        print(f"Recuperati: {quanti} {pezzi} della tua voce ({_mmss(durata)}) che la trascrizione"
              "\n            non aveva riconosciuto — sono nel montato, senza testo nei testi.")
    if result.unmatched_host_s > 1.5:
        print(f"Attenzione: {_mmss(result.unmatched_host_s)} della tua traccia restano fuori dal "
              "montato: è parlato\n            sovrapposto alla voce dell'ospite (in cuffia? "
              "aggiungi `recover_over_guest: true`\n            sotto `render:` nel preset). "
              "L'audio è comunque in registrazione-integrale.wav.")
    from datetime import datetime

    scritto = datetime.fromtimestamp(result.wav.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
    coda = "" if result.segments else " (attenzione: senza tagli, vedi sopra)"
    print(f"\nScritto adesso ({scritto}). Da pubblicare è il file «podcast»{coda}.")
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


#: i file che una puntata completa dovrebbe avere, con la loro descrizione
SESSION_FILES = [
    ("host.wav", "la tua voce"),
    ("guest.wav", "la voce dell'ospite"),
    ("registrazione-integrale.wav", "le due voci insieme, pause comprese"),
    ("podcast.wav", "il montato, senza i vuoti"),
    ("podcast.mp3", "il montato in mp3 (serve ffmpeg)"),
    ("transcript.md", "la trascrizione"),
]


def cmd_analyze(args: argparse.Namespace) -> int:
    """Radiografia di una puntata, senza toccare niente: cosa c'è e cosa farebbe il montaggio."""
    from collections import Counter

    from .audio.recorder import read_events
    from .audio.wavio import read_wav, wav_duration
    from .render import plan_timeline, prepare_tracks, recover_host_events, unmatched_host_seconds

    cfg = _load(args)
    session_dir = Path(args.session) if args.session else latest_session(args.sessions)
    if session_dir is None or not (session_dir / "host.wav").exists():
        print("Nessuna puntata da analizzare.", file=sys.stderr)
        return 1

    print(f"her {__version__}, codice del {code_date()}")
    print(f"\nPuntata: {session_dir}")
    print(f"  registrata: {_mmss(wav_duration(session_dir / 'host.wav'))} di traccia")

    host, sr = read_wav(session_dir / "host.wav")
    guest, _ = read_wav(session_dir / "guest.wav")
    events = read_events(session_dir)
    kinds = Counter(f"{e['speaker']}/{e.get('kind', 'turno')}" for e in events)
    print(f"  turni in timeline: {len(events)}" + (f"  ({dict(kinds)})" if events else ""))
    if not events:
        print("  !! events.jsonl è vuoto o assente: senza timeline il montaggio non taglia niente")

    usable = [e for e in events if e["speaker"] in ("host", "guest")]
    if cfg.render.drop_greeting:
        usable = [e for e in usable if e.get("kind") != "greeting"]
    recovered = recover_host_events(host, guest, usable, sr, cfg.render) if cfg.render.recover_host_audio else []
    piano = plan_timeline(sorted(usable + recovered, key=lambda e: e["start"]), cfg.render)

    _, levels = prepare_tracks({"host": host, "guest": guest}, usable, sr, cfg.render)
    if levels.host_lufs is not None and levels.guest_lufs is not None:
        print(f"  volumi percepiti: tu {levels.host_lufs:.1f} LUFS, ospite {levels.guest_lufs:.1f} LUFS")
        print(f"  correzione applicata: {levels.host_gain_db:+.1f} / {levels.guest_gain_db:+.1f} dB "
              f"(target {cfg.render.target_lufs} LUFS)")
        print(f"  compressione: tu {levels.host_compressed}, ospite {levels.guest_compressed}")
        if levels.host_short_db > 0.5:
            print(f"  !! correzione al massimo: la tua voce resta {levels.host_short_db:.0f} dB "
                  "sotto il livello giusto")
            print("     il microfono è troppo basso alla fonte: alzalo in Impostazioni di Windows")
    else:
        print("  volumi: non misurabili")
    print(f"  bilanciamento attivo: {cfg.render.match_loudness} · "
          f"recupero audio: {cfg.render.recover_host_audio} · pausa max: {cfg.render.max_gap_s}s")
    print(f"  spezzoni recuperati: {len(recovered)}")
    print(f"  fuori dal montato: {_mmss(unmatched_host_seconds(host, usable + recovered, sr))}")
    if piano:
        print(f"  montato previsto: {_mmss(max(p['end'] for p in piano) + cfg.render.tail_s)} "
              f"in {len(piano)} pezzi")

    # quando si è fermata? il confronto fra l'ultimo turno e la fine della
    # registrazione dice se a un certo punto ha smesso di ascoltare
    durata = wav_duration(session_dir / "host.wav")
    if events:
        ultimo = max(float(e["end"]) for e in events)
        coda = durata - ultimo
        print(f"  ultimo turno riconosciuto: al minuto {ultimo / 60:.1f} di {durata / 60:.1f}")
        if coda > 60:
            print(f"  !! gli ultimi {coda / 60:.1f} minuti non hanno nessun turno: "
                  "lì ha smesso di ascoltare o di trascrivere")
            print("     il registro della puntata (sessione.log) dice perché, se c'era")

    log = session_dir / "sessione.log"
    if log.exists():
        righe = log.read_text(encoding="utf-8", errors="replace").splitlines()
        errori = [r for r in righe if "[ERRORE]" in r or "[TRACCIA]" in r]
        print(f"  registro: {len(righe)} righe, {len(errori)} errori")
        for riga in errori[-5:]:
            print(f"     {riga[:160]}")
    else:
        print("  registro: assente (puntata registrata prima che esistesse)")

    montato = session_dir / "podcast.wav"
    if montato.exists():
        from datetime import datetime

        quando = datetime.fromtimestamp(montato.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        if montato.stat().st_mtime < recorded_at(session_dir) - 1:
            stato = "VECCHIO: è di prima della registrazione, rimonta"
        elif montato.stat().st_mtime < _code_mtime():
            stato = "montato con una versione precedente del programma: conviene rimontare"
        else:
            stato = "aggiornato"
        print(f"  podcast.wav: {_mmss(wav_duration(montato))}, scritto il {quando} — {stato}")
    else:
        print("  podcast.wav: NON C'È")
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    """Elenca le puntate e dice quali file ha ciascuna: serve a capire dove si è fermato."""
    base = Path(args.sessions)
    if not base.exists():
        print(f"Nessuna puntata: la cartella {base}/ non esiste ancora.")
        return 0
    sessions = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name)
    if not sessions:
        print(f"Nessuna puntata in {base}/.")
        return 0

    from datetime import datetime

    from .audio.wavio import wav_duration

    incomplete = []
    for session in sorted(sessions, key=recorded_at):
        quando = datetime.fromtimestamp(recorded_at(session)).strftime("%d/%m/%Y %H:%M")
        durata = _mmss(wav_duration(session / "host.wav"))
        print(f"\n{session}   registrata il {quando}, {durata}")
        for name, what in SESSION_FILES:
            path = session / name
            if path.exists():
                size = path.stat().st_size
                print(f"  OK  {name:<28} {_size(size)}  {what}")
            elif name == "podcast.mp3":
                print(f"  --  {name:<28} assente        {what}")
            else:
                print(f"  --  {name:<28} MANCA          {what}")
                if name != "podcast.mp3":
                    incomplete.append(session)
        montato = session / "podcast.wav"
        if montato.exists() and montato.stat().st_mtime < recorded_at(session) - 1:
            print("  !!  il montaggio è più VECCHIO della registrazione: rimontala (monta.bat)")
            incomplete.append(session)

    if incomplete:
        print("\nA qualche puntata manca il montaggio: doppio clic su monta.bat "
              "(rimonta l'ultima) oppure:")
        print(f"  .venv\\Scripts\\her.exe render {sorted(set(incomplete))[-1]}")
    else:
        print("\nTutte le puntate sono complete.")
    return 0


def _size(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def _print_levels(levels) -> None:
    """Dice com'erano le due voci e cosa è stato fatto per pareggiarle."""
    if levels.host_lufs is None or levels.guest_lufs is None:
        return
    compressa = " (la tua voce è stata anche compressa)" if levels.host_compressed else ""
    print(f"Volumi:    tu {levels.host_lufs:.1f} LUFS, l'ospite {levels.guest_lufs:.1f} LUFS "
          f"→ corretti di {levels.host_gain_db:+.1f} e {levels.guest_gain_db:+.1f} dB{compressa}")
    _warn_low_mic(levels)


def _warn_low_mic(levels) -> None:
    """Un microfono troppo basso non si aggiusta in post: si aggiusta prima."""
    if levels.host_short_db > 0.5:
        print(f"           !! la tua voce resta {levels.host_short_db:.0f} dB sotto il livello "
              "giusto: la correzione\n              ha già toccato il massimo consentito.")
    elif levels.host_gain_db <= 14:
        return
    print("           Alza il microfono in Impostazioni di Windows → Sistema → Audio →")
    print("           Microfono → Volume (e avvicinatelo): tirando su di tanto in post")
    print("           si tira su anche il fruscio della stanza.")


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
    parser.add_argument("--version", action="version",
                        version=f"her {__version__} (codice del {code_date()})")
    parser.add_argument("--env", default=".env", help="file con le chiavi API (default: .env)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, full: bool = True) -> None:
        p.add_argument("-p", "--preset", help="preset YAML (nome in presets/ o percorso)")
        p.add_argument("--context", metavar="FILE",
                       help="appunti della puntata (default: contesto.md, se c'è)")
        p.add_argument("--no-link", action="store_true",
                       help="non scaricare i link trovati negli appunti")
        p.add_argument("--ricarica", action="store_true",
                       help="riscarica i link anche se sono già in cache")
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
    p_rec.add_argument("--continua", nargs="?", const="", metavar="PUNTATA",
                       help="riprende una puntata già registrata (default: l'ultima)")
    p_rec.add_argument("--text", action="store_true", help="scrivi invece di parlare (per provare)")
    p_rec.add_argument("--pausa", type=float, metavar="SECONDI",
                       help="silenzio da aspettare prima che l'ospite risponda (default: 1.2)")
    p_rec.add_argument("--no-regia", action="store_true",
                       help="niente suggerimenti scritti durante la registrazione")
    p_rec.add_argument("--barge-in", action="store_true", help="puoi interrompere l'ospite (usa le cuffie)")
    p_rec.add_argument("--no-render", action="store_true", help="non montare a fine registrazione")
    p_rec.add_argument("--max-gap", type=float, help="pausa massima nel montaggio (s)")
    p_rec.add_argument("--no-mp3", action="store_true")
    p_rec.set_defaults(func=cmd_record)

    p_ren = sub.add_parser("render", help="monta una sessione già registrata")
    common(p_ren, full=False)
    p_ren.add_argument("session", nargs="?", help="cartella della puntata (default: l'ultima registrata)")
    p_ren.add_argument("--scegli", action="store_true", help="chiede quale puntata montare")
    p_ren.add_argument("--tutte", action="store_true", help="rimonta tutte le puntate")
    p_ren.add_argument("--sessions", default="sessions", help="cartella radice delle puntate")
    p_ren.add_argument("--max-gap", type=float, help="pausa massima fra i turni (s)")
    p_ren.add_argument("--no-mp3", action="store_true")
    p_ren.set_defaults(func=cmd_render)

    p_mod = sub.add_parser("models", help="elenca i modelli disponibili con la tua chiave")
    common(p_mod)
    p_mod.add_argument("--provider", choices=["openai", "gemini"], help="default: quello del preset")
    p_mod.add_argument("--search", help="filtra per nome")
    p_mod.set_defaults(func=cmd_models)

    p_ctx = sub.add_parser("contesto", help="prepara e mostra il materiale della puntata")
    common(p_ctx)
    p_ctx.set_defaults(func=cmd_context)

    p_ana = sub.add_parser("analizza", help="radiografia di una puntata, senza modificarla")
    common(p_ana, full=False)
    p_ana.add_argument("session", nargs="?", help="cartella della puntata (default: l'ultima)")
    p_ana.add_argument("--sessions", default="sessions", help="cartella radice delle puntate")
    p_ana.set_defaults(func=cmd_analyze)

    p_ses = sub.add_parser("sessioni", help="elenca le puntate e i file di ciascuna")
    p_ses.add_argument("--sessions", default="sessions", help="cartella radice delle puntate")
    p_ses.set_defaults(func=cmd_sessions)

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
    except PermissionError as exc:
        print(f"Errore: non riesco a scrivere {getattr(exc, 'filename', '')}: "
              "il file è aperto in un altro programma? Chiudi il lettore audio e riprova.",
              file=sys.stderr)
        return 1
    except (AudioUnavailable, SttError, LlmError, TtsError, ModelsError,
            FileNotFoundError, ValueError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
