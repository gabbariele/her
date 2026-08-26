"""Speech-to-text: trascrive un turno del conduttore (OpenAI o Gemini)."""
from __future__ import annotations

import base64

import httpx
import numpy as np

from ..audio.wavio import wav_bytes
from ..config import GEMINI_KEYS, OPENAI_KEYS, SttConfig, api_key

OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_PROMPT = (
    "Trascrivi letteralmente l'audio. Restituisci solo la trascrizione, "
    "senza commenti, senza virgolette."
)


class SttError(RuntimeError):
    pass


def transcribe(samples: np.ndarray, sample_rate: int, cfg: SttConfig, timeout: float = 60.0) -> str:
    if samples.size == 0:
        return ""
    audio = wav_bytes(samples, sample_rate)
    if cfg.provider == "openai":
        return _openai(audio, cfg, timeout)
    if cfg.provider == "gemini":
        return _gemini(audio, cfg, timeout)
    raise SttError(f"provider STT sconosciuto: {cfg.provider}")


def _openai(audio: bytes, cfg: SttConfig, timeout: float) -> str:
    key = api_key(*OPENAI_KEYS)
    if not key:
        raise SttError("manca OPENAI_API_KEY")
    data = {"model": cfg.model, "response_format": "json"}
    if cfg.language:
        data["language"] = cfg.language
    if cfg.hint:
        data["prompt"] = cfg.hint
    resp = httpx.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {key}"},
        data=data,
        files={"file": ("turn.wav", audio, "audio/wav")},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise SttError(f"OpenAI STT {resp.status_code}: {resp.text[:300]}")
    return (resp.json().get("text") or "").strip()


def _gemini(audio: bytes, cfg: SttConfig, timeout: float) -> str:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise SttError("manca GEMINI_API_KEY")
    prompt = _PROMPT
    if cfg.language:
        prompt += f" La lingua parlata è: {cfg.language}."
    if cfg.hint:
        prompt += f" Termini che possono comparire: {cfg.hint}."
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(audio).decode()}},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.0},
    }
    resp = httpx.post(
        GEMINI_URL.format(model=cfg.model),
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise SttError(f"Gemini STT {resp.status_code}: {resp.text[:300]}")
    return _gemini_text(resp.json()).strip()


def _gemini_text(data: dict) -> str:
    out = []
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                out.append(part["text"])
    return "".join(out)
