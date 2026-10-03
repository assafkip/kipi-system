#!/bin/bash
# model-gate.sh -- the shell door to the model gate (plugins/kipi-core/voiceloop/model_gate.py).
#
#   model-gate.sh --job <name> [--item <id>] -- claude -p ...
#
# why: every cap the fleet had was local to one path, so a caller that reached
# the model another way passed all of them. A shell caller puts this in front
# of its command; model_gate.check() decides.
#
#   admitted: the command runs (exec), its exit code is the door's.
#   refused:  MODEL_GATE_REFUSED on stderr, exit 75. Not 0: a caller reading
#             exit 0 + empty stdout as "no findings" would turn a refusal into
#             an approval.
#   the gate itself did not run (python or module missing): same policy as a
#             broken ledger, admit in report mode, refuse (exit 75) otherwise.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="${KIPI_MODEL_GATE_PKG:-$HERE/../../../plugins/kipi-core}"
job="" item=""
while [ $# -gt 0 ]; do
  case "$1" in
    --job|--item) [ $# -ge 2 ] || { echo "model-gate.sh: $1 needs a value" >&2; exit 2; }
      if [ "$1" = --job ]; then job="$2"; else item="$2"; fi; shift 2 ;;
    --) shift; break ;;
    *) echo "model-gate.sh: usage: --job J [--item I] -- cmd..." >&2; exit 2 ;;
  esac
done
[ -n "$job" ] && [ $# -gt 0 ] || { echo "model-gate.sh: usage: --job J [--item I] -- cmd..." >&2; exit 2; }

# Run FROM the package dir so `python3 -m` loads THIS checkout's gate, not one
# that happens to sit first on the caller's sys.path.
( cd "$PKG" && python3 -m voiceloop.model_gate check --job "$job" ${item:+--item "$item"} ) >/dev/null
rc=$?
[ "$rc" -eq 0 ] && exec "$@"
if [ "$rc" -ne 3 ]; then
  mode="${KIPI_MODEL_GATE_MODE:-}"
  [ -z "$mode" ] && [[ "$(date -u +%Y-%m-%d)" < "2026-10-10" ]] && mode=report
  echo "model-gate.sh: the gate did not run (exit $rc); mode ${mode:-enforce}" >&2
  [ "$mode" = report ] && exec "$@"
fi
echo "MODEL_GATE_REFUSED job=$job item=$item" >&2
exit 75
