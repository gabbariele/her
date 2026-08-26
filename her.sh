#!/usr/bin/env bash
# Scorciatoia: usa her senza dover "attivare" niente.
#   ./her.sh check      ./her.sh voices      ./her.sh record --preset intervista
cd "$(dirname "$0")"
if [ ! -x .venv/bin/her ]; then
  echo "her non risulta installato: lancia prima  ./setup.sh"
  exit 1
fi
exec .venv/bin/her "$@"
