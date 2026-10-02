#!/bin/bash
# model-gate.sh -- the shell door to the model gate (plugins/kipi-core/voiceloop/model_gate.py).
#
#   model-gate.sh --job <name> [--item <pr-123|ASK-45>] -- claude -p ...
#
# why: every cap the fleet had was local to one path, so a caller that reached
# the model another way passed all of them (RCA token-waste-loops, 2026-10-02).
# A shell caller puts this in front of its command; the gate decides, and on a
# refusal the command never runs.
#
# Contract:
#   * admitted: the command runs, its stdout is passed through unchanged, its
#     exit code is returned, and its cost row is appended to the usage ledger
#     (measured when the caller asked for --output-format json).
#   * refused: prints MODEL_GATE_REFUSED on stderr and exits 75 (EX_TEMPFAIL).
#     Not 0: a caller that reads exit 0 + empty stdout as "no findings" would
#     turn a refusal into an approval (PRD review finding 4). The alert is the
#     gate's job, filed once per job+limit+day.
#   * the gate cannot run at all (module missing): fail CLOSED. The command does
#     not run, MODEL_GATE_ERROR on stderr, one alert per day, exit 75.
#   * --item names the work item WITH its repo or tracker (owner/repo#123,
#     ASK-45): the round cap is keyed on it, and a bare number collides.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="${KIPI_MODEL_GATE_PKG:-$HERE/../../../plugins/kipi-core}"
job="" item=""
while [ $# -gt 0 ]; do
  case "$1" in
    # A flag with no value: `shift 2` on one argument fails and the loop spun
    # forever (PR #503 review). Refuse instead.
    --job|--item) [ $# -ge 2 ] || { echo "model-gate.sh: $1 needs a value" >&2; exit 2; }
      if [ "$1" = --job ]; then job="$2"; else item="$2"; fi; shift 2 ;;
    --) shift; break ;;
    *) echo "model-gate.sh: unknown argument $1 (usage: --job J [--item K] -- cmd...)" >&2; exit 2 ;;
  esac
done
if [ -z "$job" ] || [ $# -eq 0 ]; then
  echo "model-gate.sh: usage: --job J [--item K] -- cmd..." >&2
  exit 2
fi

# Run FROM the package dir: `python3 -m` puts the cwd first on sys.path, so a
# caller sitting in some other checkout's plugins/kipi-core would otherwise get
# THAT copy of the gate (seen in this door's own test, 2026-10-02).
gate() { ( cd "$PKG" 2>/dev/null && PYTHONPATH="$PKG" python3 -m voiceloop.model_gate "$@" ) || return $?; }

if [ -n "$item" ]; then decision="$(gate check --job "$job" --item "$item")"; rc=$?
else decision="$(gate check --job "$job")"; rc=$?; fi

if [ "$rc" -eq 3 ]; then
  echo "MODEL_GATE_REFUSED job=$job item=$item $decision" >&2
  exit 75
fi
if [ "$rc" -ne 0 ]; then
  echo "MODEL_GATE_ERROR job=$job: the gate did not run (exit $rc); refusing the call" >&2
  marker="${HOME}/.config/kipi/.model-gate-door-error-$(date -u +%Y-%m-%d)"
  if [ -n "${KIPI_MODEL_GATE_LEDGER:-}" ]; then marker="$(dirname "$KIPI_MODEL_GATE_LEDGER")/.model-gate-door-error-$(date -u +%Y-%m-%d)"; fi
  mkdir -p "$(dirname "$marker")" 2>/dev/null
  if ( set -o noclobber; : > "$marker" ) 2>/dev/null; then
    notify="${KIPI_MODEL_GATE_NOTIFY:-bash $HERE/slack-notify.sh}"
    $notify "model-gate.sh: the gate did not run (exit $rc) for job=$job; calls are refused" >/dev/null 2>&1
  fi
  exit 75
fi

out="$(mktemp "${TMPDIR:-/tmp}/model-gate.XXXXXX")"
"$@" > "$out"
status=$?
cat "$out"
gate record --job "$job" --stdout-file "$out" --exit "$status" >/dev/null 2>&1
rm -f "$out"
exit "$status"
