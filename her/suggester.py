"""La regia: una seconda testa, indipendente, che ti suggerisce come proseguire.

Non è l'ospite e non parla mai ad alta voce. Ha davanti la scaletta della
puntata e la conversazione man mano che si svolge, e ogni volta che tocca a
Nova rispondere manda al conduttore una riga da leggere in due secondi.

Gira su una connessione sua, in un thread suo: se è lenta o cade, la
registrazione non se ne accorge. E se non ha niente di utile da dire, tace —
un suggeritore che parla sempre diventa rumore.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from .config import GEMINI_KEYS, OPENAI_KEYS, LlmConfig, SuggesterConfig, api_key
from .providers.llm import stream_reply

SYSTEM_PROMPT = """\
Sei la regia di un podcast: stai in cuffia con il conduttore mentre registra.
Hai davanti la scaletta della puntata e la conversazione in corso. L'ospite è
un'AI di nome {ospite}; il conduttore è la persona vera.

Il tuo lavoro è dare al conduttore UNA spinta da leggere in due secondi, mentre
l'ospite sta rispondendo.

COME
- Una riga sola, massimo {parole} parole. Niente preamboli, niente virgolette,
  niente «suggerimento:». Solo la frase.
- Dagli qualcosa da DIRE: l'affondo, la battuta, la domanda precisa. Mai
  consigli generici come «approfondisci» o «chiedi un esempio».
- Tono ironico e caldo, da complice che gli passa la palla, non da professore.

QUANDO
- Se la conversazione è uscita dalla scaletta ma sta funzionando, NON riportarlo
  indietro: assecondala e digli come cavalcarla.
- Se si è impantanata, o gira a vuoto, o l'ospite è stato generico, dagli la via
  d'uscita.
- Se sta andando bene e non hai niente che aggiunga davvero qualcosa, rispondi
  esattamente: NIENTE

Non ripetere consigli già dati. Non commentare la qualità della puntata.
"""


@dataclass
class Suggestion:
    turn: int
    text: str


class Suggester:
    """Chiede un suggerimento senza mai far aspettare la conversazione."""

    def __init__(
        self,
        cfg: SuggesterConfig,
        briefing: str,
        persona_name: str,
        out_path: Path | None = None,
        on_suggestion: Callable[[Suggestion], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self.cfg = cfg
        self.briefing = briefing.strip()
        self.persona_name = persona_name or "l'ospite"
        self.out_path = out_path
        self.on_suggestion = on_suggestion
        self.on_error = on_error
        self.suggestions: list[Suggestion] = []
        self.disabled_reason = ""
        self._busy = threading.Lock()
        self._turn = 0
        # connessione tutta sua: non condivide niente con l'ospite
        self._client = httpx.Client(timeout=cfg.timeout)

    # -- disponibilità -----------------------------------------------------
    @property
    def available(self) -> bool:
        return self.cfg.enabled and not self.disabled_reason

    def check(self) -> str:
        """Motivo per cui la regia non può lavorare, o stringa vuota."""
        if not self.cfg.enabled:
            return "spenta"
        keys = GEMINI_KEYS if self.cfg.provider == "gemini" else OPENAI_KEYS
        if not api_key(*keys):
            return f"manca la chiave {self.cfg.provider}"
        return ""

    # -- lavoro ------------------------------------------------------------
    def consider(self, history: list[dict]) -> None:
        """Valuta il momento e, se ha qualcosa da dire, lo dirà fra un istante."""
        if not self.available or self._busy.locked():
            return
        self._turn += 1
        snapshot = list(history[-self.cfg.history_turns * 2:])
        threading.Thread(
            target=self._work, args=(snapshot, self._turn), name="regia", daemon=True
        ).start()

    def _work(self, history: list[dict], turn: int) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            text = self._ask(history)
            if not text:
                return
            suggestion = Suggestion(turn, text)
            self.suggestions.append(suggestion)
            self._save(suggestion)
            if self.on_suggestion:
                self.on_suggestion(suggestion)
        except Exception as exc:
            if self.on_error:
                self.on_error(f"regia non disponibile: {type(exc).__name__}: {exc}")
        finally:
            self._busy.release()

    def _ask(self, history: list[dict]) -> str:
        system = SYSTEM_PROMPT.format(ospite=self.persona_name, parole=self.cfg.max_words)
        if self.briefing:
            system += "\n\nSCALETTA E MATERIALE DELLA PUNTATA\n" + self.briefing
        if self.suggestions:
            recenti = " | ".join(s.text for s in self.suggestions[-4:])
            system += f"\n\nSuggerimenti che gli hai già dato (non ripeterli): {recenti}"

        conversazione = "\n".join(
            f"{'CONDUTTORE' if m['role'] == 'user' else self.persona_name.upper()}: {m['content']}"
            for m in history
        )
        cfg = LlmConfig(
            provider=self.cfg.provider,
            model=self.cfg.model,
            temperature=self.cfg.temperature,
            max_output_tokens=self.cfg.max_output_tokens,
            thinking=self.cfg.thinking,
        )
        pieces = stream_reply(
            system,
            [{"role": "user", "content": conversazione + "\n\nLa tua riga:"}],
            cfg,
            timeout=self.cfg.timeout,
            client=self._client,
        )
        return clean_suggestion("".join(pieces), self.cfg.max_words)

    def _save(self, suggestion: Suggestion) -> None:
        if not self.out_path:
            return
        try:
            with open(self.out_path, "a", encoding="utf-8") as handle:
                handle.write(f"- [turno {suggestion.turn}] {suggestion.text}\n")
        except OSError:
            pass

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


def clean_suggestion(text: str, max_words: int) -> str:
    """Una riga, senza fronzoli. Stringa vuota se la regia ha scelto di tacere."""
    text = (text or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    for prefisso in ("suggerimento:", "regia:", "-", "•", ">"):
        if text.lower().startswith(prefisso):
            text = text[len(prefisso):].strip()
    text = text.strip('"').strip("«»").strip("'").strip()
    if not text or text.upper().startswith("NIENTE"):
        return ""
    parole = text.split()
    if len(parole) > max_words + 6:            # un filo di tolleranza, poi si taglia
        text = " ".join(parole[: max_words + 6]).rstrip(",;:") + "…"
    return text
