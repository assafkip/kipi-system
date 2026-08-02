#!/usr/bin/env bash
# Mutation harness for linear-relay-core.py. Refuses non-applying mutants.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/../linear-relay-core.py"
SUITE="$DIR/test-linear-relay-core.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

run_mutant() {
  local name="$1" expr="$2" guarantee="$3"
  local mutant="$WORK/$name.py"
  sed "$expr" "$SRC" > "$mutant"
  if cmp -s "$SRC" "$mutant"; then
    echo "[BROKEN] $name: mutation did not apply"; return 2
  fi
  local out rc
  out="$(KIPI_NOTIFY=/usr/bin/true KIPI_RELAY_MODULE_UNDER_TEST="$(basename "$mutant")" \
         PYTHONPATH="$WORK" python3 - "$mutant" "$SUITE" <<'PY' 2>&1
import subprocess, sys, os, shutil
mutant, suite = sys.argv[1], sys.argv[2]
# Drive the suite against the mutant by placing it where the loader looks.
scripts = os.path.dirname(os.path.dirname(suite))
tmpname = os.path.join(scripts, "__mutant_relay_core.py")
shutil.copy(mutant, tmpname)
try:
    env = dict(os.environ, KIPI_RELAY_MODULE_UNDER_TEST="__mutant_relay_core.py")
    r = subprocess.run([sys.executable, suite], env=env, capture_output=True, text=True)
    print(r.stdout + r.stderr)
    sys.exit(r.returncode)
finally:
    os.remove(tmpname)
PY
)"
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "[CAUGHT] $name -- suite went RED as it must ($guarantee)"
    echo "$out" | grep '^\[FAIL\]' | sed 's/^/           /'
    return 0
  fi
  echo "[ESCAPED] $name -- suite stayed GREEN. NOTHING CHECKS: $guarantee"
  return 1
}

echo "=== mutation testing linear-relay-core.py ==="
fails=0

# The subtle one. Re-serializing the body is the mistake a reasonable person makes,
# and it silently breaks every downstream signature check.
run_mutant "body-reserialized" \
  's|^        "raw": raw_body.decode("latin-1"),$|        "raw": json.dumps(payload, sort_keys=True),|' \
  "the raw body must survive the queue byte-exact or the Mac rejects every delegation" || fails=$((fails+1))

run_mutant "no-signature-check" \
  's|^    ok, reason = verify_fn(raw_body, signature, secret, now_ms=int(now \* 1000))$|    ok, reason = (True, "MUTANT")|' \
  "a forged event must not reach storage" || fails=$((fails+1))

run_mutant "no-dedupe" \
  's|^    if store.has(key):$|    if False:|' \
  "a Linear retry must not become a second run of the same issue" || fails=$((fails+1))

run_mutant "no-queue-bound" \
  's|^    if store.count() >= MAX_QUEUE_DEPTH:$|    if False:|' \
  "an unbounded queue behind a public URL must be impossible" || fails=$((fails+1))

run_mutant "overflow-evicts-oldest" \
  's|^        return 503, f"queue full ({store.count()}/{MAX_QUEUE_DEPTH}) -- refusing, not dropping"$|        store.delete(store.keys()[0])|' \
  "overflow must refuse, never silently evict a real delegation" || fails=$((fails+1))

run_mutant "no-expiry" \
  's|^        if now - item.get("received_at", 0) > max_age:$|        if False:|' \
  "a day-old delegation must expire rather than fire" || fails=$((fails+1))

run_mutant "drain-removes" \
  's|^    fresh.sort(key=lambda e: e\["received_at"\])   # oldest first; delegation order matters$|    [store.delete(e["key"]) for e in fresh]; fresh.sort(key=lambda e: e["received_at"])|' \
  "drain must not remove; only ack does, or a crash mid-run loses the event" || fails=$((fails+1))

echo "==============================================="
[ $fails -eq 0 ] && echo "all mutants caught -- the relay suite has teeth" \
                 || echo "$fails mutant(s) escaped or broken"
exit $fails
