#!/usr/bin/env bash
# Doppio clic su questo file (macOS) per iniziare a registrare una puntata.
# La voce e il personaggio si scelgono in .env e nel preset (vedi INSTALLA.md).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/her ]; then
  echo "Prima devi installare: doppio clic su setup.command"
  read -n 1 -s -r -p "Premi un tasto per chiudere..."
  exit 1
fi
echo "Parti pure quando vuoi. Per chiudere la puntata: Ctrl-C"
echo
.venv/bin/her record --preset "${HER_PRESET:-intervista}"
echo
read -n 1 -s -r -p "Premi un tasto per chiudere questa finestra..."
echo
