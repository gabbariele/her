"""Chiamate a ElevenLabs verificate senza rete."""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from her.config import TtsConfig
from her.providers.tts import TtsError, stream_speech, synthesize


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "chiave-finta")


def _pcm(n: int) -> bytes:
    return (np.arange(n, dtype=np.int16) * 3).tobytes()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_language_is_sent_so_the_voice_speaks_italian():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["key"] = request.headers.get("xi-api-key")
        return httpx.Response(200, content=_pcm(240))

    cfg = TtsConfig(voice_id="voce123", model="eleven_turbo_v2_5", language="it")
    with _client(handler) as http:
        audio = synthesize("ciao a tutti", cfg, 24000, client=http)

    assert audio.size == 240
    assert seen["body"]["language_code"] == "it"
    assert seen["body"]["model_id"] == "eleven_turbo_v2_5"
    assert "voce123/stream" in seen["url"]
    assert "output_format=pcm_24000" in seen["url"]


def test_language_is_omitted_when_empty():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_pcm(10))

    with _client(handler) as http:
        synthesize("ciao", TtsConfig(voice_id="v", language=""), client=http)
    assert "language_code" not in seen["body"]


def test_retries_without_language_if_the_model_refuses_it():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "language_code" in body:
            return httpx.Response(400, json={"detail": "language_code is not supported for this model"})
        return httpx.Response(200, content=_pcm(100))

    cfg = TtsConfig(voice_id="v", model="eleven_multilingual_v2", language="it")
    with _client(handler) as http:
        audio = synthesize("ciao", cfg, client=http)

    assert audio.size == 100
    assert len(calls) == 2 and "language_code" not in calls[1]


def test_other_errors_are_reported_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"detail": "chiave non valida"})

    with _client(handler) as http:
        with pytest.raises(TtsError, match="401"):
            synthesize("ciao", TtsConfig(voice_id="v"), client=http)
    assert len(calls) == 1


def test_odd_byte_at_the_chunk_boundary_is_not_lost():
    """Un blocco può tagliare un campione a metà: il byte va tenuto per il dopo."""
    raw = _pcm(50)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw)

    with _client(handler) as http:
        chunks = list(stream_speech("ciao", TtsConfig(voice_id="v"), client=http))
    assert np.concatenate(chunks).tobytes() == raw


def test_voice_must_be_chosen():
    with pytest.raises(TtsError, match="voce"):
        synthesize("ciao", TtsConfig(voice_id=""))


def test_empty_text_is_not_sent():
    def handler(request):  # pragma: no cover - non deve essere chiamato
        raise AssertionError("chiamata inattesa")

    with _client(handler) as http:
        assert list(stream_speech("   ", TtsConfig(voice_id="v"), client=http)) == []
