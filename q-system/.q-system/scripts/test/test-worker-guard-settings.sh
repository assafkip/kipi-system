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
#   F. tree whose settings run every guard: no --settings (no double-firing).
#   F2. tree whose settings predate guards: --settings carries exactly those (ASK-3957).
#   G. the set cannot be built: no agent is started, the reason is said, and
#      nothing is charged to the issue (fail closed, not "run unguarded").
#   H. census by code: every agent-session call site in the worker passes it.
set -uo pipefail
# NOT A BILLING TEST (ASK-4311). This suite stubs `claude` on PATH and tests its
# own subject, so its runs take the plan path: KIPI_FLEET_API_KEYS=0 makes the
# worker, the reviewer and the dispatcher call `env -u ANTHROPIC_API_KEY claude`
# exactly as before the fleet door. The door has its own suites
# (test_fleet_api_credit.py, test-dispatch-api-key-gate.sh, test-worker-usage-brake.sh).
export KIPI_FLEET_API_KEYS=0

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
# ASK-4747/4756: the machine's plugins, shaped like the real install records
# (installed_plugins.json version 2) and a skills-dir plugin (.claude-plugin/plugin.json
# under ~/.claude/skills), the two sources `claude plugin list` read on 2026-11-12.
# One fleet plugin the worker row keeps, two it does not.
mkdir -p "$WORK/home/.claude/plugins" "$WORK/home/.claude/skills/last30days/.claude-plugin"
printf '%s\n' '{"version":2,"plugins":{"kipi-core@kipi":[{"scope":"user","version":"1"}],"posthog@claude-plugins-official":[{"scope":"user","version":"1"}]}}' > "$WORK/home/.claude/plugins/installed_plugins.json"
printf '%s\n' '{"name":"last30days","version":"2.9.5"}' > "$WORK/home/.claude/skills/last30days/.claude-plugin/plugin.json"

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
# ASK-4675: a real run writes its transcript under $HOME/.claude/projects/<cwd>/<session>.jsonl.
# NO_TX=1 is the run that wrote none (the negative case).
if [ -z "${NO_TX:-}" ]; then
  sid=""; prev=""
  for a in "$@"; do [ "$prev" = "--session-id" ] && sid="$a"; prev="$a"; done
  if [ -n "$sid" ]; then
    mkdir -p "$HOME/.claude/projects/-stub"
    printf '%s\n' '{"type":"assistant","message":{"id":"m1","model":"x","usage":{"input_tokens":3,"output_tokens":700,"cache_read_input_tokens":10,"cache_creation_input_tokens":5}}}' > "$HOME/.claude/projects/-stub/$sid.jsonl"
  fi
fi
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

# run_case <name> <settings:yes|no|parity> [GUARD_FAIL]
run_case() {
  local name="$1" withset="$2" gfail="${3:-}" tgt="$WORK/target-$1"
  mkrepo "$tgt" "target$1"
  if [ "$withset" = "yes" ]; then
    mkdir -p "$tgt/.claude"
    printf '{"hooks":{}}\n' > "$tgt/.claude/settings.json"
    G -C "$tgt" add .claude/settings.json && G -C "$tgt" commit -qm settings && git -C "$tgt" push -q origin main
  elif [ "$withset" = "parity" ]; then
    # Settings that run every guard the skeleton set carries, each script present:
    # the set itself, written back as $CLAUDE_PROJECT_DIR hooks (ASK-3957).
    "$REAL_PY" - "$ROOT" "$tgt" <<'PY' || fail "could not build the parity fixture"
import json, os, re, subprocess, sys
root, tgt = sys.argv[1], sys.argv[2]
full = subprocess.run([sys.executable, root + "/q-system/.q-system/scripts/skeleton-guard-settings.py"],
                      capture_output=True, text=True, check=True).stdout
txt = json.dumps({"hooks": json.loads(full)["hooks"]}).replace(root + "/", "$CLAUDE_PROJECT_DIR/")
os.makedirs(tgt + "/.claude", exist_ok=True)
open(tgt + "/.claude/settings.json", "w").write(txt)
for rel in set(re.findall(r"\$CLAUDE_PROJECT_DIR/([\w./-]+\.(?:py|sh))", txt)):
    os.makedirs(os.path.dirname(os.path.join(tgt, rel)), exist_ok=True)
    open(os.path.join(tgt, rel), "w").write("# fixture\n")
PY
    G -C "$tgt" add -A && G -C "$tgt" commit -qm parity && git -C "$tgt" push -q origin main
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

# --- E1. the launch loads only what the allowlist's worker row names (ASK-4747/4756) ---
# Read from fleet-load-allowlist.json, never restated here: every plugin the fixture
# machine knows whose name the row does not list must be off, and the MCP config must
# be strict and hold exactly the row's servers (none). A launch without
# --strict-mcp-config loads every MCP server and account connector: 617 deferred tool
# names measured on 2026-11-12, against 13 with it.
"$REAL_PY" - "$WORK/argv-E" "$ROOT/q-system/.q-system/fleet-load-allowlist.json" <<'PY' || fail "E1: see above. Output: $(tail -8 "$WORK/run-E.out")"
import json, sys
argv = [a.decode() for a in open(sys.argv[1], "rb").read().split(b"\0")[:-1]]
row = json.load(open(sys.argv[2]))["jobs"]["worker"]
known = {"kipi-core@kipi", "posthog@claude-plugins-official", "last30days@skills-dir"}
if "--strict-mcp-config" not in argv:
    sys.exit("E1: no --strict-mcp-config: the run loads every MCP server and account connector")
if "--mcp-config" not in argv:
    sys.exit("E1: --strict-mcp-config with no --mcp-config")
servers = json.loads(argv[argv.index("--mcp-config") + 1]).get("mcpServers")
if not isinstance(servers, dict) or sorted(servers) != sorted(row["mcp_servers"]):
    sys.exit("E1: MCP servers %r, the worker row names %r" % (servers, row["mcp_servers"]))
enabled = json.loads(argv[argv.index("--settings") + 1]).get("enabledPlugins", {})
loaded = sorted(i for i in known if enabled.get(i, True) is not False)
stray = [i for i in loaded if i.split("@")[0] not in row["plugins"]]
if stray:
    sys.exit("E1: plugins the worker row does not list still load: %r" % stray)
if "kipi-core@kipi" not in loaded:
    sys.exit("E1: the launch turned off kipi-core, which the worker row keeps")
print("  argv: --strict-mcp-config --mcp-config %s, loads %r" % (json.dumps(servers), loaded))
PY
ok "E1: the worker launch loads only the allowlist's plugins and no MCP server"

# --- E2. the worker passes --session-id and records the run's tokens (ASK-4675) ---
ROWS="$WORK/home/.local/state/kipi/run-tokens.jsonl"
tr '\0' '\n' < "$WORK/argv-E" | grep -x -- '--session-id' >/dev/null || fail "E2: the worker started claude with no --session-id, so no transcript can be tied to the run"
[ "$(cat "$WORK/rc-E")" = "0" ] || fail "E2: the run did not exit 0"
[ -f "$ROWS" ] || fail "E2: the run finished but wrote no run-tokens row. Output: $(tail -6 "$WORK/run-E.out")"
"$REAL_PY" - "$ROWS" <<'PY' || fail "E2: the row is wrong"
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
r = rows[-1]
if len(rows) != 1 or r["ticket"] != "ASK-GGG" or r["output_tokens"] != 700 or r["requests"] != 1 or not r["session"]:
    sys.exit("E2: unexpected row %r" % (r,))
PY
ok "E2: --session-id is passed and one run-tokens row (ticket, 700 output tokens) is appended"

# --- E3. a run whose transcript cannot be read still succeeds -------------------
rm -f "$ROWS"
NO_TX=1 run_case E3 no
[ "$(cat "$WORK/rc-E3")" = "0" ] || fail "E3: a missing transcript failed the worker run. Output: $(tail -8 "$WORK/run-E3.out")"
grep -q 'ok ASK-GGG' "$WORK/run-E3.out" || fail "E3: the run did not complete. Output: $(tail -8 "$WORK/run-E3.out")"
[ ! -s "$ROWS" ] || fail "E3: a row was written for a run with no transcript"
ok "E3: no transcript means no row and an unchanged run"

# --- F. project settings that run every guard: nothing supplied ---------------
run_case F parity
[ -f "$WORK/argv-F" ] || fail "F: the agent was never started. Output:
$(tail -12 "$WORK/run-F.out")"
# NOT grep -q (ASK-3957): under pipefail, grep -q exits at the first match, tr dies
# of SIGPIPE on the multi-KB prompt, the pipeline returns 141 and `&& fail` never
# ran. The original check could not fail; a mutant that double-supplied passed it.
# ASK-4747: --settings now always carries the plugin trim, so the double-firing
# property is "no HOOKS supplied", which is what fires twice, not "no --settings".
"$REAL_PY" - "$WORK/argv-F" <<'PY' || fail "F: a tree whose settings already run every guard was also given guard hooks in --settings; every guard would fire twice"
import json, sys
argv = [a.decode() for a in open(sys.argv[1], "rb").read().split(b"\0")[:-1]]
if "--settings" in argv and json.loads(argv[argv.index("--settings") + 1]).get("hooks"):
    sys.exit(1)
PY
ok "F: a tree whose settings run every guard gets no guard hooks in --settings (no double-firing)"

# --- F2. project settings that predate the guards: the missing ones supplied --
# ASK-3957. Before it, F asserted that THIS tree (settings that run no guard at all)
# gets nothing, which is the gap: every client tree cut from origin lacked
# agent-brief-one-job-guard.py on 2026-11-08 and ran without it.
run_case F2 yes
[ -f "$WORK/argv-F2" ] || fail "F2: the agent was never started. Output:
$(tail -12 "$WORK/run-F2.out")"
"$REAL_PY" - "$WORK/argv-F2" "$ROOT" <<'PY' || fail "F2: see above. Output: $(tail -8 "$WORK/run-F2.out")"
import json, sys
argv = [a.decode() for a in open(sys.argv[1], "rb").read().split(b"\0")[:-1]]
root = sys.argv[2]
if "--settings" not in argv:
    sys.exit("F2: a tree whose settings run no guard was started with NO --settings: the guards never run")
s = json.loads(argv[argv.index("--settings") + 1])
cmds = [h["command"] for arr in s["hooks"].values() for m in arr for h in m["hooks"]]
if not any("agent-brief-one-job-guard.py" in c for c in cmds):
    sys.exit("F2: the overlay does not carry agent-brief-one-job-guard.py")
if not all(root + "/" in c for c in cmds):
    sys.exit("F2: a supplied hook does not run from this skeleton")
if any("stop-logger.sh" in c for c in cmds):
    sys.exit("F2: an excluded hook reached the agent")
print("  argv: -p <prompt> --settings <%d hook commands the tree lacks>" % len(cmds))
PY
grep -q 'lacks skeleton guard hooks' "$WORK/run-F2.out" || fail "F2: the run does not say it supplied guards. Output:
$(tail -8 "$WORK/run-F2.out")"
ok "F2: a tree whose settings predate the guards gets exactly the ones it lacks"

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
# `$FLEET_CLAUDE -p` is the main run since ASK-4311: the fleet door execs
# `claude -p`, so it is a launch like any other.
LAUNCHERS='claude -p|\$\{?FLEET_CLAUDE\}? -p|\$\{?SECOND_RUNNER_FALLBACK|\$\{?REVIEWER_CMD'
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
