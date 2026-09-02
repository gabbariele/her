"""Cosa fare quando il provider dice «sono sovraccarico».

Le API di Gemini e OpenAI rispondono 429 (troppe richieste) o 503 (modello
sovraccarico) anche quando la chiave è a posto e la richiesta è corretta: sono
errori temporanei, e l'unica risposta sensata è aspettare un attimo e riprovare.

Le due regole che contano: aspettare un tempo che cresce (e con un po' di
casualità, o tutti i client del mondo ritentano nello stesso istante) e avere un
budget massimo. In una registrazione dal vivo non si può ritentare per un minuto:
meglio perdere un turno che restare piantati con il microfono aperto.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

#: errori che ha senso ritentare: sono temporanei, non colpa della richiesta
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def sleep(seconds: float) -> None:      # separato per poterlo sostituire nei test
    time.sleep(seconds)


def parse_retry_after(headers) -> float | None:
    """I secondi indicati dal provider, se li indica."""
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None                      # forma a data: non vale la pena
    return value if value >= 0 else None


@dataclass
class Backoff:
    """Tiene il conto dei tentativi e decide quando smettere."""

    #: quanto tempo in tutto si può spendere a ritentare
    budget_s: float = 6.0
    base_s: float = 0.5
    cap_s: float = 4.0
    attempts: int = 0
    started: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def wait_for(self, status_code: int, headers=None) -> float | None:
        """Secondi da aspettare prima di riprovare, o None per arrendersi."""
        if status_code not in RETRYABLE:
            return None
        self.attempts += 1
        crescita = min(self.cap_s, self.base_s * (2 ** (self.attempts - 1)))
        attesa = crescita * random.uniform(0.7, 1.3)

        indicata = parse_retry_after(headers)
        if indicata is not None:
            # il provider sa meglio di noi quando riprovare
            attesa = max(attesa, indicata)

        rimasto = self.budget_s - self.elapsed
        if attesa > rimasto:
            return None
        return attesa

    def message(self, status_code: int, servizio: str) -> str:
        motivo = "troppe richieste" if status_code == 429 else "sovraccarico"
        return (
            f"{servizio} {motivo} ({status_code}): non si è ripreso in "
            f"{self.budget_s:.0f}s, turno saltato"
        )

    def notice(self, status_code: int, servizio: str, attesa: float) -> str:
        motivo = "troppe richieste" if status_code == 429 else "sovraccarico"
        return f"{servizio} {motivo} ({status_code}): riprovo fra {attesa:.1f}s"


def handle(status_code: int, headers, backoff: Backoff, servizio: str, notice=None) -> bool:
    """Aspetta se vale la pena riprovare. True = riprova, False = arrenditi."""
    attesa = backoff.wait_for(status_code, headers)
    if attesa is None:
        return False
    if notice is not None:
        notice(backoff.notice(status_code, servizio, attesa))
    sleep(attesa)
    return True
