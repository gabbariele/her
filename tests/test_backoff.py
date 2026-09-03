"""Sovraccarico del provider: aspettare e riprovare, ma non all'infinito."""
from __future__ import annotations

import httpx
import numpy as np
import pytest

from her.config import LlmConfig, SttConfig, TtsConfig
from her.providers import backoff as bo
from her.providers.llm import LlmError, stream_reply
from her.providers.stt import SttError, transcribe
from her.providers.tts import TtsError, synthesize


@pytest.fixture(autouse=True)
def niente_attese(monkeypatch):
    """I test non devono davvero dormire: registriamo le attese e basta."""
    attese = []
    monkeypatch.setattr(bo, "sleep", attese.append)
    monkeypatch.setenv("GEMINI_API_KEY", "chiave-finta")
    monkeypatch.setenv("OPENAI_API_KEY", "chiave-finta")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "chiave-finta")
    return attese


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _sse(text: str) -> bytes:
    import json
    chunk = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return b"data: " + json.dumps(chunk).encode() + b"\n\n"


# -- la meccanica -----------------------------------------------------------
def test_only_temporary_errors_are_retried():
    assert bo.Backoff().wait_for(503) is not None
    assert bo.Backoff().wait_for(429) is not None
    assert bo.Backoff().wait_for(400) is None      # richiesta sbagliata
    assert bo.Backoff().wait_for(403) is None      # chiave sbagliata
    assert bo.Backoff().wait_for(404) is None      # modello inesistente


def test_waits_grow_and_stay_within_the_budget():
    attesa = bo.Backoff(budget_s=100.0, base_s=1.0, cap_s=8.0)
    tempi = [attesa.wait_for(503) for _ in range(5)]
    assert all(t is not None for t in tempi)
    assert tempi[0] < tempi[-1]                    # crescono
    assert max(tempi) <= 8.0 * 1.3 + 1e-6          # ma con un tetto


def test_the_provider_can_say_when_to_come_back():
    assert bo.Backoff(budget_s=30).wait_for(429, {"retry-after": "5"}) == 5.0
    # se chiede più di quanto abbiamo, si rinuncia invece di piantarsi
    assert bo.Backoff(budget_s=3).wait_for(429, {"retry-after": "60"}) is None
    assert bo.Backoff().wait_for(429, {"retry-after": "lunedì"}) is not None


def test_two_clients_do_not_retry_in_lockstep():
    """Senza casualità tutti i client del mondo ritentano nello stesso istante."""
    tempi = {bo.Backoff(base_s=1.0).wait_for(503) for _ in range(20)}
    assert len(tempi) > 1


# -- i provider -------------------------------------------------------------
def test_the_llm_survives_an_overloaded_model(niente_attese):
    tentativi = []
    avvisi = []

    def handler(request):
        tentativi.append(1)
        if len(tentativi) < 3:
            return httpx.Response(503, json={"error": {"message": "model is overloaded"}})
        return httpx.Response(200, content=_sse("eccomi"))

    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}],
                                   LlmConfig(provider="gemini"), client=http,
                                   notice=avvisi.append))
    assert out == "eccomi"
    assert len(tentativi) == 3
    assert len(niente_attese) == 2                 # due attese, crescenti
    assert "sovraccarico" in avvisi[0]


def test_the_llm_gives_up_with_a_clear_message(niente_attese):
    with _client(lambda r: httpx.Response(503, text="overloaded")) as http:
        with pytest.raises(LlmError, match="sovraccarico"):
            list(stream_reply("s", [{"role": "user", "content": "x"}],
                              LlmConfig(provider="gemini", retry_budget_s=2.0), client=http))


def test_transcription_survives_too(niente_attese):
    tentativi = []

    def handler(request):
        tentativi.append(1)
        if len(tentativi) == 1:
            return httpx.Response(429, json={"error": {"message": "rate limit"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ciao"}]}}]})

    with _client(handler) as http:
        assert transcribe(np.ones(100, dtype=np.int16), 24000,
                          SttConfig(provider="gemini", model="gemini-3.5-flash"),
                          client=http) == "ciao"
    assert len(tentativi) == 2


def test_the_voice_survives_too(niente_attese):
    tentativi = []

    def handler(request):
        tentativi.append(1)
        if len(tentativi) == 1:
            return httpx.Response(503, text="overloaded")
        return httpx.Response(200, content=(np.arange(50, dtype=np.int16)).tobytes())

    with _client(handler) as http:
        audio = synthesize("ciao", TtsConfig(voice_id="v"), client=http)
    assert audio.size == 50 and len(tentativi) == 2


def test_a_stream_already_started_is_never_restarted(niente_attese):
    """Ritentare a metà risposta la farebbe uscire doppia."""
    tentativi = []

    def handler(request):
        tentativi.append(1)
        return httpx.Response(200, content=_sse("prima parte"))

    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}],
                                   LlmConfig(provider="gemini"), client=http))
    assert out == "prima parte" and len(tentativi) == 1


# -- il ripiego su un altro provider ----------------------------------------
def test_a_slow_primary_hands_over_to_the_fallback(niente_attese, monkeypatch):
    """Se Gemini non risponde in tempo, la battuta la scrive ChatGPT."""
    chiamate = []
    avvisi = []

    def handler(request):
        chiamate.append(str(request.url))
        if "generativelanguage" in str(request.url):
            raise httpx.ReadTimeout("troppo lento", request=request)
        return httpx.Response(200, content=(
            b'data: {"choices":[{"delta":{"content":"eccomi"}}]}\n\n'))

    cfg = LlmConfig(provider="gemini", model="gemini-3.5-flash",
                    fallback_provider="openai", fallback_model="gpt-4o-mini")
    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}], cfg,
                                   client=http, notice=avvisi.append))

    assert out == "eccomi"
    assert "generativelanguage" in chiamate[0] and "api.openai.com" in chiamate[-1]
    assert "troppo lento" in avvisi[-1] and "gpt-4o-mini" in avvisi[-1]


def test_an_overloaded_primary_hands_over_too(niente_attese):
    chiamate = []

    def handler(request):
        chiamate.append(str(request.url))
        if "generativelanguage" in str(request.url):
            return httpx.Response(503, text="model is overloaded")
        return httpx.Response(200, content=(
            b'data: {"choices":[{"delta":{"content":"ci penso io"}}]}\n\n'))

    cfg = LlmConfig(provider="gemini", model="gemini-3.5-flash", retry_budget_s=1.0,
                    fallback_provider="openai", fallback_model="gpt-4o-mini")
    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}], cfg, client=http))
    assert out == "ci penso io"
    assert any("api.openai.com" in c for c in chiamate)


def test_an_answer_already_started_is_never_handed_over(niente_attese):
    """A metà risposta si tiene quello che c'è: due modelli darebbero due testi."""
    def handler(request):
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, content=_sse("mezza rispo") + b"data: rotto\n\n")
        raise AssertionError("il ripiego non doveva essere chiamato")

    cfg = LlmConfig(provider="gemini", model="gemini-3.5-flash",
                    fallback_provider="openai", fallback_model="gpt-4o-mini")
    with _client(handler) as http:
        out = "".join(stream_reply("s", [{"role": "user", "content": "x"}], cfg, client=http))
    assert out == "mezza rispo"


def test_without_the_second_key_there_is_no_fallback(monkeypatch, niente_attese):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = LlmConfig(provider="gemini", model="gemini-3.5-flash")
    from her.providers.llm import chain

    assert [p.provider for p in chain(cfg, 120)] == ["gemini"]
    monkeypatch.setenv("OPENAI_API_KEY", "c'è")
    assert [p.provider for p in chain(cfg, 120)] == ["gemini", "openai"]


def test_the_primary_gets_a_short_leash_when_there_is_an_alternative():
    from her.providers.llm import chain

    cfg = LlmConfig(provider="gemini", model="gemini-3.5-flash",
                    fallback_after_s=4.0, retry_budget_s=10.0)
    passi = chain(cfg, 120)
    assert passi[0].timeout == 4.0 and passi[0].retry_budget_s == 4.0
    assert passi[-1].timeout == 120                      # al ripiego si dà tempo


def test_transcription_hands_over_too(niente_attese):
    chiamate = []

    def handler(request):
        chiamate.append(str(request.url))
        if "generativelanguage" in str(request.url):
            raise httpx.ReadTimeout("lento", request=request)
        return httpx.Response(200, json={"text": "trascritto dal ripiego"})

    cfg = SttConfig(provider="gemini", model="gemini-3.5-flash",
                    fallback_provider="openai", fallback_model="gpt-4o-mini-transcribe")
    with _client(handler) as http:
        testo = transcribe(np.ones(100, dtype=np.int16), 24000, cfg, client=http)
    assert testo == "trascritto dal ripiego"
    assert len(chiamate) == 2
