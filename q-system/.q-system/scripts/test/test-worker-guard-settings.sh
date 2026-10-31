#!/usr/bin/env bash
# Reproducer + acceptance for ASK-3529, the worker half: an issue tree with no
# .claude/settings.json ran `claude -p` with none of the skeleton's guards.
#
# Measured 2026-10-31 in a scratch repo with a counter hook: `claude -p
# --settings <x>` ADDS to project settings (both sets fired), byte-identical
# commands dedupe, and the rewritten skeleton commands never equal an
# instance's own `$CLAUDE_PROJECT_DIR/...` commands. So supplying the set to a
# tree that HAS settings fires every guard twice, and the set is supplied only
# when the tree has none.
#
# Through the REAL worker, git real, gh/claude/python3 stubbed (the harness
# shape of test-worker-default-branch.sh):
#   E. tree without settings: the agent is started with --settings, a JSON set
#      whose hooks run from this skeleton and carry no excluded hook.
#   F. tree WITH settings: no --settings (no double-firing).
#   G. the set cannot be built: no agent is started, the reason is said, and
#      nothing is charged to the issue (fail closed, not "run unguarded").
#   H. census by code: every agent-session call site in the worker passes it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
GEN="$ROOT/q-system/.q-system/scripts/skeleton-guard-settings.py"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ] || fail "linear-worker.sh does not exist at $WORKER"
[ -f "$GEN" ] || fail "THE DEFECT: no skeleton-guard-settings.py, so a tree without settings runs the agent unguarded"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID KIPI_TARGET_REPO KIPI_DISPATCH_TARGETS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

mkrepo() {
  git init -q --bare "$WORK/origin-$2.git"
  git -C "$WORK/origin-$2.git" symbolic-ref HEAD refs/heads/main
  git init -q "$1"
  git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
  G -C "$1" commit -q --allow-empty -m c1
  git -C "$1" branch -M main
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  git -C "$1" push -q -u origin main
  git -C "$1" remote set-head origin main
}
mkrepo "$WORK/skel" homerepo

GH_LOG="$WORK/gh.txt"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
exit 0
EOF
chmod +x "$STUB/gh"
# The agent stub records its exact argv, NUL-separated so a JSON argument with
# spaces and quotes comes back byte-for-byte, then makes one commit.
cat > "$STUB/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s\0' "$@" > "$CLAUDE_ARGV"
git -c user.email=t@t.t -c user.name=t commit -q --allow-empty -m "agent work"
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/reviewer-noop"; chmod +x "$STUB/reviewer-noop"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' '{"ready":[{"id":"ASK-GGG","title":"t","project":"targetproj"}],"total_open":1}'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
  *skeleton-guard-settings.py) [ -n "\${GUARD_FAIL:-}" ] && { echo "forced failure" >&2; exit 1; } ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$STUB/python3"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real remotes are the subject"

# run_case <name> <settings:yes|no> [GUARD_FAIL]
run_case() {
  local name="$1" withset="$2" gfail="${3:-}" tgt="$WORK/target-$1"
  mkrepo "$tgt" "target$1"
  if [ "$withset" = "yes" ]; then
    mkdir -p "$tgt/.claude"
    printf '{"hooks":{}}\n' > "$tgt/.claude/settings.json"
    G -C "$tgt" add .claude/settings.json && G -C "$tgt" commit -qm settings && git -C "$tgt" push -q origin main
  fi
  cat > "$WORK/skel/instance-registry.json" <<JSON
{"instances":[{"name":"targetproj","path":"$tgt","has_git":true,
  "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/target$1.git"}}]}
JSON
  : > "$GH_LOG"; rm -f "$WORK/argv-$1"
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-$1" \
       KIPI_NOTIFY="/usr/bin/true" KIPI_PR_REVIEWER="$STUB/reviewer-noop" \
       KIPI_LINEAR_PROJECT="targetproj" CLAUDE_ARGV="$WORK/argv-$1" GUARD_FAIL="$gfail" \
       bash "$WORKER" --apply --repo "$tgt" --issue ASK-GGG --limit 1 \
  ) >"$WORK/run-$1.out" 2>&1
  echo $? > "$WORK/rc-$1"
}

# --- E. no project settings: the skeleton set is supplied --------------------
run_case E no
[ -f "$WORK/argv-E" ] || fail "E: the agent was never started. Output:
$(tail -12 "$WORK/run-E.out")"
"$REAL_PY" - "$WORK/argv-E" "$ROOT" <<'PY' || fail "E: see above. Output: $(tail -8 "$WORK/run-E.out")"
import json, re, sys
argv = open(sys.argv[1], "rb").read().split(b"\0")[:-1]
argv = [a.decode() for a in argv]; root = sys.argv[2]
if argv[:1] != ["-p"]:
    sys.exit("E: argv does not start with -p: %r" % argv[:2])
if "--settings" not in argv:
    sys.exit("E: a tree without .claude/settings.json was started with NO --settings: %r" % ([argv[0]] + argv[2:],))
s = json.loads(argv[argv.index("--settings") + 1])
cmds = [h["command"] for arr in s["hooks"].values() for m in arr for h in m["hooks"]]
if not cmds or not all(root + "/" in c for c in cmds):
    sys.exit("E: the supplied hooks do not run from this skeleton (%d commands)" % len(cmds))
if any("stop-logger.sh" in c or "auto-update.sh" in c for c in cmds):
    sys.exit("E: an excluded hook reached the agent")
if not s.get("permissions", {}).get("deny"):
    sys.exit("E: the template deny rules were not supplied")
print("  argv: -p <prompt> --settings <%d hook commands, %d deny rules>" % (len(cmds), len(s["permissions"]["deny"])))
PY
ok "E: a tree without project settings starts the agent with the skeleton's guard set"

# --- F. project settings present: nothing supplied ---------------------------
run_case F yes
[ -f "$WORK/argv-F" ] || fail "F: the agent was never started. Output:
$(tail -12 "$WORK/run-F.out")"
tr '\0' '\n' < "$WORK/argv-F" | grep -qx -- '--settings' \
  && fail "F: a tree WITH .claude/settings.json was also given --settings; every guard would fire twice"
ok "F: a tree with project settings gets no --settings (no double-firing)"

# --- G. the set cannot be built: fail closed --------------------------------
run_case G no 1
[ -f "$WORK/argv-G" ] && fail "G: the agent was started although the guard set could not be built"
grep -q 'guard set' "$WORK/run-G.out" || fail "G: the refusal does not say why. Output:
$(tail -8 "$WORK/run-G.out")"
grep -q 'not counted against the issue' "$WORK/run-G.out" || fail "G: the refusal was charged to the issue. Output:
$(tail -8 "$WORK/run-G.out")"
ok "G: no guard set means no agent, a stated reason, and no attempt charged"

# --- H. census by code: every agent launch carries the set, or is a named gap -
# Enumerated from the source, never from this comment. Every non-comment line
# naming an agent launcher (a literal `claude -p`, the stand-in variable, the
# reviewer variable) is classified: a definition or a presence test is skipped,
# and every LAUNCH must pass --settings unless KNOWN names it with a ticket.
# PR #583 review (minor): the first cut matched only `run_bounded` lines, so a
# launch shaped like the reviewer call was invisible and the census passed.
# Residual, said out loud: a launcher behind a brand-new variable name is still
# invisible until its name is added to LAUNCHERS.
LAUNCHERS='claude -p|\$\{?SECOND_RUNNER_FALLBACK|\$\{?REVIEWER_CMD'
KNOWN_REVIEWER='$REVIEWER_CMD "$PR_NUM"'   # pr-review-agent.sh runs its own review tree: ASK-3571
# A definition is a line that IS an assignment of a quoted string (NAME="...").
# Anchored, so an env-prefixed launch (NAME=value $LAUNCHER ...) still counts.
DEF_RX='^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*="'
LAUNCHES=""; KNOWN_HIT=0; N_LAUNCH=0
while IFS= read -r ln; do
  code="${ln#*:}"
  [[ $code =~ $DEF_RX ]] && continue                                # a definition, not a launch
  case "$code" in *'[ -n "$SECOND_RUNNER_FALLBACK" ]'*) continue ;; esac   # a presence test
  N_LAUNCH=$((N_LAUNCH + 1))
  case "$code" in *"$KNOWN_REVIEWER"*) KNOWN_HIT=1; continue ;; esac
  printf '%s' "$code" | grep -q -- '--settings' || LAUNCHES="$LAUNCHES
$ln"
done < <(grep -nE "$LAUNCHERS" "$WORKER" | grep -vE '^[0-9]+:[[:space:]]*#')
[ "$N_LAUNCH" -ge 3 ] || fail "H: found $N_LAUNCH agent launches, expected at least 3 (Sana, the stand-in, the reviewer); the census pattern is stale"
[ "$KNOWN_HIT" = "1" ] || fail "H: the reviewer launch tracked as ASK-3571 is gone or reshaped; re-check whether it now needs the set"
[ -z "$LAUNCHES" ] || fail "H: an agent launch starts without the guard set and is not a named gap:$LAUNCHES"
ok "H: $N_LAUNCH agent launches found; each passes the guard set, except the reviewer (ASK-3571)"

echo "PASS ($PASS checks) test-worker-guard-settings.sh"
