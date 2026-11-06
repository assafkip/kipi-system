#!/bin/bash
# A target whose OWN pre-commit gate is red must be refused BEFORE any write,
# with the gate named (ASK-3621).
#
# THE SCAR (2026-10-31). The consulting root's `linear-identity` gate went red
# under launchd's empty env. The updater had already rsynced, the commit was
# refused, the unwind ran, and the run ended "NOT UPDATED: ASK_AI_consultant" with
# only "config sync did not reach a complete committed state" to go on. The same
# shape (a gate only that checkout runs, found after the write) hit it on
# 2026-09-05, 09-06, 09-07.
#
# Cases (B and the "proceeds once quiet" half of E are the negative self-tests
# that prove the checks can fail on a good input):
#   A  red gate            -> exit 1, gate NAMED, instance HEAD and tree unchanged
#   B  green gate          -> no gate ABORT (the check does not refuse everything)
#   C  gate needs the Sana identity, launchd-like env (env -i), token file
#      present           -> passes: the updater declares the identity itself
#   D  same, token file absent -> ABORT naming the gate
#   E  busy guard: gives up while a matching process runs, proceeds once quiet
#   G  fleet run: red target skipped UNWRITTEN, the other target still runs
#   F  output/ stays instance-owned (consulting-72: never rsync --delete it)
#
# ONLY --dry-run is invoked, against throwaway repos; nothing touches a live path.
set -uo pipefail
REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
SLEEPER=""
trap '[ -n "$SLEEPER" ] && kill "$SLEEPER" 2>/dev/null; rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0
g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false -c init.defaultBranch=main "$@"; }
has() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
ok()  { echo "  ok: $1"; }
bad() { echo "  FAIL: $1"; FAILURES=$((FAILURES + 1)); }

# $1 root, $2 = shell body of the instance's lefthook gate named "probe-gate"
build() {
  local root="$1" body="$2" skel="$1/skeleton"
  mkdir -p "$skel"
  cp -R "$REAL/q-system" "$skel/q-system"
  cp "$REAL"/*.py "$REAL"/*.sh "$skel/" 2>/dev/null
  cp "$REAL"/*.json "$REAL"/*.yml "$skel/" 2>/dev/null
  cp -R "$REAL/plugins" "$skel/plugins" 2>/dev/null
  chmod +x "$skel/kipi-update.sh"
  g init -q "$skel" && g -C "$skel" add -A && g -C "$skel" commit -qm init
  mkdir -p "$root/inst/q-system"; echo i > "$root/inst/q-system/marker"
  printf 'pre-commit:\n  commands:\n    probe-gate:\n      run: |\n        %s\n' "$body" > "$root/inst/lefthook.yml"
  g init -q "$root/inst" && g -C "$root/inst" add -A && g -C "$root/inst" commit -qm init
  printf '{"skeleton":{"path":"%s"},"instances":[{"name":"inst","path":"%s","subtree_prefix":"q-system","instance_q_dir":null,"type":"subtree","has_git":true}]}' \
    "$skel" "$root/inst" > "$skel/instance-registry.json"
}

run() { # $1 root; remaining = env(1) prefix words
  local root="$1"; shift
  ( cd "$root/skeleton" && "$@" bash ./kipi-update.sh --dry-run --only inst 2>&1 ); echo "RC=$?"
}

echo "A: red gate"
R="$T/a"; mkdir -p "$R"; build "$R" "echo boom; exit 1"
before="$(g -C "$R/inst" rev-parse HEAD)$(g -C "$R/inst" status --porcelain)"
out="$(run "$R" env HOME="$T/h" PATH="$PATH")"
after="$(g -C "$R/inst" rev-parse HEAD)$(g -C "$R/inst" status --porcelain)"
has "$out" "RC=1" && ok "exit 1" || bad "exit: $out"
has "$out" "probe-gate" && ok "gate named" || bad "gate not named: $out"
[ "$before" = "$after" ] && ok "instance unchanged" || bad "instance changed"

echo "B: green gate (negative self-test)"
R="$T/b"; mkdir -p "$R"; build "$R" "true"
out="$(run "$R" env HOME="$T/h" PATH="$PATH")"
has "$out" "pre-commit gate" && bad "green gate refused: $out" || ok "green gate not refused"

echo "C/D: identity declared by the updater under an empty env"
GATE='test -n "$KIPI_LINEAR_API_KEY"'
R="$T/c"; mkdir -p "$R" "$T/hc/.config/kipi"; build "$R" "$GATE"
echo "sana-token" > "$T/hc/.config/kipi/linear-sana-token"
out="$(run "$R" env -i HOME="$T/hc" PATH="$PATH")"
has "$out" "pre-commit gate" && bad "C: refused despite token: $out" || ok "C: passes with token file"
R="$T/d"; mkdir -p "$R" "$T/hd"; build "$R" "$GATE"
out="$(run "$R" env -i HOME="$T/hd" PATH="$PATH")"
has "$out" "probe-gate" && ok "D: red without token, gate named" || bad "D: not refused: $out"

echo "G: fleet run, one red target, one green"
R="$T/g"; mkdir -p "$R"; build "$R" "exit 1"
mkdir -p "$R/ok/q-system"; echo o > "$R/ok/q-system/marker"
printf 'pre-commit:\n  commands:\n    fine:\n      run: |\n        echo fine\n' > "$R/ok/lefthook.yml"
g init -q "$R/ok" && g -C "$R/ok" add -A && g -C "$R/ok" commit -qm init
python3 - "$R" <<'PY'
import json, sys
r = sys.argv[1]; p = r + "/skeleton/instance-registry.json"
d = json.load(open(p))
d["instances"].append(dict(d["instances"][0], name="ok", path=r + "/ok"))
json.dump(d, open(p, "w"))
PY
before="$(g -C "$R/inst" rev-parse HEAD)$(g -C "$R/inst" status --porcelain)"
out="$( ( cd "$R/skeleton" && env HOME="$T/h" PATH="$PATH" bash ./kipi-update.sh --dry-run 2>&1 ); echo "RC=$?")"
after="$(g -C "$R/inst" rev-parse HEAD)$(g -C "$R/inst" status --porcelain)"
has "$out" "SKIPPED UNWRITTEN" && ok "G: red target skipped, named" || bad "G: not skipped: $out"
has "$out" "--- ok (" && ok "G: the other target still ran" || bad "G: fleet aborted: $out"
has "$out" "ABORT: the target" && bad "G: fleet run aborted on one gate" || ok "G: no fleet-wide abort"
[ "$before" = "$after" ] && ok "G: red target unchanged" || bad "G: red target changed"

echo "E: busy guard matches the job, not text that mentions it"
eval "$(awk '/^busy_processes\(\) \{/,/^}/' "$REAL/kipi-update.sh")"
eval "$(awk '/^wait_for_quiet_target\(\) \{/,/^}/' "$REAL/kipi-update.sh")"
KIPI_BUSY_GUARDS='inst=kipi-busy-job-987\.py|kipi-busy-job-987' KIPI_BUSY_WAIT_SECS=2 KIPI_BUSY_POLL_SECS=1
# DECOY: consulting-72's wait loop. Its command line CONTAINS the job name as text.
bash -c 'until false; do sleep 1; done # kipi-busy-job-987 pipeline.daily' & SLEEPER=$!
sleep 0.5
if wait_for_quiet_target inst >/dev/null; then ok "E: a wait loop that only mentions the job does not block"
else bad "E: decoy blocked the apply"; fi
kill "$SLEEPER" 2>/dev/null; wait "$SLEEPER" 2>/dev/null; SLEEPER=""
# DECOY 2: a teammate's `git commit` whose message names the module (consulting-72).
mkdir -p "$T/bin"; printf '#!/bin/bash\nsleep 60\n' > "$T/bin/git"; chmod +x "$T/bin/git"
"$T/bin/git" commit -m "fix kipi-busy-job-987 pipeline.daily wiring" & SLEEPER=$!
sleep 0.5
if wait_for_quiet_target inst >/dev/null; then ok "E: a git command whose args name the job does not block"
else bad "E: git decoy blocked the apply"; fi
kill "$SLEEPER" 2>/dev/null; wait "$SLEEPER" 2>/dev/null; SLEEPER=""
# REAL, as argv0 (exec -a), and as an interpreter running the script.
bash -c 'exec -a kipi-busy-job-987 sleep 60' & SLEEPER=$!
sleep 0.5
tout="$(wait_for_quiet_target inst)" && bad "E: argv0 job did not block" || ok "E: a process named as the job blocks"
has "$tout" "still running:" && ok "E: timeout names what is running" || bad "E: timeout reason missing: $tout"
kill "$SLEEPER" 2>/dev/null; wait "$SLEEPER" 2>/dev/null; SLEEPER=""
printf 'sleep 60\n' > "$T/kipi-busy-job-987.py"
bash "$T/kipi-busy-job-987.py" & SLEEPER=$!
sleep 0.5
if wait_for_quiet_target inst >/dev/null; then bad "E: interpreter+script job did not block"; else ok "E: interpreter running the script blocks"; fi
kill "$SLEEPER" 2>/dev/null; wait "$SLEEPER" 2>/dev/null; SLEEPER=""
wait_for_quiet_target inst >/dev/null && ok "E: proceeds once quiet" || bad "E: still refusing when quiet"

echo "F: output/ is instance-owned"
awk '/^INSTANCE_OWNED_SUBTREES=\(/,/^\)/' "$REAL/kipi-update.sh" | grep -qx '  output' \
  && ok "output in INSTANCE_OWNED_SUBTREES" || bad "output not instance-owned"

[ "$FAILURES" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED: $FAILURES"; exit 1; }
