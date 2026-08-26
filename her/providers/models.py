"""Elenco dei modelli disponibili con la propria chiave.

I nomi dei modelli cambiano spesso: invece di fidarsi di una lista scritta a
mano, `her models` chiede al provider cosa offre davvero a questo account.
"""
from __future__ import annotations

import httpx

from ..config import GEMINI_KEYS, OPENAI_KEYS, api_key
from . import _gemini


class ModelsError(RuntimeError):
    pass


def list_models(provider: str, timeout: float = 30.0) -> list[dict]:
    if provider == "gemini":
        return _gemini_models(timeout)
    if provider == "openai":
        return _openai_models(timeout)
    raise ModelsError(f"provider sconosciuto: {provider}")


def _gemini_models(timeout: float) -> list[dict]:
    key = api_key(*GEMINI_KEYS)
    if not key:
        raise ModelsError("manca GEMINI_API_KEY")
    out: list[dict] = []
    params: dict = {"pageSize": 200}
    with httpx.Client(timeout=timeout) as http:
        while True:
            resp = http.get(f"{_gemini.BASE}/models", headers={"x-goog-api-key": key}, params=params)
            if resp.status_code >= 400:
                raise ModelsError(f"Gemini models {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            for model in data.get("models", []):
                methods = model.get("supportedGenerationMethods") or []
                out.append(
                    {
                        "id": _gemini.normalize_model(model.get("name", "")),
                        "name": model.get("displayName") or "",
                        "methods": methods,
                        "usable": "generateContent" in methods,
                    }
                )
            token = data.get("nextPageToken")
            if not token:
                break
            params = {"pageSize": 200, "pageToken": token}
    out.sort(key=lambda m: m["id"])
    return out


def _openai_models(timeout: float) -> list[dict]:
    key = api_key(*OPENAI_KEYS)
    if not key:
        raise ModelsError("manca OPENAI_API_KEY")
    with httpx.Client(timeout=timeout) as http:
        resp = http.get(
            "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}
        )
    if resp.status_code >= 400:
        raise ModelsError(f"OpenAI models {resp.status_code}: {resp.text[:300]}")
    models = [
        {"id": m.get("id", ""), "name": "", "methods": [], "usable": True}
        for m in resp.json().get("data", [])
    ]
    models.sort(key=lambda m: m["id"])
    return models
