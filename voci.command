#!/usr/bin/env bash
# Doppio clic (macOS): elenca le voci ElevenLabs del tuo account con il loro id.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/her ]; then
  echo "Prima devi installare: doppio clic su setup.command"
  read -n 1 -s -r -p "Premi un tasto per chiudere..."; exit 1
fi
.venv/bin/her voices
echo
echo "Copia l'id della voce che ti piace e incollalo nel file .env, alla riga HER_VOICE_ID="
echo
read -n 1 -s -r -p "Premi un tasto per chiudere questa finestra..."
echo
