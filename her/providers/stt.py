"""Speech-to-text: trascrive un turno del conduttore (OpenAI o Gemini)."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from typing import Callable

import httpx
import numpy as np

from ..audio.wavio import wav_bytes
from ..config import GEMINI_KEYS, OPENAI_KEYS, SttConfig, api_key
from . import _gemini, backoff as bo

OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"

#: quante volte al massimo si riprova cambiando modello o togliendo il thinking
_MAX_ATTEMPTS = 5
#: e quanti giri in più concedere ai tentativi per sovraccarico
_OVERLOAD_ATTEMPTS = 8

_PROMPT = (
    "Trascrivi letteralmente questo audio, parola per parola. "
    "Rispondi soltanto con la trascrizione: niente commenti, niente virgolette, "
    "niente descrizioni dell'audio. Se non si sente parlare nessuno, rispondi con una riga vuota."
)


class SttError(RuntimeError):
    pass


def _notify(notice: Callable[[str], None] | None, message: str) -> None:
    if notice is not None:
        notice(message)


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
    notice: Callable[[str], None] | None = None,
) -> str:
    if samples.size == 0:
        return ""
    audio = wav_bytes(samples, sample_rate)
    if cfg.provider == "openai":
        return _openai(audio, cfg, timeout, client, notice)
    if cfg.provider == "gemini":
        return _gemini_transcribe(audio, cfg, timeout, client, notice)
    raise SttError(f"provider STT sconosciuto: {cfg.provider}")


def _openai(audio: bytes, cfg: SttConfig, timeout: float, client, notice=None) -> str:
    key = api_key(*OPENAI_KEYS)
    if not key:
        raise SttError("manca OPENAI_API_KEY")
    data = {"model": cfg.model, "response_format": "json"}
    if cfg.language:
        data["language"] = cfg.language
    if cfg.hint:
        data["prompt"] = cfg.hint
    attesa = bo.Backoff(budget_s=cfg.retry_budget_s)
    with _client(client, timeout) as http:
        while True:
            resp = http.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {key}"},
                data=data,
                files={"file": ("turn.wav", audio, "audio/wav")},
                timeout=timeout,
            )
            if resp.status_code < 400:
                return (resp.json().get("text") or "").strip()
            if bo.handle(resp.status_code, resp.headers, attesa, "OpenAI", notice):
                continue
            if resp.status_code in bo.RETRYABLE:
                raise SttError(attesa.message(resp.status_code, "OpenAI"))
            raise SttError(f"OpenAI STT {resp.status_code}: {resp.text[:300]}")


def _gemini_payload(audio: bytes, cfg: SttConfig) -> dict:
    prompt = _PROMPT
    if cfg.language:
        prompt += f" La lingua parlata è: {cfg.language}."
    if cfg.hint:
        prompt += f" Possono comparire questi termini: {cfg.hint}."
    generation: dict = {"temperature": 0.0}
    thinking = _gemini.thinking_config(cfg.thinking, cfg.model)
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


def _gemini_transcribe(audio: bytes, cfg: SttConfig, timeout: float, client, notice) -> str:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise SttError("manca GEMINI_API_KEY")
    headers = {"x-goog-api-key": key, "content-type": "application/json"}
    payload = _gemini_payload(audio, cfg)
    model = cfg.model
    tried = {_gemini.normalize_model(model)}
    attesa = bo.Backoff(budget_s=cfg.retry_budget_s)

    with _client(client, timeout) as http:
        for _ in range(_MAX_ATTEMPTS + _OVERLOAD_ATTEMPTS):
            resp = http.post(
                _gemini.endpoint(model, "generateContent"),
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                # sovraccarico: aspetta e riprova finché il budget lo consente
                if bo.handle(resp.status_code, resp.headers, attesa, "Gemini", notice):
                    continue
                if resp.status_code in bo.RETRYABLE:
                    raise SttError(attesa.message(resp.status_code, "Gemini"))
                detail = resp.text
                # un modello ritirato o un parametro non gradito si recuperano
                # da soli: sarebbe assurdo perdere il turno per questo
                retry = _gemini.plan_retry(resp.status_code, detail, payload, model, tried, "stt")
                if retry is None:
                    raise SttError(f"Gemini STT {resp.status_code}: {detail[:300]}")
                _notify(notice, retry.notice)
                payload, model = retry.payload, retry.model
                tried.add(_gemini.normalize_model(model))
                continue

            data = resp.json()
            text = _gemini.response_text(data).strip()
            if text:
                return _clean(text)
            # nessun testo: se ha esaurito i token pensando, avvisa invece di
            # far finta che il conduttore non abbia detto niente
            if _gemini.finish_reason(data).upper() == "MAX_TOKENS":
                raise SttError(_gemini.empty_answer_hint("MAX_TOKENS", "", model))
            return ""
    raise SttError("Gemini STT: troppi tentativi falliti di seguito")


def _clean(text: str) -> str:
    """Toglie le virgolette che certi modelli mettono intorno alla trascrizione."""
    text = text.strip()
    if len(text) > 1 and text[0] in "\"'«" and text[-1] in "\"'»":
        text = text[1:-1].strip()
    return text
