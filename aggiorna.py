"""Aggiorna her all'ultima versione, senza perdere chiavi e registrazioni.

Scarica lo zip del progetto da GitHub e sostituisce i file del programma.
NON tocca mai: `.env` (le tue chiavi), `sessions/` (le tue puntate), `.venv`.
I preset vengono salvati in `presets-backup/` prima di essere sovrascritti,
così se ne hai modificato uno lo ritrovi.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO = "gabbariele/her"
BRANCH = "claude/interactive-podcast-audio-software-9yczan"
URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"

#: quello che è tuo e non va toccato per nessun motivo
PRESERVE = {".env", "sessions", ".venv", "presets-backup", ".git"}


def main(here: Path | None = None) -> int:
    here = here or Path(__file__).resolve().parent
    print("Aggiornamento di her")
    print(f"  scarico da github.com/{REPO}")
    try:
        with urllib.request.urlopen(URL, timeout=120) as resp:
            blob = resp.read()
    except Exception as exc:
        print(f"  ✗ download fallito: {exc}")
        print("    Controlla la connessione e riprova.")
        return 1

    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        print("  ✗ il file scaricato non è valido, riprova più tardi.")
        return 1

    staging = here / ".aggiornamento"
    shutil.rmtree(staging, ignore_errors=True)
    archive.extractall(staging)
    roots = [p for p in staging.iterdir() if p.is_dir()]
    if len(roots) != 1:
        print("  ✗ archivio inatteso, aggiornamento annullato.")
        shutil.rmtree(staging, ignore_errors=True)
        return 1
    new = roots[0]

    if (here / "presets").exists():
        backup = here / "presets-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
        backup.parent.mkdir(exist_ok=True)
        shutil.copytree(here / "presets", backup)
        print(f"  ✓ preset salvati in {backup.relative_to(here)}")

    copied = 0
    for item in new.iterdir():
        if item.name in PRESERVE:
            continue
        target = here / item.name
        if item.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
            if target.suffix in (".sh", ".command") or not target.suffix:
                target.chmod(0o755)
        copied += 1
    shutil.rmtree(staging, ignore_errors=True)
    print(f"  ✓ aggiornati {copied} elementi (chiavi e registrazioni intatte)")

    if not (here / ".venv").exists():
        print("\nFatto (ambiente non trovato: se serve, rilancia setup).")
        return 0

    print("  aggiorno i componenti…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[audio]", "--quiet"],
        cwd=here,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print(f"  ! componenti non aggiornati: {result.stderr.strip()[:200]}")
        print("    Se qualcosa non funziona, rilancia setup.")
    else:
        print("  ✓ componenti aggiornati")

    print("\nFatto. Puoi registrare come sempre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
