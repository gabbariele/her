#!/usr/bin/env bash
# Installazione automatica di her (Linux e macOS).
# Su Windows usa setup.bat.
set -u
cd "$(dirname "$0")"

BOLD=$'\033[1m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YELL=$'\033[33m'; OFF=$'\033[0m'
step() { echo; echo "${BOLD}$1${OFF}"; }
ok()   { echo "${GREEN}✓${OFF} $1"; }
bad()  { echo "${RED}✗${OFF} $1"; }

echo "${BOLD}Installazione di her${OFF}"
echo "Ci vogliono un paio di minuti. Non devi fare niente, guarda e basta."

# 1. Python -----------------------------------------------------------------
step "1/4  Cerco Python"
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  bad "Python 3.10 o successivo non trovato."
  echo
  echo "  Scaricalo da  ${BOLD}https://www.python.org/downloads/${OFF}"
  echo "  installalo, poi riapri questa finestra e rilancia l'installazione."
  exit 1
fi
ok "$($PY --version) trovato"

# 2. Ambiente isolato -------------------------------------------------------
step "2/4  Preparo l'ambiente (cartella .venv)"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv || { bad "creazione dell'ambiente fallita"; exit 1; }
fi
ok "ambiente pronto"

# 3. Dipendenze -------------------------------------------------------------
step "3/4  Scarico i componenti necessari"
./.venv/bin/python -m pip install --upgrade pip --quiet
if ./.venv/bin/python -m pip install -e ".[audio]" --quiet; then
  ok "componenti installati"
else
  bad "installazione dei componenti fallita (connessione? proxy?)"
  exit 1
fi

if [ "$(uname)" = "Linux" ] && ! ./.venv/bin/python -c "import sounddevice" 2>/dev/null; then
  echo "${YELL}!${OFF} Su Linux serve anche PortAudio:  sudo apt install libportaudio2"
fi
command -v ffmpeg >/dev/null 2>&1 \
  && ok "ffmpeg trovato (esporterà anche l'MP3)" \
  || echo "${YELL}!${OFF} ffmpeg non installato: avrai il WAV ma non l'MP3 (opzionale)"

# 4. Chiavi -----------------------------------------------------------------
step "4/4  File delle chiavi"
if [ ! -f .env ]; then
  cp .env.example .env
  ok "creato il file .env"
else
  ok "file .env già presente"
fi

echo
echo "${GREEN}${BOLD}Installazione completata.${OFF}"
echo
echo "${BOLD}Adesso tocca a te, due cose:${OFF}"
echo "  1. apri il file  ${BOLD}.env${OFF}  in questa cartella e incolla le tue chiavi API"
echo "  2. lancia   ${BOLD}./her.sh check${OFF}   per verificare che sia tutto a posto"
echo
echo "Tutto spiegato passo passo in ${BOLD}INSTALLA.md${OFF}"
