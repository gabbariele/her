"""Utility di testo: pulizia per il TTS e taglio in frasi per lo streaming."""
from __future__ import annotations

import re
from typing import Iterable, Iterator

_MD_NOISE = re.compile(r"[*_`#]+")
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_SPACES = re.compile(r"[ \t]+")
_SENTENCE_END = ".!?…:;\n"


def clean_for_tts(text: str) -> str:
    """Toglie il markdown: letto ad alta voce suonerebbe come rumore."""
    text = _CODE_FENCE.sub(" ", text)
    text = _MD_NOISE.sub("", text)
    text = text.replace(" ", " ")
    text = _SPACES.sub(" ", text)
    return text.strip()


def split_sentences(text: str, min_chars: int = 60) -> list[str]:
    return list(iter_sentences([text], min_chars=min_chars))


def iter_sentences(tokens: Iterable[str], min_chars: int = 60) -> Iterator[str]:
    """Accumula i token dell'LLM e li rilascia frase per frase.

    Mandare al TTS la prima frase appena è pronta, invece di aspettare tutta la
    risposta, è ciò che tiene la latenza percepita intorno al secondo.
    `min_chars` evita di sintetizzare spezzoni troppo corti ("Certo." "Ok.")
    che spezzerebbero la prosodia.
    """
    buf = ""
    for token in tokens:
        if not token:
            continue
        buf += token
        while True:
            cut = _find_cut(buf, min_chars)
            if cut is None:
                break
            chunk, buf = buf[:cut], buf[cut:]
            chunk = clean_for_tts(chunk)
            if chunk:
                yield chunk
    tail = clean_for_tts(buf)
    if tail:
        yield tail


def _find_cut(buf: str, min_chars: int) -> int | None:
    """Indice dopo cui tagliare, oppure None se conviene aspettare altro testo."""
    for i, ch in enumerate(buf):
        if ch not in _SENTENCE_END:
            continue
        if i + 1 < min_chars:
            continue
        # "3.14" o "ecc." non chiudono una frase: serve uno spazio (o fine buffer).
        if ch == "." and i + 1 < len(buf) and buf[i + 1].isdigit():
            continue
        j = i + 1
        while j < len(buf) and buf[j] in _SENTENCE_END:
            j += 1
        if j < len(buf) and not buf[j].isspace():
            continue
        return j
    return None
