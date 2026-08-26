"""Verifica delle chiamate a Gemini senza toccare la rete (httpx.MockTransport)."""
from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from her.config import LlmConfig, SttConfig
from her.providers import _gemini
from her.providers.llm import LlmError, stream_reply
from her.providers.stt import SttError, transcribe


def _sse(*chunks: dict) -> bytes:
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks)


def _text_chunk(text: str, **extra) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, **extra}]}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-finta-per-i-test")


# -- configurazione del ragionamento ---------------------------------------
def test_thinking_config_mapping():
    assert _gemini.thinking_config("off") == {"thinkingBudget": 0}
    assert _gemini.thinking_config(False) == {"thinkingBudget": 0}      # `thinking: off` in YAML
    assert _gemini.thinking_config("low") == {"thinkingLevel": "low"}
    assert _gemini.thinking_config("2048") == {"thinkingBudget": 2048}
    assert _gemini.thinking_config("auto") is None
    with pytest.raises(ValueError):
        _gemini.thinking_config("moltissimo")


def test_model_name_is_normalized():
    assert _gemini.normalize_model("models/gemini-2.5-flash") == "gemini-2.5-flash"
    assert "models/gemini-2.5-flash:generateContent" in _gemini.endpoint("gemini-2.5-flash", "generateContent")


# -- risposte dell'ospite ---------------------------------------------------
def test_llm_payload_shape_and_streaming():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(_text_chunk("Ciao, "), _text_chunk("come va?")))

    cfg = LlmConfig(provider="gemini", model="gemini-3.5-flash-lite", thinking="off")
    history = [{"role": "user", "content": "ciao"}, {"role": "assistant", "content": "ehi"}]
    with _client(handler) as http:
        out = "".join(stream_reply("sei un ospite", history, cfg, client=http))

    assert out == "Ciao, come va?"
    assert seen["url"].endswith("models/gemini-3.5-flash-lite:streamGenerateContent?alt=sse")
    body = seen["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "sei un ospite"
    assert [c["role"] for c in body["contents"]] == ["user", "model"]   # assistant -> model
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert body["generationConfig"]["maxOutputTokens"] == cfg.max_output_tokens


def test_llm_skips_the_models_inner_thoughts():
    chunk = {"candidates": [{"content": {"parts": [
        {"text": "sto ragionando", "thought": True},
        {"text": "questa e la risposta"},
    ]}}]}

    with _client(lambda r: httpx.Response(200, content=_sse(chunk))) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}],
                                   LlmConfig(provider="gemini"), client=http))
    assert out == "questa e la risposta"


def test_llm_retries_once_without_thinking_if_rejected():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "thinkingConfig" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"message": "thinkingConfig is not supported"}})
        return httpx.Response(200, content=_sse(_text_chunk("va bene lo stesso")))

    cfg = LlmConfig(provider="gemini", thinking="off")
    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}], cfg, client=http))

    assert out == "va bene lo stesso"
    assert len(calls) == 2
    assert "thinkingConfig" not in calls[1]["generationConfig"]


def test_llm_other_errors_are_not_retried():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "quota esaurita"}})

    with _client(handler) as http:
        with pytest.raises(LlmError, match="429"):
            list(stream_reply("s", [{"role": "user", "content": "x"}],
                              LlmConfig(provider="gemini"), client=http))
    assert len(calls) == 1


def test_llm_empty_answer_explains_what_to_change():
    chunk = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
    with _client(lambda r: httpx.Response(200, content=_sse(chunk))) as http:
        with pytest.raises(LlmError, match="max_output_tokens"):
            list(stream_reply("s", [{"role": "user", "content": "x"}],
                              LlmConfig(provider="gemini"), client=http))


# -- trascrizione ------------------------------------------------------------
def test_stt_sends_inline_wav_and_cleans_quotes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_text_chunk('"buongiorno a tutti"'))

    cfg = SttConfig(provider="gemini", model="gemini-2.5-flash-lite", language="it")
    audio = (np.sin(np.arange(2400)) * 1000).astype(np.int16)
    with _client(handler) as http:
        text = transcribe(audio, 24000, cfg, client=http)

    assert text == "buongiorno a tutti"
    assert seen["url"].endswith("models/gemini-2.5-flash-lite:generateContent")
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[1]["inlineData"]["mimeType"] == "audio/wav"
    assert parts[1]["inlineData"]["data"]                      # base64 non vuoto
    assert "italiano" in parts[0]["text"] or "it" in parts[0]["text"]


def test_stt_empty_audio_never_calls_the_api():
    def handler(request):  # pragma: no cover - non deve essere chiamato
        raise AssertionError("chiamata inattesa")

    with _client(handler) as http:
        assert transcribe(np.zeros(0, dtype=np.int16), 24000,
                          SttConfig(provider="gemini"), client=http) == ""


def test_stt_reports_api_errors():
    with _client(lambda r: httpx.Response(403, json={"error": {"message": "chiave non valida"}})) as http:
        with pytest.raises(SttError, match="403"):
            transcribe(np.ones(100, dtype=np.int16), 24000, SttConfig(provider="gemini"), client=http)


def test_stt_silence_returns_empty_string():
    with _client(lambda r: httpx.Response(200, json=_text_chunk("  "))) as http:
        assert transcribe(np.ones(100, dtype=np.int16), 24000,
                          SttConfig(provider="gemini"), client=http) == ""


# -- modelli ritirati da Google ---------------------------------------------
RITIRATO = {
    "error": {
        "code": 404,
        "message": (
            "This model models/gemini-2.5-flash-lite is no longer available to new users. "
            "Please update your code to use models/gemini-3.5-flash-lite for the latest "
            "features and improvements."
        ),
        "status": "NOT_FOUND",
    }
}


def test_suggested_model_is_read_from_the_error():
    body = json.dumps(RITIRATO)
    assert _gemini.suggested_model(body, "gemini-2.5-flash-lite") == "gemini-3.5-flash-lite"
    # un errore qualsiasi non deve far cambiare modello
    assert _gemini.suggested_model('{"error": {"message": "quota esaurita"}}', "x") is None


def test_stt_follows_googles_advice_when_a_model_is_retired():
    chiamate, avvisi = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        chiamate.append(str(request.url))
        if "gemini-2.5-flash-lite" in str(request.url):
            return httpx.Response(404, json=RITIRATO)
        return httpx.Response(200, json=_text_chunk("ci siamo"))

    cfg = SttConfig(provider="gemini", model="gemini-2.5-flash-lite")
    with _client(handler) as http:
        text = transcribe(np.ones(100, dtype=np.int16), 24000, cfg,
                          client=http, notice=avvisi.append)

    assert text == "ci siamo"                       # il turno non è andato perso
    assert len(chiamate) == 2
    assert "gemini-3.5-flash-lite" in chiamate[1]
    assert "gemini-3.5-flash-lite" in avvisi[0] and "preset" in avvisi[0]


def test_llm_follows_googles_advice_too():
    avvisi = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "gemini-2.5-flash-lite" in str(request.url):
            return httpx.Response(404, json=RITIRATO)
        return httpx.Response(200, content=_sse(_text_chunk("eccomi")))

    cfg = LlmConfig(provider="gemini", model="gemini-2.5-flash-lite")
    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}], cfg,
                                   client=http, notice=avvisi.append))
    assert out == "eccomi"
    assert avvisi and "gemini-3.5-flash-lite" in avvisi[0]


def test_a_model_is_never_tried_twice():
    """Se il sostituto dà lo stesso errore non si va in cerchio."""
    chiamate = []

    def handler(request: httpx.Request) -> httpx.Response:
        chiamate.append(str(request.url))
        return httpx.Response(404, json=RITIRATO)

    cfg = SttConfig(provider="gemini", model="gemini-2.5-flash-lite")
    with _client(handler) as http:
        with pytest.raises(SttError, match="404"):
            transcribe(np.ones(100, dtype=np.int16), 24000, cfg, client=http)
    assert len(chiamate) == 2
