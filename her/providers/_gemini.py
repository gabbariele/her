"""Pezzi comuni alle chiamate Gemini (trascrizione e risposte).

L'endpoint è quello classico `models/{modello}:generateContent`, che è ancora
quello documentato e supportato. Qui stanno le tre cose che cambiano fra una
famiglia di modelli e l'altra: il nome del modello, il "ragionamento" (thinking)
e il fatto che le risposte possono contenere parti di pensiero da NON leggere
ad alta voce.
"""
from __future__ import annotations

from typing import Any

BASE = "https://generativelanguage.googleapis.com/v1beta"

_OFF = {"off", "no", "false", "0", "disabled", "spento"}
_AUTO = {"", "auto", "default", "automatico"}
_LEVELS = {"low", "medium", "high", "minimal"}


def normalize_model(model: str) -> str:
    """`models/gemini-2.5-flash` e `gemini-2.5-flash` sono la stessa cosa."""
    model = (model or "").strip()
    return model[len("models/"):] if model.startswith("models/") else model


def endpoint(model: str, method: str, sse: bool = False) -> str:
    url = f"{BASE}/models/{normalize_model(model)}:{method}"
    return f"{url}?alt=sse" if sse else url


def thinking_config(setting: Any) -> dict | None:
    """Traduce l'impostazione `thinking` nel campo giusto per l'API.

    "off" azzera il ragionamento (più veloce e più economico: per una battuta di
    podcast non serve), "low"/"medium"/"high" lo dosano, un numero è il budget
    di token, "auto" lascia decidere al modello. Le famiglie di modelli non
    accettano tutte gli stessi campi: se l'API lo rifiuta, la chiamata viene
    ripetuta senza (vedi `is_thinking_error`).
    """
    text = str(setting if setting is not None else "").strip().lower()
    if text in _AUTO:
        return None
    if text in _OFF:
        return {"thinkingBudget": 0}
    if text in _LEVELS:
        return {"thinkingLevel": text}
    try:
        return {"thinkingBudget": int(text)}
    except ValueError:
        raise ValueError(
            f"valore di `thinking` non valido: {setting!r} "
            "(usa off, low, medium, high, auto oppure un numero di token)"
        ) from None


def is_thinking_error(status_code: int, body: str) -> bool:
    """L'errore dipende dal campo `thinking*`? Allora vale la pena riprovare senza."""
    if status_code not in (400, 404):
        return False
    return "thinking" in body.lower()


def strip_thinking(payload: dict) -> dict:
    clean = dict(payload)
    config = dict(clean.get("generationConfig") or {})
    config.pop("thinkingConfig", None)
    clean["generationConfig"] = config
    return clean


def part_text(part: dict) -> str:
    """Testo di una parte, saltando il pensiero del modello.

    Le parti con `thought: true` sono il ragionamento interno: farle leggere
    all'ospite sarebbe surreale.
    """
    if part.get("thought"):
        return ""
    return part.get("text") or ""


def response_text(data: dict) -> str:
    out = []
    for candidate in data.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            out.append(part_text(part))
    return "".join(out)


def finish_reason(data: dict) -> str:
    for candidate in data.get("candidates") or []:
        if candidate.get("finishReason"):
            return str(candidate["finishReason"])
    return ""


def blocked_reason(data: dict) -> str:
    feedback = data.get("promptFeedback") or {}
    return str(feedback.get("blockReason") or "")


def empty_answer_hint(finish: str, blocked: str, model: str) -> str:
    """Messaggio utile quando il modello risponde… niente."""
    if blocked:
        return f"Gemini ha bloccato la richiesta ({blocked}): riformula o cambia contesto."
    if finish.upper() == "MAX_TOKENS":
        return (
            f"{model} ha esaurito i token prima di dire qualcosa. Alza "
            "`llm.max_output_tokens` nel preset, oppure metti `llm.thinking: off` "
            "per non farglieli sprecare in ragionamento."
        )
    return (
        f"{model} ha restituito una risposta vuota"
        + (f" (motivo: {finish})" if finish else "")
        + ". Prova un altro modello con `her models`."
    )
