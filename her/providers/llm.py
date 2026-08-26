"""LLM in streaming: la risposta arriva token per token (OpenAI o Gemini)."""
from __future__ import annotations

import json
from typing import Iterator

import httpx

from ..config import GEMINI_KEYS, OPENAI_KEYS, LlmConfig, api_key

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
)


class LlmError(RuntimeError):
    pass


def stream_reply(
    system_prompt: str,
    history: list[dict],
    cfg: LlmConfig,
    timeout: float = 120.0,
) -> Iterator[str]:
    """Genera la risposta dell'ospite. `history` = [{'role': 'user'|'assistant', 'content': str}]."""
    if cfg.provider == "openai":
        yield from _openai(system_prompt, history, cfg, timeout)
    elif cfg.provider == "gemini":
        yield from _gemini(system_prompt, history, cfg, timeout)
    else:
        raise LlmError(f"provider LLM sconosciuto: {cfg.provider}")


def _openai(system_prompt: str, history: list[dict], cfg: LlmConfig, timeout: float) -> Iterator[str]:
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
    with httpx.stream(
        "POST",
        OPENAI_URL,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json=payload,
        timeout=timeout,
    ) as resp:
        if resp.status_code >= 400:
            raise LlmError(f"OpenAI LLM {resp.status_code}: {resp.read().decode()[:300]}")
        for data in _sse(resp):
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices", []):
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    yield piece


def _gemini(system_prompt: str, history: list[dict], cfg: LlmConfig, timeout: float) -> Iterator[str]:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise LlmError("manca GEMINI_API_KEY")
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in history
    ]
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": cfg.temperature,
            "maxOutputTokens": cfg.max_output_tokens,
        },
    }
    with httpx.stream(
        "POST",
        GEMINI_URL.format(model=cfg.model),
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        json=payload,
        timeout=timeout,
    ) as resp:
        if resp.status_code >= 400:
            raise LlmError(f"Gemini LLM {resp.status_code}: {resp.read().decode()[:300]}")
        for data in _sse(resp):
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            for cand in chunk.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text"):
                        yield part["text"]


def _sse(resp: httpx.Response) -> Iterator[str]:
    for line in resp.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        yield data


def trim_history(history: list[dict], turns: int) -> list[dict]:
    """Tiene solo gli ultimi `turns` scambi (1 scambio = domanda + risposta)."""
    if turns <= 0:
        return list(history)
    return history[-turns * 2 :]
