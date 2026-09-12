#!/usr/bin/env bash
# Reproducer + acceptance criterion for ASK-1510: "the worker assumes every
# repo's default branch is main, so a master repo can never be worked".
#
# THE DEFECT: linear-worker.sh cut every issue worktree from a hardcoded
# BASE="origin/main". A repo whose remote default is `master` failed before any
# work happened:
#   fatal: invalid reference: origin/main
#   INFRA: could not create worktree for ASK-1104 (not counted against the issue)
# Measured 2026-09-12 on interview-coach, whose remote carries only `master`.
# The issue was not charged, but every attempt spent a slot of the 10/day
# dispatch budget, so the repo was paused in the registry (PR #341).
#
# WHY THIS DRIVES THE REAL SCRIPT: the claim is about a side effect (does a
# worktree exist, on which commit, and what base does the PR name), so it is
# read back from real git refs. `git` stays REAL; python3's picker heredoc, gh,
# claude and the reviewer are stubbed. HOME, KIPI_SKEL and KIPI_STATE_DIR all
# point inside a temp dir.
#
# The cases, and what each one is able to fail on:
#   1  master remote, origin/HEAD recorded by clone  -> worktree on origin/master
#   2  master remote, NO origin/HEAD (remote add)    -> the ls-remote fallback
#   3  main remote                                   -> no regression
#   4  a remote whose HEAD cannot be resolved        -> INFRA refusal naming the repo
#   5  a master-repo run that commits                -> pushed, PR opened --base master
#   6  interview-coach is dispatch-enabled again, with the pause keys gone
#   7  no executable line of the worker still names origin/main or --base main
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
REGISTRY="$ROOT/instance-registry.json"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ] || fail "linear-worker.sh does not exist at $WORKER"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID KIPI_TARGET_REPO 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

# Never reach the real reviewer (sp-cb48c3c0): its default engine is codex.
KIPI_PR_REVIEWER="$STUB/reviewer-noop"
export KIPI_PR_REVIEWER
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/reviewer-noop"
chmod +x "$STUB/reviewer-noop"

# gh RECORDS its arguments: case 5 asserts the base the PR was opened against.
# Empty output everywhere, so no PR ever "exists" and none is reviewed.
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/gh-calls.txt"
exit 0
EOF
chmod +x "$STUB/gh"

# claude RECORDS the prompt it was handed (arg 2, after -p) and, when asked,
# commits one file so the worker has something to push and open a PR for.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
printf '%s' "\$2" > "$WORK/prompt.txt"
echo dispatched >> "$WORK/worked.txt"
if [ -f "$WORK/commit-on-run" ]; then
  echo change > work.txt
  git add work.txt
  git -c user.email=t@t.t -c user.name=t commit -q -m "ASK-AAA work"
fi
exit 0
EOF
chmod +x "$STUB/claude"

cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$STUB/python3"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real refs are the subject"

# make_origin <name> <default-branch>: a bare remote whose HEAD names <default>,
# with one commit pushed to exactly that branch and nothing else.
make_origin() {
  git init -q --bare "$WORK/$1.git"
  git -C "$WORK/$1.git" symbolic-ref HEAD "refs/heads/$2"
  git init -q "$WORK/$1-seed"
  G -C "$WORK/$1-seed" commit -q --allow-empty -m c1
  git -C "$WORK/$1-seed" branch -M "$2"
  git -C "$WORK/$1-seed" push -q "$WORK/$1.git" "$2"
}

# run_worker <skel> <state>: one real --apply run against <skel>.
run_worker() {
  : > "$WORK/worked.txt"; : > "$WORK/gh-calls.txt"; rm -f "$WORK/prompt.txt"
  ( cd "$1" \
    && HOME="$WORK/home" KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
       KIPI_NOTIFY="$WORK/notify-recorder.sh" \
       bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$2.out" 2>&1
}
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s/pages.txt"\n' "$WORK" > "$WORK/notify-recorder.sh"
chmod +x "$WORK/notify-recorder.sh"

# assert_tree_on <state> <ref> <skel> <label>
assert_tree_on() {
  local tree="$1/worktrees/ask-aaa" want
  [ -d "$tree" ] || fail "$4: no worktree was created. The run said:
      $(grep -E 'INFRA|worktree' "$1.out" | head -3)
      git said: $(grep -E 'fatal' "$1/linear-worker.log" 2>/dev/null | head -2)"
  want="$(git -C "$3" rev-parse "$2")"
  [ "$(git -C "$tree" rev-parse HEAD)" = "$want" ] \
    || fail "$4: the worktree is not on $2 ($want)"
  [ "$(git -C "$tree" rev-parse --abbrev-ref HEAD)" = "sana/ask-aaa" ] \
    || fail "$4: the worktree is not on branch sana/ask-aaa"
}

# --- 1. master remote, origin/HEAD recorded by clone -------------------------
make_origin m1 master
git clone -q "$WORK/m1.git" "$WORK/skel1"
[ "$(git -C "$WORK/skel1" symbolic-ref refs/remotes/origin/HEAD)" = "refs/remotes/origin/master" ] \
  || fail "fixture: the clone did not record origin/HEAD -> master"
git -C "$WORK/skel1" rev-parse -q --verify origin/main >/dev/null \
  && fail "fixture: origin/main exists, so this case could not reproduce the defect"
run_worker "$WORK/skel1" "$WORK/state1"
assert_tree_on "$WORK/state1" origin/master "$WORK/skel1" "master remote (origin/HEAD)"
grep -q "off origin/master" "$WORK/prompt.txt" 2>/dev/null \
  || fail "master remote: the agent's prompt does not name the base it was cut from (origin/master)"
ok "a master remote with origin/HEAD gets a worktree and branch on origin/master"

# --- 2. master remote, no origin/HEAD: the ls-remote fallback ----------------
make_origin m2 master
git init -q "$WORK/skel2"
git -C "$WORK/skel2" remote add origin "$WORK/m2.git"
git -C "$WORK/skel2" fetch -q origin
git -C "$WORK/skel2" checkout -q -b master origin/master
# git 2.48+ records origin/HEAD on every fetch (remote.<name>.followRemoteHEAD
# defaults to "create"), including the worker's own fetch. `never` models the
# older git and the checkout that opted out; an older git ignores the key.
git -C "$WORK/skel2" config remote.origin.followRemoteHEAD never
git -C "$WORK/skel2" remote set-head origin -d >/dev/null 2>&1 || true
git -C "$WORK/skel2" symbolic-ref -q refs/remotes/origin/HEAD >/dev/null \
  && fail "fixture: origin/HEAD exists, so the fallback path would not be exercised"
run_worker "$WORK/skel2" "$WORK/state2"
assert_tree_on "$WORK/state2" origin/master "$WORK/skel2" "master remote (ls-remote fallback)"
ok "a master remote with no origin/HEAD resolves through ls-remote and gets a worktree"

# --- 3. main remote: every other repo in the fleet ---------------------------
make_origin mn main
git clone -q "$WORK/mn.git" "$WORK/skel3"
run_worker "$WORK/skel3" "$WORK/state3"
assert_tree_on "$WORK/state3" origin/main "$WORK/skel3" "main remote (regression)"
ok "a main remote still gets a worktree on origin/main"

# --- 4. an unresolvable default refuses as INFRA and names the repo ---------
# HEAD names a branch nobody pushed, so ls-remote advertises no HEAD symref, and
# a `remote add` checkout has no origin/HEAD. Guessing "main" here is the defect.
make_origin un trunk
git -C "$WORK/un.git" symbolic-ref HEAD refs/heads/nowhere
git init -q "$WORK/skel4"
git -C "$WORK/skel4" remote add origin "$WORK/un.git"
git -C "$WORK/skel4" fetch -q origin
git -C "$WORK/skel4" checkout -q -b trunk origin/trunk
: > "$WORK/pages.txt"
run_worker "$WORK/skel4" "$WORK/state4"
RC4=$?
[ "$RC4" != "0" ] || fail "unresolvable default: the worker exited 0, indistinguishable from a healthy run.
      It said: $(tail -3 "$WORK/state4.out")"
SKEL4_REAL="$(cd "$WORK/skel4" && pwd -P)"
grep "INFRA" "$WORK/state4.out" | grep -qE "$WORK/skel4|$SKEL4_REAL" \
  || fail "unresolvable default: no INFRA line names the repo. It said: $(grep INFRA "$WORK/state4.out" | head -2)"
grep "INFRA" "$WORK/state4.out" | grep -qi "default branch" \
  || fail "unresolvable default: the INFRA line does not give the reason (default branch)"
[ ! -d "$WORK/state4/worktrees/ask-aaa" ] || fail "unresolvable default: a worktree was cut anyway (a guess)"
[ ! -s "$WORK/worked.txt" ] || fail "unresolvable default: the agent was dispatched anyway"
[ -s "$WORK/pages.txt" ] || fail "unresolvable default: nobody was told (\$NOTIFY never called)"
ok "an unresolvable default refuses as INFRA (rc=$RC4), names the repo and the reason, cuts nothing"

# --- 5. a master-repo run that commits: pushed, PR opened against master ----
make_origin m5 master
git clone -q "$WORK/m5.git" "$WORK/skel5"
touch "$WORK/commit-on-run"
run_worker "$WORK/skel5" "$WORK/state5"
rm -f "$WORK/commit-on-run"
git -C "$WORK/m5.git" rev-parse -q --verify refs/heads/sana/ask-aaa >/dev/null \
  || fail "master repo: the agent's commit was never pushed (the ahead count read origin/main). It said:
      $(grep -E 'ASK-AAA' "$WORK/state5.out" | tail -3)"
grep -E "^pr create" "$WORK/gh-calls.txt" | grep -q -- "--base master" \
  || fail "master repo: the PR was not opened against master. gh saw: $(grep -E '^pr create' "$WORK/gh-calls.txt" | head -1)"
ok "a master-repo commit is pushed and the PR is opened --base master"

# --- 6. interview-coach is un-paused ------------------------------------------
"$REAL_PY" - "$REGISTRY" <<'PY' || fail "instance-registry.json: interview-coach is still paused (see above)"
import json, sys
reg = json.load(open(sys.argv[1]))
rows = [i for i in reg.get("instances", reg if isinstance(reg, list) else [])
        if isinstance(i, dict) and i.get("name") == "interview-coach"]
assert rows, "no interview-coach row in the registry"
d = rows[0].get("dispatch") or {}
problems = []
if d.get("enabled") is not True:
    problems.append("dispatch.enabled is %r, not true" % d.get("enabled"))
for k in ("decision", "reason"):
    if k in d:
        problems.append("the pause key %r is still present" % k)
if problems:
    print("  interview-coach: " + "; ".join(problems), file=sys.stderr)
    sys.exit(1)
PY
ok "interview-coach is dispatch-enabled with no pause decision/reason keys"

# --- 7. no executable line still hardcodes main -------------------------------
# A backstop for the paths the cases above cannot reach cheaply (the PR-head
# repositioning guard). Comments are excluded: the scar history names main.
LEFT="$(grep -nE 'origin/main|--base main' "$WORKER" | grep -vE '^[0-9]+:[[:space:]]*#')"
[ -z "$LEFT" ] || fail "linear-worker.sh still hardcodes main on an executable line:
$LEFT"
ok "no executable line of linear-worker.sh hardcodes origin/main or --base main"

bash -n "$WORKER" || fail "linear-worker.sh does not parse"
echo "PASS: worker default branch ($PASS checks)"
