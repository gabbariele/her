"""her - podcast conversazionali con un ospite AI in tempo reale."""

from datetime import datetime
from pathlib import Path

__version__ = "0.2.0"


def code_date() -> str:
    """Quando è stato scritto il codice che sta girando davvero.

    Serve a rispondere alla domanda «l'aggiornamento è arrivato?» senza
    doverci credere sulla parola.
    """
    here = Path(__file__).resolve().parent
    newest = max((f.stat().st_mtime for f in here.rglob("*.py")), default=0.0)
    return datetime.fromtimestamp(newest).strftime("%d/%m/%Y %H:%M") if newest else "?"
