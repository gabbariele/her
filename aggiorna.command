#!/usr/bin/env bash
# Doppio clic (macOS) per aggiornare her all'ultima versione.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Prima devi installare: doppio clic su setup.command"
  read -n 1 -s -r -p "Premi un tasto per chiudere..."; exit 1
fi
.venv/bin/python aggiorna.py
echo
read -n 1 -s -r -p "Premi un tasto per chiudere questa finestra..."
echo
