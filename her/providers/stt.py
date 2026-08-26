"""Speech-to-text: trascrive un turno del conduttore (OpenAI o Gemini)."""
from __future__ import annotations

import base64
from contextlib import contextmanager

import httpx
import numpy as np

from ..audio.wavio import wav_bytes
from ..config import GEMINI_KEYS, OPENAI_KEYS, SttConfig, api_key
from . import _gemini

OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"

_PROMPT = (
    "Trascrivi letteralmente questo audio, parola per parola. "
    "Rispondi soltanto con la trascrizione: niente commenti, niente virgolette, "
    "niente descrizioni dell'audio. Se non si sente parlare nessuno, rispondi con una riga vuota."
)


class SttError(RuntimeError):
    pass


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


def transcribe(
    samples: np.ndarray,
    sample_rate: int,
    cfg: SttConfig,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
) -> str:
    if samples.size == 0:
        return ""
    audio = wav_bytes(samples, sample_rate)
    if cfg.provider == "openai":
        return _openai(audio, cfg, timeout, client)
    if cfg.provider == "gemini":
        return _gemini_transcribe(audio, cfg, timeout, client)
    raise SttError(f"provider STT sconosciuto: {cfg.provider}")


def _openai(audio: bytes, cfg: SttConfig, timeout: float, client) -> str:
    key = api_key(*OPENAI_KEYS)
    if not key:
        raise SttError("manca OPENAI_API_KEY")
    data = {"model": cfg.model, "response_format": "json"}
    if cfg.language:
        data["language"] = cfg.language
    if cfg.hint:
        data["prompt"] = cfg.hint
    with _client(client, timeout) as http:
        resp = http.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}"},
            data=data,
            files={"file": ("turn.wav", audio, "audio/wav")},
            timeout=timeout,
        )
    if resp.status_code >= 400:
        raise SttError(f"OpenAI STT {resp.status_code}: {resp.text[:300]}")
    return (resp.json().get("text") or "").strip()


def _gemini_payload(audio: bytes, cfg: SttConfig) -> dict:
    prompt = _PROMPT
    if cfg.language:
        prompt += f" La lingua parlata è: {cfg.language}."
    if cfg.hint:
        prompt += f" Possono comparire questi termini: {cfg.hint}."
    generation: dict = {"temperature": 0.0}
    thinking = _gemini.thinking_config(cfg.thinking)
    if thinking is not None:
        generation["thinkingConfig"] = thinking
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "audio/wav",
                            "data": base64.b64encode(audio).decode(),
                        }
                    },
                ],
            }
        ],
        "generationConfig": generation,
    }


def _gemini_transcribe(audio: bytes, cfg: SttConfig, timeout: float, client) -> str:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise SttError("manca GEMINI_API_KEY")
    url = _gemini.endpoint(cfg.model, "generateContent")
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    payload = _gemini_payload(audio, cfg)

    with _client(client, timeout) as http:
        for attempt, body in enumerate((payload, _gemini.strip_thinking(payload))):
            resp = http.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code >= 400:
                if attempt == 0 and _gemini.is_thinking_error(resp.status_code, resp.text):
                    continue
                raise SttError(f"Gemini STT {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            text = _gemini.response_text(data).strip()
            if text:
                return _clean(text)
            # nessun testo: se ha esaurito i token pensando, avvisa invece di
            # far finta che il conduttore non abbia detto niente
            finish = _gemini.finish_reason(data)
            if finish.upper() == "MAX_TOKENS":
                raise SttError(_gemini.empty_answer_hint(finish, "", cfg.model))
            return ""
    return ""


def _clean(text: str) -> str:
    """Toglie le virgolette che certi modelli mettono intorno alla trascrizione."""
    text = text.strip()
    if len(text) > 1 and text[0] in "\"'«" and text[-1] in "\"'»":
        text = text[1:-1].strip()
    return text
