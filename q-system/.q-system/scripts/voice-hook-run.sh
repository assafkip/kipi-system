#!/bin/bash
# The ONE launcher for every voice hook (ASK-4969 parts 1 and 2).
#   voice-hook-run.sh [--timeout SECONDS] [--stop-hook] <script> [script args...]
#
# why this file exists: the voice hooks ran `python3` off whatever PATH the harness had, so
# two hooks could run on two interpreters, and each hook carried its own copy of the
# fail-closed shell. The interpreter is resolved HERE, once, and exported as
# KIPI_VOICE_PYTHON so voice_full_gate.default_python() and every child agree.
#
# Resolution order, no fallback past a bad pin (a fallback is how two interpreters return):
#   1. $KIPI_VOICE_PYTHON            2. first line of ~/.config/kipi/voice-python
#   3. the first executable of /opt/homebrew/bin/python3, /usr/local/bin/python3, /usr/bin/python3
# An interpreter that is not executable or older than 3.9 is a fault: exit 2.
#
# Exit contract: 2 blocks, anything else is a non-blocking error to the harness, so every
# fault in here is 2 (voice_hook_run.py holds the rest of the contract). The one exception
# is a Stop hook on its second pass (stop_hook_active), where a fault is 0 so the turn can end.
fault() { echo "voice-hook-run: $1" >&2; exit "${2:-2}"; }

payload=$(cat)
hold=2
case " $* " in
  *" --stop-hook "*)
    case "$payload" in *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) hold=0 ;; esac ;;
esac

PY="${KIPI_VOICE_PYTHON:-}"
if [ -z "$PY" ] && [ -f "$HOME/.config/kipi/voice-python" ]; then
  PY=$(head -n1 "$HOME/.config/kipi/voice-python")
fi
if [ -z "$PY" ]; then
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$c" ]; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] && [ -x "$PY" ] || fault "no usable voice interpreter (KIPI_VOICE_PYTHON, ~/.config/kipi/voice-python, or a system python3); the gate cannot run" "$hold"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null \
  || fault "interpreter $PY is older than 3.9 or does not run; the gate cannot run" "$hold"
export KIPI_VOICE_PYTHON="$PY"

RUNNER="$(cd "$(dirname "$0")" && pwd)/voice_hook_run.py"
[ -f "$RUNNER" ] || fault "$RUNNER missing: the gate cannot run. Restore the skeleton scripts" "$hold"
printf '%s' "$payload" | exec "$PY" "$RUNNER" "$@"
