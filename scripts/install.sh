#!/bin/sh
# Poseidon installer — paste one line, get an agent.
#   curl -fsSL https://raw.githubusercontent.com/ShabariRepo/poseidon/main/scripts/install.sh | sh
set -e
PY="$(command -v python3 || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  echo "Poseidon needs Python 3.10+ — grab it from https://python.org and re-run."; exit 1
fi
DIR="$HOME/.poseidon-app"
[ -d "$DIR/venv" ] || "$PY" -m venv "$DIR/venv"
echo "🔱 installing Poseidon…"
"$DIR/venv/bin/pip" install -q --upgrade pip poseidon-ai
BIN="$HOME/.local/bin"; mkdir -p "$BIN"
ln -sf "$DIR/venv/bin/poseidon" "$BIN/poseidon"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "→ add $BIN to your PATH (or run $BIN/poseidon)";; esac
echo "🔱 Poseidon installed — starting…"
exec "$BIN/poseidon"
