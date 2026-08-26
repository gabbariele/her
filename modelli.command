#!/usr/bin/env bash
# Doppio clic (macOS): elenca i modelli che la tua chiave può usare.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/her ]; then
  echo "Prima devi installare: doppio clic su setup.command"
  read -n 1 -s -r -p "Premi un tasto per chiudere..."; exit 1
fi
.venv/bin/her models
echo
echo "Per usarne uno diverso, incolla il nome nel preset (cartella presets), alla riga model:"
echo
read -n 1 -s -r -p "Premi un tasto per chiudere questa finestra..."
echo
