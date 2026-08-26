"""Pezzi comuni alle chiamate Gemini (trascrizione e risposte).

L'endpoint è quello classico `models/{modello}:generateContent`, che è ancora
quello documentato e supportato. Qui stanno le tre cose che cambiano fra una
famiglia di modelli e l'altra: il nome del modello, il "ragionamento" (thinking)
e il fatto che le risposte possono contenere parti di pensiero da NON leggere
ad alta voce.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

BASE = "https://generativelanguage.googleapis.com/v1beta"

_OFF = {"off", "no", "false", "0", "disabled", "spento"}
_AUTO = {"", "auto", "default", "automatico"}
_LEVELS = {"minimal", "low", "medium", "high"}


def normalize_model(model: str) -> str:
    """`models/gemini-2.5-flash` e `gemini-2.5-flash` sono la stessa cosa."""
    model = (model or "").strip()
    return model[len("models/"):] if model.startswith("models/") else model


def endpoint(model: str, method: str, sse: bool = False) -> str:
    url = f"{BASE}/models/{normalize_model(model)}:{method}"
    return f"{url}?alt=sse" if sse else url


#: i modelli Gemini 3 e successivi si regolano a "livelli"; i 2.5 a budget di token
_LEVEL_FAMILY = re.compile(r"^gemini-([3-9]|\d{2,})", re.I)
#: equivalenza approssimativa livello -> budget, per i modelli che vogliono i token
_LEVEL_BUDGET = {"minimal": 0, "low": 1024, "medium": 4096, "high": 16384}


def uses_thinking_level(model: str) -> bool:
    return bool(_LEVEL_FAMILY.match(normalize_model(model)))


def thinking_config(setting: Any, model: str = "") -> dict | None:
    """Traduce l'impostazione `thinking` nel campo giusto per quel modello.

    Le due generazioni non parlano la stessa lingua: Gemini 3 e successivi
    vogliono `thinkingLevel` (minimal/low/medium/high), i 2.5 un `thinkingBudget`
    in token. Mandare il campo sbagliato fa fallire la richiesta con un generico
    400 INVALID_ARGUMENT, quindi qui si sceglie in base al nome del modello.

    "off" vuol dire «il minimo possibile»: sui 2.5 è davvero zero, sui 3 è il
    livello minimo, perché quei modelli non sanno smettere di pensare del tutto.
    """
    text = str(setting if setting is not None else "").strip().lower()
    if text in _AUTO:
        return None
    by_level = uses_thinking_level(model)
    if text in _OFF:
        return {"thinkingLevel": "minimal"} if by_level else {"thinkingBudget": 0}
    if text in _LEVELS:
        return {"thinkingLevel": text} if by_level else {"thinkingBudget": _LEVEL_BUDGET[text]}
    try:
        budget = int(text)
    except ValueError:
        raise ValueError(
            f"valore di `thinking` non valido: {setting!r} "
            "(usa off, minimal, low, medium, high, auto oppure un numero di token)"
        ) from None
    if not by_level:
        return {"thinkingBudget": budget}
    # un budget su un modello a livelli: lo traduciamo nel livello più vicino
    level = min(_LEVEL_BUDGET, key=lambda name: abs(_LEVEL_BUDGET[name] - budget))
    return {"thinkingLevel": level}


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


_SUGGESTED = re.compile(r"use\s+(?:the\s+)?models/([\w.\-]+)", re.I)
_ANY_MODEL = re.compile(r"models/([\w.\-]+)")


def suggested_model(body: str, current: str) -> str | None:
    """Il modello indicato da Google quando quello richiesto è stato ritirato.

    L'errore dice testualmente «... is no longer available ... please update your
    code to use models/<altro>»: invece di far fallire la puntata, quel nome lo
    leggiamo e riproviamo con quello.
    """
    if "no longer available" not in body.lower() and "not found" not in body.lower():
        return None
    match = _SUGGESTED.search(body)
    if match and normalize_model(match.group(1)) != normalize_model(current):
        return normalize_model(match.group(1))
    for name in reversed(_ANY_MODEL.findall(body)):
        if normalize_model(name) != normalize_model(current):
            return normalize_model(name)
    return None


def retired_notice(old: str, new: str, section: str = "") -> str:
    dove = f" sotto `{section}:`" if section else ""
    return (
        f"{old} non è più disponibile: uso {new}. "
        f"Aggiorna la riga `model:`{dove} nel preset per non rivedere questo avviso."
    )


@dataclass
class Retry:
    """Il prossimo tentativo da fare dopo una richiesta rifiutata."""

    payload: dict
    model: str
    notice: str


def plan_retry(
    status_code: int, body: str, payload: dict, model: str, tried: set[str], section: str = ""
) -> Retry | None:
    """Cosa provare dopo un errore, o None per arrendersi.

    Due casi si recuperano da soli: un modello ritirato (Google dice nell'errore
    quale usare) e un parametro facoltativo non gradito (il 400 è generico, non
    dice quale: si toglie il più probabile e si riprova).
    """
    if status_code == 404 or "no longer available" in body.lower():
        replacement = suggested_model(body, model)
        if replacement and replacement not in tried:
            return Retry(payload, replacement, retired_notice(model, replacement, section))
        return None
    if status_code != 400:
        return None

    generation = dict(payload.get("generationConfig") or {})
    thinking = generation.get("thinkingConfig") or {}
    if thinking.get("thinkingLevel") == "minimal":
        # `minimal` non esiste su tutti i modelli a livelli: `low` sì
        relaxed = dict(payload)
        relaxed["generationConfig"] = {**generation, "thinkingConfig": {"thinkingLevel": "low"}}
        return Retry(relaxed, model, "il livello di thinking «minimal» non è accettato: riprovo con «low»")
    if thinking:
        return Retry(
            strip_thinking(payload),
            model,
            "il parametro `thinking` non è accettato da questo modello: riprovo senza",
        )
    if generation:
        relaxed = {k: v for k, v in payload.items() if k != "generationConfig"}
        return Retry(relaxed, model, "parametri di generazione rifiutati: riprovo con quelli predefiniti")
    return None


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
