"""LLM in streaming: la risposta arriva token per token (OpenAI o Gemini)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

import httpx

from ..config import GEMINI_KEYS, OPENAI_KEYS, LlmConfig, api_key
from . import _gemini

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class LlmError(RuntimeError):
    pass


def stream_reply(
    system_prompt: str,
    history: list[dict],
    cfg: LlmConfig,
    timeout: float = 120.0,
    client: httpx.Client | None = None,
) -> Iterator[str]:
    """Genera la risposta dell'ospite. `history` = [{'role': 'user'|'assistant', 'content': str}]."""
    if cfg.provider == "openai":
        yield from _openai(system_prompt, history, cfg, timeout, client)
    elif cfg.provider == "gemini":
        yield from _gemini_stream(system_prompt, history, cfg, timeout, client)
    else:
        raise LlmError(f"provider LLM sconosciuto: {cfg.provider}")


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


def _openai(system_prompt, history, cfg: LlmConfig, timeout, client) -> Iterator[str]:
    key = api_key(*OPENAI_KEYS)
    if not key:
        raise LlmError("manca OPENAI_API_KEY")
    payload = {
        "model": cfg.model,
        "messages": [{"role": "system", "content": system_prompt}, *history],
        "stream": True,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_output_tokens,
    }
    with _client(client, timeout) as http:
        with http.stream(
            "POST",
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json=payload,
            timeout=timeout,
        ) as resp:
            if resp.status_code >= 400:
                raise LlmError(f"OpenAI LLM {resp.status_code}: {_body(resp)[:300]}")
            for data in _sse(resp):
                chunk = _json(data)
                for choice in chunk.get("choices", []) if chunk else []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        yield piece


def _gemini_payload(system_prompt: str, history: list[dict], cfg: LlmConfig) -> dict:
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in history
    ]
    generation: dict = {
        "temperature": cfg.temperature,
        "maxOutputTokens": cfg.max_output_tokens,
    }
    thinking = _gemini.thinking_config(cfg.thinking)
    if thinking is not None:
        generation["thinkingConfig"] = thinking
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": generation,
    }


def _gemini_stream(system_prompt, history, cfg: LlmConfig, timeout, client) -> Iterator[str]:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise LlmError("manca GEMINI_API_KEY")
    url = _gemini.endpoint(cfg.model, "streamGenerateContent", sse=True)
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    payload = _gemini_payload(system_prompt, history, cfg)

    with _client(client, timeout) as http:
        for attempt, body in enumerate((payload, _gemini.strip_thinking(payload))):
            emitted = False
            finish = blocked = ""
            with http.stream("POST", url, headers=headers, json=body, timeout=timeout) as resp:
                if resp.status_code >= 400:
                    text = _body(resp)
                    # certe famiglie di modelli non accettano il campo thinking:
                    # in quel caso si riprova una volta sola, senza
                    if attempt == 0 and _gemini.is_thinking_error(resp.status_code, text):
                        continue
                    raise LlmError(f"Gemini LLM {resp.status_code}: {text[:300]}")
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
                raise LlmError(_gemini.empty_answer_hint(finish, blocked, cfg.model))
            return


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
