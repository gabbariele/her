"""LLM in streaming: la risposta arriva token per token (OpenAI o Gemini)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

import httpx

from ..config import GEMINI_KEYS, OPENAI_KEYS, LlmConfig, api_key
from . import _gemini, backoff as bo

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

#: quante volte al massimo si riprova cambiando modello o togliendo il thinking
_MAX_ATTEMPTS = 5
#: e quanti giri in più concedere ai tentativi per sovraccarico
_OVERLOAD_ATTEMPTS = 8


class LlmError(RuntimeError):
    pass


def _notify(notice: Callable[[str], None] | None, message: str) -> None:
    if notice is not None:
        notice(message)


@dataclass
class Attempt:
    """Un tentativo della catena: chi chiamare, con che modello e con che fretta."""

    provider: str
    model: str
    timeout: float
    retry_budget_s: float
    label: str


def chain(cfg: LlmConfig, timeout: float) -> list[Attempt]:
    """Il primario e, se configurato e utilizzabile, il ripiego.

    Al primario si dà un guinzaglio corto: se c'è un'alternativa pronta, non ha
    senso aspettare venti secondi un provider che arranca.
    """
    passi = [
        Attempt(cfg.provider, cfg.model, cfg.fallback_after_s,
                min(cfg.retry_budget_s, cfg.fallback_after_s), "primario")
    ]
    if cfg.fallback_provider and cfg.fallback_model:
        keys = OPENAI_KEYS if cfg.fallback_provider == "openai" else GEMINI_KEYS
        if api_key(*keys) and (cfg.fallback_provider, cfg.fallback_model) != (cfg.provider, cfg.model):
            passi.append(Attempt(cfg.fallback_provider, cfg.fallback_model, timeout,
                                 cfg.retry_budget_s, "ripiego"))
    return passi


def stream_reply(
    system_prompt: str,
    history: list[dict],
    cfg: LlmConfig,
    timeout: float = 120.0,
    client: httpx.Client | None = None,
    notice: Callable[[str], None] | None = None,
) -> Iterator[str]:
    """Genera la risposta dell'ospite. `history` = [{'role': 'user'|'assistant', 'content': str}]."""
    passi = chain(cfg, timeout)
    for indice, passo in enumerate(passi):
        emesso = False
        try:
            for token in _call(passo, system_prompt, history, cfg, client, notice):
                emesso = True
                yield token
            return
        except Exception as exc:
            ultimo = indice + 1 >= len(passi)
            # a risposta iniziata non si cambia cavallo: uscirebbe il doppio testo
            if emesso or ultimo:
                raise
            prossimo = passi[indice + 1]
            _notify(notice, f"{passo.model} non risponde ({_motivo(exc)}): "
                            f"passo a {prossimo.model}")


def _motivo(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "troppo lento"
    if isinstance(exc, httpx.TransportError):
        return "rete"
    return str(exc)[:120]


def _call(passo: Attempt, system_prompt, history, cfg, client, notice) -> Iterator[str]:
    if passo.provider == "openai":
        return _openai(system_prompt, history, cfg, passo, client, notice)
    if passo.provider == "gemini":
        return _gemini_stream(system_prompt, history, cfg, passo, client, notice)
    raise LlmError(f"provider LLM sconosciuto: {passo.provider}")


@contextmanager
def _client(client: httpx.Client | None, timeout: float):
    if client is not None:
        yield client
        return
    own = httpx.Client(timeout=timeout)
    try:
        yield own
    finally:
        own.close()


def _openai(system_prompt, history, cfg: LlmConfig, passo, client, notice=None) -> Iterator[str]:
    key = api_key(*OPENAI_KEYS)
    if not key:
        raise LlmError("manca OPENAI_API_KEY")
    payload = {
        "model": passo.model,
        "messages": [{"role": "system", "content": system_prompt}, *history],
        "stream": True,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_output_tokens,
    }
    attesa = bo.Backoff(budget_s=passo.retry_budget_s)
    with _client(client, passo.timeout) as http:
        while True:
            with http.stream(
                "POST",
                OPENAI_URL,
                headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                json=payload,
                timeout=passo.timeout,
            ) as resp:
                if resp.status_code >= 400:
                    # sovraccarico: si aspetta e si riprova, ma solo finché non
                    # è uscito niente, o il testo verrebbe fuori doppio
                    if bo.handle(resp.status_code, resp.headers, attesa, "OpenAI", notice):
                        continue
                    if resp.status_code in bo.RETRYABLE:
                        raise LlmError(attesa.message(resp.status_code, "OpenAI"))
                    raise LlmError(f"OpenAI LLM {resp.status_code}: {_body(resp)[:300]}")
                for data in _sse(resp):
                    chunk = _json(data)
                    for choice in chunk.get("choices", []) if chunk else []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            yield piece
                return


def _gemini_payload(system_prompt: str, history: list[dict], cfg: LlmConfig, model: str = "") -> dict:
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in history
    ]
    generation: dict = {
        "temperature": cfg.temperature,
        "maxOutputTokens": cfg.max_output_tokens,
    }
    thinking = _gemini.thinking_config(cfg.thinking, model or cfg.model)
    if thinking is not None:
        generation["thinkingConfig"] = thinking
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": generation,
    }


def _gemini_stream(system_prompt, history, cfg: LlmConfig, passo, client, notice) -> Iterator[str]:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise LlmError("manca GEMINI_API_KEY")
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    payload = _gemini_payload(system_prompt, history, cfg)
    model = cfg.model
    tried = {_gemini.normalize_model(model)}

    attesa = bo.Backoff(budget_s=passo.retry_budget_s)
    with _client(client, passo.timeout) as http:
        for _ in range(_MAX_ATTEMPTS + _OVERLOAD_ATTEMPTS):
            emitted = False
            finish = blocked = ""
            url = _gemini.endpoint(model, "streamGenerateContent", sse=True)
            with http.stream("POST", url, headers=headers, json=payload,
                             timeout=passo.timeout) as resp:
                if resp.status_code >= 400:
                    # sovraccarico del modello: aspetta e ritenta, finché il
                    # budget lo consente. Qui non è ancora uscito nessun token,
                    # quindi ripetere la richiesta non duplica niente
                    if bo.handle(resp.status_code, resp.headers, attesa, "Gemini", notice):
                        continue
                    if resp.status_code in bo.RETRYABLE:
                        raise LlmError(attesa.message(resp.status_code, "Gemini"))
                    detail = _body(resp)
                    # modello ritirato o parametro non gradito: si riprova
                    # aggiustando la richiesta, invece di far cadere la risposta
                    retry = _gemini.plan_retry(resp.status_code, detail, payload, model, tried, "llm")
                    if retry is None:
                        raise LlmError(f"Gemini LLM {resp.status_code}: {detail[:300]}")
                    _notify(notice, retry.notice)
                    payload, model = retry.payload, retry.model
                    tried.add(_gemini.normalize_model(model))
                    continue

                for data in _sse(resp):
                    chunk = _json(data)
                    if not chunk:
                        continue
                    finish = _gemini.finish_reason(chunk) or finish
                    blocked = _gemini.blocked_reason(chunk) or blocked
                    piece = _gemini.response_text(chunk)
                    if piece:
                        emitted = True
                        yield piece
            if not emitted:
                raise LlmError(_gemini.empty_answer_hint(finish, blocked, model))
            return
    raise LlmError("Gemini LLM: troppi tentativi falliti di seguito")


def _sse(resp: httpx.Response) -> Iterator[str]:
    for line in resp.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        yield data


def _json(data: str) -> dict | None:
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _body(resp: httpx.Response) -> str:
    try:
        return resp.read().decode("utf-8", "replace")
    except Exception:
        return "(nessun dettaglio)"


def trim_history(history: list[dict], turns: int) -> list[dict]:
    """Tiene solo gli ultimi `turns` scambi (1 scambio = domanda + risposta)."""
    if turns <= 0:
        return list(history)
    return history[-turns * 2 :]
