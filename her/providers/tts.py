"""Text-to-speech ElevenLabs in streaming (PCM grezzo, pronto da riprodurre)."""
from __future__ import annotations

from typing import Iterator

import httpx
import numpy as np

from ..audio.wavio import pcm_to_array
from ..config import ELEVEN_KEYS, TtsConfig, api_key

BASE = "https://api.elevenlabs.io/v1"
#: ElevenLabs esporta PCM solo a questi sample rate
SUPPORTED_RATES = (16000, 22050, 24000, 44100)


class TtsError(RuntimeError):
    pass


def voice_settings(cfg: TtsConfig) -> dict:
    settings = {
        "stability": cfg.stability,
        "similarity_boost": cfg.similarity_boost,
        "style": cfg.style,
        "use_speaker_boost": cfg.use_speaker_boost,
    }
    if abs(cfg.speed - 1.0) > 1e-6:
        settings["speed"] = cfg.speed
    return settings


def stream_speech(
    text: str,
    cfg: TtsConfig,
    sample_rate: int = 24000,
    timeout: float = 60.0,
) -> Iterator[np.ndarray]:
    """Sintetizza `text` e restituisce i blocchi audio int16 man mano che arrivano."""
    if not text.strip():
        return
    key = api_key(*ELEVEN_KEYS)
    if not key:
        raise TtsError("manca ELEVENLABS_API_KEY")
    if not cfg.voice_id:
        raise TtsError("nessuna voce selezionata: imposta tts.voice_id (vedi `her voices`)")
    if sample_rate not in SUPPORTED_RATES:
        raise TtsError(f"sample rate {sample_rate} non supportato da ElevenLabs (usa {SUPPORTED_RATES})")

    params = {
        "output_format": f"pcm_{sample_rate}",
        "optimize_streaming_latency": str(cfg.optimize_streaming_latency),
    }
    payload = {
        "text": text,
        "model_id": cfg.model,
        "voice_settings": voice_settings(cfg),
    }
    tail = b""
    with httpx.stream(
        "POST",
        f"{BASE}/text-to-speech/{cfg.voice_id}/stream",
        headers={"xi-api-key": key, "content-type": "application/json"},
        params=params,
        json=payload,
        timeout=timeout,
    ) as resp:
        if resp.status_code >= 400:
            raise TtsError(f"ElevenLabs TTS {resp.status_code}: {resp.read().decode()[:300]}")
        for chunk in resp.iter_bytes():
            if not chunk:
                continue
            data = tail + chunk
            # un blocco può spezzare un campione a metà: il byte dispari va rinviato
            if len(data) % 2:
                data, tail = data[:-1], data[-1:]
            else:
                tail = b""
            if data:
                yield pcm_to_array(data)


def synthesize(text: str, cfg: TtsConfig, sample_rate: int = 24000) -> np.ndarray:
    chunks = list(stream_speech(text, cfg, sample_rate))
    if not chunks:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(chunks).astype(np.int16)


def list_voices(timeout: float = 30.0) -> list[dict]:
    key = api_key(*ELEVEN_KEYS)
    if not key:
        raise TtsError("manca ELEVENLABS_API_KEY")
    resp = httpx.get(f"{BASE}/voices", headers={"xi-api-key": key}, timeout=timeout)
    if resp.status_code >= 400:
        raise TtsError(f"ElevenLabs voices {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("voices", [])
