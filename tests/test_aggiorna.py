"""L'aggiornamento non deve mai portarsi via chiavi e registrazioni."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def aggiorna():
    spec = importlib.util.spec_from_file_location("aggiorna", ROOT / "aggiorna.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_release(path: Path) -> str:
    """Uno zip con la stessa forma di quelli di GitHub (una sola cartella radice)."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("her-nuovo/her/cli.py", "# versione nuova\n")
        zf.writestr("her-nuovo/presets/gemini.yaml", "persona:\n  name: Nova\n")
        zf.writestr("her-nuovo/README.md", "nuovo readme\n")
        zf.writestr("her-nuovo/setup.sh", "#!/bin/sh\necho ciao\n")
    return path.as_uri()


def test_update_replaces_code_but_keeps_your_stuff(tmp_path, aggiorna, monkeypatch):
    home = tmp_path / "her"
    (home / "her").mkdir(parents=True)
    (home / "presets").mkdir()
    (home / "sessions" / "20260101-120000").mkdir(parents=True)

    (home / "her" / "cli.py").write_text("# versione vecchia\n")
    (home / "presets" / "gemini.yaml").write_text("persona:\n  name: IlMioOspite\n")
    (home / ".env").write_text("GEMINI_API_KEY=la-mia-chiave\nHER_VOICE_ID=voce123\n")
    (home / "sessions" / "20260101-120000" / "podcast.wav").write_bytes(b"RIFF...")

    monkeypatch.setattr(aggiorna, "URL", _fake_release(tmp_path / "release.zip"))
    assert aggiorna.main(here=home) == 0

    # il codice è aggiornato
    assert (home / "her" / "cli.py").read_text() == "# versione nuova\n"
    assert (home / "README.md").read_text() == "nuovo readme\n"
    # le tue cose sono intatte
    assert "la-mia-chiave" in (home / ".env").read_text()
    assert (home / "sessions" / "20260101-120000" / "podcast.wav").exists()
    # il preset che avevi modificato è recuperabile
    backups = list((home / "presets-backup").glob("*/gemini.yaml"))
    assert len(backups) == 1
    assert "IlMioOspite" in backups[0].read_text()
    # e non resta sporcizia
    assert not (home / ".aggiornamento").exists()


def test_update_survives_a_broken_download(tmp_path, aggiorna, monkeypatch):
    home = tmp_path / "her"
    home.mkdir()
    (home / ".env").write_text("GEMINI_API_KEY=intatta\n")
    broken = tmp_path / "rotto.zip"
    broken.write_bytes(b"non sono uno zip")

    monkeypatch.setattr(aggiorna, "URL", broken.as_uri())
    assert aggiorna.main(here=home) == 1
    assert "intatta" in (home / ".env").read_text()


def test_update_keeps_the_episode_notes(tmp_path, aggiorna, monkeypatch):
    home = tmp_path / "her"
    (home / "contesto-cache").mkdir(parents=True)
    (home / "contesto.md").write_text("# Puntata di domani\nSi parla di vinile.\n")
    (home / "contesto-cache" / "abc.json").write_text('{"url": "x"}')

    monkeypatch.setattr(aggiorna, "URL", _fake_release(tmp_path / "release.zip"))
    assert aggiorna.main(here=home) == 0
    assert "vinile" in (home / "contesto.md").read_text()
    assert (home / "contesto-cache" / "abc.json").exists()
