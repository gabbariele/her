#!/usr/bin/env bash
# Doppio clic su questo file (macOS) per installare her.
cd "$(dirname "$0")"
./setup.sh
echo
read -n 1 -s -r -p "Premi un tasto per chiudere questa finestra..."
echo
