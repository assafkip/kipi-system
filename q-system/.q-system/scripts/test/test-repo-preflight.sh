#!/usr/bin/env bash
# Reproducer for finding-8 (BLOCKER) and finding-9 of
# prd-terminal-state-redrive-2026-08-01.
#
# Pairs with: repo-preflight.sh, and fleet_candidates/rotation/pick_list/cursor_set
# in kipi-dispatch.sh.
#
# WHAT IS BEING PREVENTED
# -----------------------
# Exactly one dispatch job exists fleet-wide and it is bound to the kipi-system
# checkout, so 18 ready owner:sana issues across 14 projects are skipped as
# out-of-repo every cycle. The obvious fix -- let the dispatcher iterate the
# registry -- points an unattended loop that RUNS AGENTS, PUSHES BRANCHES AND ARMS
# AUTO-MERGE at Alice, Prodigy_Gold and Pure_spectrum_Q. Codex called opt-in plus a
# project filter inadequate for that, and it was right: opt-in says which repos a
# human MEANT to enter, it says nothing about whether entering one is SAFE right
# now. The preflight is the part that answers "safe right now".
#
# TWO PROPERTIES, AND BOTH ARE LOAD-BEARING
#   1. A repo failing ANY preflight item is ABSENT from the pick list (finding-8).
#   2. Selection is round-robin from a recorded cursor, so a repo that sorts LAST
#      is eventually picked even while an earlier repo always has work (finding-9).
#      "Lists ready issues from two repos" is explicitly NOT sufficient and is not
#      what this file asserts.
#
# WHY THE STUB IS A PATH STUB AND NOT AN ENV OVERRIDE. The preflight shells `gh`
# for branch protection and credentials. Giving it a KIPI_GH variable would have
# been convenient and would ALSO have been a documented way to defeat two checks
# by pointing them at /bin/true. There is no such variable; the test prepends a
# stub dir to PATH instead. Same for the preflight script path: the dispatcher
# hardcodes it off $REPO, so no variable can aim it at a script that always passes.
#
# NEVER A LIVE DATA PATH. Every repo here is a git repo built under mktemp, and the
# registry the dispatcher reads is a fixture. A test that enumerated the real
# instance-registry.json would be one bug away from entering a client repo, which
# is the exact thing under test.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derive the repo from the SCRIPT, never from $PWD -- a test that asks the checkout
# it happens to run in proves nothing about the caller (test-dispatch-stale-checkout
# learned this first).
REPO="$(cd "$HERE" && git rev-parse --show-toplevel)"
DISPATCH="$REPO/kipi-dispatch.sh"
PREFLIGHT="$REPO/q-system/.q-system/scripts/repo-preflight.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

[ -f "$DISPATCH" ] || { echo "no kipi-dispatch.sh at $DISPATCH"; exit 1; }

# --- STAGE 0: the defect, stated as a check that can fail --------------------
if [ ! -f "$PREFLIGHT" ]; then
  echo "  FAIL: THE DEFECT: no repo-preflight.sh exists, so a dispatcher that iterates"
  echo "        the registry would enter Alice / Prodigy_Gold / Pure_spectrum_Q with no"
  echo "        check on control-code version, hooks, remote, branch protection,"
  echo "        credentials, dirty state or a kill switch."
  echo "-------- 0 passed, 1 failed --------"
  exit 1
fi
for fn in fleet_candidates rotation pick_list cursor_set cursor_get; do
  grep -q "^${fn}() {" "$DISPATCH" || {
    echo "  FAIL: THE DEFECT: kipi-dispatch.sh has no ${fn}() -- selection is still"
    echo "        single-repo and registry-order, so later client repos starve."
    echo "-------- 0 passed, 1 failed --------"
    exit 1
  }
done

# --- a stub gh on PATH -------------------------------------------------------
# Two knobs, both defaulting to the HEALTHY answer, so a fixture that fails a
# preflight item fails it because the test asked for that and not because the
# sandbox has no gh. A stub whose default is "broken" would make every case green
# for the wrong reason -- the accidental-shield failure.
STUBBIN="$WORK/stubbin"; mkdir -p "$STUBBIN"
cat > "$STUBBIN/gh" <<'STUB'
#!/usr/bin/env bash
case "$1 ${2:-}" in
  "auth status")
    [ "${STUB_GH_AUTH:-ok}" = "ok" ] || { echo "not logged in" >&2; exit 1; }
    echo "Logged in to github.com"; exit 0 ;;
esac
case "${*}" in
  *"/protection"*)
    [ "${STUB_GH_PROTECTION:-ok}" = "ok" ] || { echo "Branch not protected" >&2; exit 1; }
    echo '{"required_pull_request_reviews":{"required_approving_review_count":1},"required_status_checks":{"strict":true,"contexts":["ci"]}}'; exit 0 ;;
  "repo view"*)
    [ "${STUB_GH_REPOVIEW:-ok}" = "ok" ] || { echo "could not resolve to a Repository" >&2; exit 1; }
    echo "assafkip/fixture"; exit 0 ;;
  "api repos/"*)
    [ "${STUB_GH_REPOVIEW:-ok}" = "ok" ] || { echo "Not Found" >&2; exit 1; }
    echo "main"; exit 0 ;;
esac
exit 0
STUB
chmod +x "$STUBBIN/gh"
export PATH="$STUBBIN:$PATH"

# --- fixture builder ---------------------------------------------------------
# A repo that passes ALL SEVEN items. Every failing fixture below is this one with
# exactly one thing broken, so a failure names one cause and not a pile.
SKEL_WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
SKEL_SETTINGS="$REPO/.claude/settings.json"

# EVERY fixture git mutation goes through here. THE SCAR, and it is this file's
# own: before make_good_repo's `local` bug was fixed it returned an EMPTY path,
# and `cd ""` SUCCEEDS in bash -- it is a no-op, not an error. So
# `( cd "$RM" && git remote set-url origin ... )` ran against the LIVE CHECKOUT
# and rewrote this repo's origin to a fixture URL. Worktrees share .git/config,
# so it broke the main checkout too, and it surfaced as a confusing "Repository
# not found" on push long after the test had gone green.
#
# A test must never touch a live data path. One chokepoint that refuses an empty
# path or the real repo is how that becomes impossible rather than remembered.
fixture_git() {
  local d="$1"; shift
  case "$d" in
    ""|"$REPO"|"$REPO"/*)
      echo "FATAL: fixture_git refused a live or empty path: '$d'" >&2; exit 1 ;;
  esac
  [ -d "$d/.git" ] || { echo "FATAL: fixture_git: '$d' is not a fixture repo" >&2; exit 1; }
  git -C "$d" "$@"
}

# Copy every hook script the skeleton actually wires into a fixture. THE FIXTURE
# WAS THE BUG: it used to copy settings.json alone, so the "all-green" repo named
# guards it did not have -- and codex used that fixture as the proof that basename
# comparison was hollow. A control repo has to be genuinely compliant, or every
# refusal measured against it is measuring the wrong thing.
copy_guards() {
  python3 - "$SKEL_SETTINGS" "$REPO" "$1" <<'GPY'
import json, os, re, shutil, sys
settings, skel, dst = sys.argv[1], sys.argv[2], sys.argv[3]
hooks = json.load(open(settings)).get("hooks", {})
names = set()
for arr in hooks.values():
    for m in arr or []:
        for hk in m.get("hooks", []) or []:
            names |= set(re.findall(r"[\w.-]+\.(?:py|sh)", hk.get("command", "") or ""))
for rel in sorted(names):
    for base, _dirs, files in os.walk(skel):
        if "/.git" in base:
            continue
        if rel in files:
            r = os.path.relpath(os.path.join(base, rel), skel)
            t = os.path.join(dst, r)
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(os.path.join(base, rel), t)
            break
GPY
}

make_good_repo() {
  # TWO `local` LINES, NOT ONE. `local name="$1" dir="$WORK/$name"` expands every
  # word before it assigns any of them, so $name is still unbound when $dir is
  # built -- under `set -u` the function aborts and returns an EMPTY path. Every
  # fixture then pointed at "", the registry rows were dropped as pathless, and the
  # round-robin and mutation cases passed while testing nothing at all.
  local name="$1"
  local dir="$WORK/$name"
  [ -n "$name" ] && [ -n "$WORK" ] || { echo "FATAL: make_good_repo got an empty name/WORK" >&2; exit 1; }
  mkdir -p "$dir/q-system/.q-system/scripts" "$dir/.claude"
  cp "$SKEL_WORKER" "$dir/q-system/.q-system/scripts/linear-worker.sh"
  cp "$SKEL_SETTINGS" "$dir/.claude/settings.json"
  # $2 = "noguards" builds the deliberately non-compliant shape for case 17.
  [ "${2:-}" = "noguards" ] || copy_guards "$dir"
  git init -q -b main "$dir"
  ( git -C "$dir" config user.email t@e.com
    git -C "$dir" config user.name t
    git -C "$dir" add -A
    git -C "$dir" commit -qm init
    git -C "$dir" remote add origin "https://github.com/assafkip/$name.git" ) >/dev/null 2>&1
  printf '%s' "$dir"
}

# Exit 0 = the repo may be entered. Any non-zero = refuse.
run_preflight() { bash "$PREFLIGHT" "$1" "${2:-https://github.com/assafkip/$(basename "$1").git}" 2>&1; }
pf_rc() { bash "$PREFLIGHT" "$1" "${2:-https://github.com/assafkip/$(basename "$1").git}" >/dev/null 2>&1; echo $?; }

echo "== 1. the control: a repo that passes all seven items is ACCEPTED =="
# THIS CASE IS THE POINT OF THE WHOLE STUB DESIGN. If it fails, every "refused"
# assertion below is green for the wrong reason and proves nothing.
GOOD="$(make_good_repo good)"
OUT="$(run_preflight "$GOOD")"
if [ "$(pf_rc "$GOOD")" = "0" ]; then
  ok "an all-green repo passes preflight (so the refusals below mean something)"
else
  bad "the all-green control was REFUSED, so every refusal below is unproven: $OUT"
fi

echo
echo "== 2. each of the seven items refuses ON ITS OWN, and names itself =="
# One fixture per item. The assertion is not just "refused" but "refused NAMING
# this check" -- a preflight that refuses everything with one generic message is
# useless to whoever has to fix the repo.

# 2a. kill switch
KS="$(make_good_repo killswitch)"; : > "$KS/.kipi-no-dispatch"
OUT="$(run_preflight "$KS")"
{ [ "$(pf_rc "$KS")" != "0" ] && echo "$OUT" | grep -q 'kill-switch'; } \
  && ok "kill-switch: a .kipi-no-dispatch file refuses the repo by name" \
  || bad "kill-switch did not refuse or did not name itself: $OUT"

# 2b. control-code version: the repo's worker copy has drifted from the skeleton's.
# kipi update is manual, so an instance can be months behind -- running THAT copy
# is running control code nobody reviewed, on a loop that merges its own PRs.
CC="$(make_good_repo controlcode)"
echo '# drifted' >> "$CC/q-system/.q-system/scripts/linear-worker.sh"
fixture_git "$CC" commit -qam drift >/dev/null 2>&1
OUT="$(run_preflight "$CC")"
{ [ "$(pf_rc "$CC")" != "0" ] && echo "$OUT" | grep -q 'control-code'; } \
  && ok "control-code: a worker copy that drifted from the skeleton refuses by name" \
  || bad "control-code drift did not refuse or did not name itself: $OUT"

# 2c. hook presence
HK="$(make_good_repo hooks)"
echo '{}' > "$HK/.claude/settings.json"
fixture_git "$HK" commit -qam strip >/dev/null 2>&1
OUT="$(run_preflight "$HK")"
{ [ "$(pf_rc "$HK")" != "0" ] && echo "$OUT" | grep -q 'hooks'; } \
  && ok "hooks: a repo missing the skeleton's hook events refuses by name" \
  || bad "missing hooks did not refuse or did not name itself: $OUT"

# 2d. remote identity: origin is not the remote the registry pinned. This is the
# check that stops a mis-typed or re-pointed registry row pushing an agent's branch
# to somebody else's GitHub repo.
RM="$(make_good_repo remote)"
fixture_git "$RM" remote set-url origin https://github.com/someone-else/other.git >/dev/null 2>&1
OUT="$(run_preflight "$RM")"
{ [ "$(pf_rc "$RM")" != "0" ] && echo "$OUT" | grep -q 'remote'; } \
  && ok "remote: an origin that differs from the pinned remote refuses by name" \
  || bad "remote mismatch did not refuse or did not name itself: $OUT"

# 2e. remote identity with NO pin at all. An undeclared remote must refuse, not
# default to trusting whatever origin happens to say.
OUT="$(bash "$PREFLIGHT" "$GOOD" "" 2>&1)"
RC=$(bash "$PREFLIGHT" "$GOOD" "" >/dev/null 2>&1; echo $?)
{ [ "$RC" != "0" ] && echo "$OUT" | grep -q 'remote'; } \
  && ok "remote: a registry row with no pinned remote refuses (absence is not consent)" \
  || bad "an unpinned remote was accepted, so any origin would be trusted: $OUT"

# 2f. branch protection
OUT="$(STUB_GH_PROTECTION=broken run_preflight "$GOOD")"
RC=$(STUB_GH_PROTECTION=broken bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" >/dev/null 2>&1; echo $?)
{ [ "$RC" != "0" ] && echo "$OUT" | grep -q 'branch-protection'; } \
  && ok "branch-protection: an unprotected default branch refuses by name" \
  || bad "an unprotected branch was accepted -- auto-merge would land unreviewed code: $OUT"

# 2g. credentials
OUT="$(STUB_GH_AUTH=broken run_preflight "$GOOD")"
RC=$(STUB_GH_AUTH=broken bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" >/dev/null 2>&1; echo $?)
{ [ "$RC" != "0" ] && echo "$OUT" | grep -q 'credentials'; } \
  && ok "credentials: a broken gh auth refuses by name" \
  || bad "broken credentials were accepted: $OUT"

# 2h. dirty working tree: uncommitted work in a CLIENT repo belongs to a human, and
# an agent that branches and commits there captures it into its own PR.
DT="$(make_good_repo dirty)"; echo "someones work in progress" > "$DT/notes.txt"
OUT="$(run_preflight "$DT")"
{ [ "$(pf_rc "$DT")" != "0" ] && echo "$OUT" | grep -q 'dirty'; } \
  && ok "dirty: an uncommitted working tree refuses by name" \
  || bad "a dirty tree was accepted, so a human's WIP can be swept into an agent PR: $OUT"

echo
echo "== 3. the preflight FAILS CLOSED, which is the opposite of stale_check =="
# stale_check deliberately fails OPEN (a network blip must not wedge the loop).
# This one must fail CLOSED: it guards a client repo, and "I could not tell whether
# the branch is protected" is not permission to push to it. Both postures are
# correct for their own job and the difference is the thing to keep straight.
NOGH="$WORK/nogh"; mkdir -p "$NOGH"
cat > "$NOGH/gh" <<'NOGHSTUB'
#!/usr/bin/env bash
echo "gh: command failed" >&2; exit 127
NOGHSTUB
chmod +x "$NOGH/gh"
RC=$(PATH="$NOGH:$PATH" bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" >/dev/null 2>&1; echo $?)
[ "$RC" != "0" ] \
  && ok "an unanswerable preflight REFUSES (fail closed), unlike stale_check" \
  || bad "THE DEFECT: could not reach gh and entered the repo anyway"

# A missing preflight SCRIPT must also refuse, not silently allow. This is the
# hole an operator creates by moving the file.
echo

echo "== 4. finding-8: a repo failing ONE item is ABSENT from the pick list =="
# This is the issue's bypass_check, end to end through the dispatcher rather than
# through the preflight in isolation.
mk_registry() {
  # $1 = output path, then name:path:enabled triples
  local out="$1"; shift
  python3 - "$out" "$@" <<'PY'
import json, sys
out, rows = sys.argv[1], sys.argv[2:]
inst = []
for r in rows:
    name, path, enabled = r.split("|")
    e = {"name": name, "path": path, "has_git": True}
    if enabled != "absent":
        e["dispatch"] = {"enabled": enabled == "true",
                         "expected_remote": "https://github.com/assafkip/%s.git" % name}
    inst.append(e)
json.dump({"skeleton": {"path": "/nonexistent"}, "instances": inst}, open(out, "w"), indent=2)
PY
}

# Drive the dispatcher's selection functions directly. Running the whole script
# would reach Linear and could dispatch REAL work.
HARNESS="$WORK/select.sh"
{
  echo 'set -uo pipefail'
  echo 'say() { printf "SAY %s\n" "$*" >&2; }'
  echo "REPO=\"$REPO\""
  echo "PREFLIGHT=\"$PREFLIGHT\""
  awk '/^cursor_get\(\) \{/,/^\}/'       "$DISPATCH"
  awk '/^cursor_set\(\) \{/,/^\}/'       "$DISPATCH"
  awk '/^fleet_candidates\(\) \{/,/^\}/' "$DISPATCH"
  awk '/^rotation\(\) \{/,/^\}/'         "$DISPATCH"
  awk '/^pick_list\(\) \{/,/^\}/'        "$DISPATCH"
  echo 'pick_list'
} > "$HARNESS"

BAD_ONE="$(make_good_repo badone)"; : > "$BAD_ONE/.kipi-no-dispatch"
OKREPO="$(make_good_repo okrepo)"
REG1="$WORK/reg1.json"
mk_registry "$REG1" "badone|$BAD_ONE|true" "okrepo|$OKREPO|true"

CURS="$WORK/cursor1"
PICKS="$(KIPI_DISPATCH_REGISTRY="$REG1" KIPI_DISPATCH_CURSOR="$CURS" bash "$HARNESS" 2>/dev/null)"
if echo "$PICKS" | grep -q 'okrepo'; then
  ok "a repo passing preflight IS in the pick list"
else
  bad "the healthy repo never reached the pick list, so the absence below is meaningless"
fi
if echo "$PICKS" | grep -q 'badone'; then
  bad "THE DEFECT (finding-8): a repo failing a preflight item is in the pick list"
else
  ok "a repo failing ONE preflight item is ABSENT from the dry-run pick list"
fi

echo
echo "== 5. opt-in is DEFAULT OFF =="
OFFREPO="$(make_good_repo offrepo)"
ABSREPO="$(make_good_repo absrepo)"
REG2="$WORK/reg2.json"
mk_registry "$REG2" "offrepo|$OFFREPO|false" "absrepo|$ABSREPO|absent" "okrepo|$OKREPO|true"
PICKS2="$(KIPI_DISPATCH_REGISTRY="$REG2" KIPI_DISPATCH_CURSOR="$WORK/cursor2" bash "$HARNESS" 2>/dev/null)"
echo "$PICKS2" | grep -q 'offrepo' \
  && bad "a repo with dispatch.enabled=false was entered" \
  || ok "dispatch.enabled=false is never entered"
echo "$PICKS2" | grep -q 'absrepo' \
  && bad "THE DEFECT: a repo with NO dispatch key was entered -- default is not off" \
  || ok "a registry entry with no dispatch key is never entered (default OFF)"

echo
echo "== 6. finding-9: the repo that sorts LAST is eventually picked =="
# The starvation shape, concretely: home always has work. Under registry-order
# scanning the head of the list is home on every single cycle and zzz-last is never
# reached -- not "reached late", NEVER. So the assertion is that zzz-last becomes
# the HEAD of the pick list within one full rotation.
A="$(make_good_repo aaa-first)"; M="$(make_good_repo mmm-middle)"; Z="$(make_good_repo zzz-last)"
REG3="$WORK/reg3.json"
mk_registry "$REG3" "aaa-first|$A|true" "mmm-middle|$M|true" "zzz-last|$Z|true"
CURS3="$WORK/cursor3"

# One cycle = read the pick list, take the head, record it as picked.
cycle() {
  local head
  head="$(KIPI_DISPATCH_REGISTRY="$REG3" KIPI_DISPATCH_CURSOR="$CURS3" bash "$HARNESS" 2>/dev/null | head -1 | cut -f1)"
  [ -n "$head" ] || return 1
  ( set -uo pipefail
    say() { :; }
    REPO="$REPO"
    # shellcheck disable=SC1090
    source /dev/stdin <<CS
$(awk '/^cursor_set\(\) \{/,/^\}/' "$DISPATCH")
CS
    KIPI_DISPATCH_CURSOR="$CURS3" cursor_set "$head" )
  printf '%s' "$head"
}
SEQ=""
for _ in 1 2 3 4 5; do SEQ="$SEQ $(cycle)"; done
echo "  cycles picked:$SEQ"
case "$SEQ" in
  *zzz-last*) ok "the LAST-sorting repo is picked within a rotation (round-robin holds)" ;;
  *) bad "THE DEFECT (finding-9): zzz-last never became the head -- later repos starve:$SEQ" ;;
esac
# Fairness, not just eventual reachability: no repo may be picked twice before
# every other has been picked once.
UNIQ="$(printf '%s\n' $SEQ | sort -u | grep -c .)"
[ "$UNIQ" -ge 4 ] \
  && ok "a full rotation offers every candidate a turn ($UNIQ distinct in 5 cycles)" \
  || bad "only $UNIQ distinct repos in 5 cycles -- the cursor is not rotating"

echo
echo "== 7. a repo that FAILS preflight is skipped by the rotation, not blocking it =="
# A refused repo must not consume the turn and stall the rotation behind it.
BLK="$(make_good_repo blocked-repo)"; : > "$BLK/.kipi-no-dispatch"
# A REPO OF ITS OWN, named to match its pinned remote. Reusing zzz-last here under
# the name "zzz-after" would have failed the REMOTE check, so the rotation would
# have looked stalled for the wrong reason and this case would have accused the
# cursor of a bug the preflight actually caused.
AFT="$(make_good_repo zzz-after)"
REG4="$WORK/reg4.json"
mk_registry "$REG4" "blocked-repo|$BLK|true" "zzz-after|$AFT|true"
PICKS4="$(KIPI_DISPATCH_REGISTRY="$REG4" KIPI_DISPATCH_CURSOR="$WORK/cursor4" bash "$HARNESS" 2>/dev/null)"
echo "$PICKS4" | grep -q 'zzz-after' \
  && ok "a refused repo is skipped over, not a wall the rotation stops at" \
  || bad "the rotation stalled behind a refused repo: $PICKS4"

echo
echo "== 8. NO flag, env var, or registry field skips the preflight =="
# Structural, not a phrase hunt. The dispatcher must call the preflight from exactly
# one place, and that call must not sit behind a conditional that any input can make
# false. A skippable safety gate on a client repo is worse than none, because it
# reads as protection.
CALLS="$(grep -c 'bash "\$PREFLIGHT"' "$DISPATCH" || true)"
[ "${CALLS:-0}" -eq 1 ] \
  && ok "the preflight is invoked from exactly one call-site ($CALLS)" \
  || bad "the preflight has $CALLS call-sites -- one of them can drift from the others"
# The preflight path is hardcoded off $REPO. A variable here would let an operator
# aim the gate at /bin/true and keep every log line looking identical.
grep -qE '^PREFLIGHT="\$REPO/' "$DISPATCH" \
  && ok "the preflight path is hardcoded off \$REPO, not overridable" \
  || bad "the preflight path is env-overridable, which is a documented bypass"
grep -nE 'KIPI_(SKIP|NO)_PREFLIGHT|skip_preflight|--no-preflight|force_dispatch' "$DISPATCH" \
  && bad "a preflight skip switch exists in the dispatcher" \
  || ok "no skip switch exists in the dispatcher"
# A registry row must not be able to declare itself exempt.
python3 - "$DISPATCH" <<'PY' && ok "no registry field is read as a preflight exemption" || bad "a registry field can exempt a repo from preflight"
import re, sys
src = open(sys.argv[1]).read()
sys.exit(1 if re.search(r'(exempt|trusted|skip_preflight|no_preflight)', src, re.I) else 0)
PY

echo
echo "== 9. the cursor has ONE writer (finding-12: no read-then-write race) =="
# attempts-ledger.py exists because a read-then-write from two processes loses an
# update. The cursor must not recreate that: every mutation goes through cursor_set,
# and cursor_set takes an atomic lock and renames into place.
# A line that MAKES the cursor's content: a redirect straight into it, or the
# rename that swaps a temp file into place. The temp write itself is deliberately
# not counted -- writing "$CURSOR_FILE.tmp.$$" is not publishing a cursor value,
# and counting it would let a 0-vs-0 comparison pass this case with no chokepoint
# at all. (Caught here: the first version of this assertion did exactly that.)
WRITE_PAT='(> *"\$CURSOR_FILE"|mv .*"\$CURSOR_FILE")'
awk '/^cursor_set\(\) \{/,/^\}/' "$DISPATCH" > "$WORK/cs.txt"
OUTSIDE="$(grep -cE "$WRITE_PAT" "$DISPATCH" || true)"
INSIDE_N="$(grep -cE "$WRITE_PAT" "$WORK/cs.txt" || true)"
[ "${INSIDE_N:-0}" -ge 1 ] \
  && ok "cursor_set is the writer chokepoint ($INSIDE_N publishing write)" \
  || bad "cursor_set never publishes the cursor -- the chokepoint is somewhere else"
[ "${OUTSIDE:-0}" -eq "${INSIDE_N:-0}" ] \
  && ok "every write to the cursor file is inside cursor_set ($OUTSIDE total)" \
  || bad "THE DEFECT (finding-12): $OUTSIDE writes to the cursor, only $INSIDE_N inside cursor_set"
# cursor_set deliberately holds NO lock of its own now: turn_lock covers the whole
# read-select-advance, and the old inner lock could be orphaned by a killed
# dispatcher and then wedge rotation forever with nothing to reap it.
grep -q 'mkdir "$lock"' "$WORK/cs.txt" \
  && bad "cursor_set took its own lock again -- an orphaned one wedges rotation forever" \
  || ok "cursor_set holds no redundant inner lock (the turn lock is the transaction)"
grep -qE 'mv .*"\$CURSOR_FILE"' "$WORK/cs.txt" \
  && ok "cursor_set publishes by rename, so no reader sees a half-written name" \
  || bad "cursor_set truncates in place; a concurrent read can see a partial value"

echo
echo "== 10. MUTATION: delete the preflight call and case 4 must go RED =="
# A green test that stays green with the safety code removed is decorative. This
# proves the pick-list assertion is actually driven by the preflight and not by
# some incidental property of the fixtures.
MUT="$WORK/mutant-dispatch.sh"
sed 's|bash "$PREFLIGHT"|true "$PREFLIGHT"|' "$DISPATCH" > "$MUT"
if cmp -s "$MUT" "$DISPATCH"; then
  bad "the mutation changed nothing -- the mutant is not a mutant, so this proves nothing"
else
  MUTH="$WORK/select-mutant.sh"
  {
    echo 'set -uo pipefail'
    echo 'say() { printf "SAY %s\n" "$*" >&2; }'
    echo "REPO=\"$REPO\""
    echo "PREFLIGHT=\"$PREFLIGHT\""
    awk '/^cursor_get\(\) \{/,/^\}/'       "$MUT"
    awk '/^cursor_set\(\) \{/,/^\}/'       "$MUT"
    awk '/^fleet_candidates\(\) \{/,/^\}/' "$MUT"
    awk '/^rotation\(\) \{/,/^\}/'         "$MUT"
    awk '/^pick_list\(\) \{/,/^\}/'        "$MUT"
    echo 'pick_list'
  } > "$MUTH"
  MPICKS="$(KIPI_DISPATCH_REGISTRY="$REG1" KIPI_DISPATCH_CURSOR="$WORK/cursorM" bash "$MUTH" 2>/dev/null)"
  if echo "$MPICKS" | grep -q 'badone'; then
    ok "with the preflight call removed the refused repo REAPPEARS -- the gate is load-bearing"
  else
    bad "the mutant still excluded the bad repo, so case 4 is not driven by the preflight"
  fi
fi

echo
echo "== 11. the worker accepts --repo and AIMS AT IT (codex finding-1) =="
# A rotation that reaches an opted-in repo and then skips it does not make the 18
# out-of-repo issues pickable, which is this issue's stated outcome. Codex called
# it as a blocker: no external repo was ever dispatched.
#
# DRIVEN, NOT GREPPED. The worker stops with exit 9 the moment `git fetch` fails
# against its target, BEFORE it reaches Linear or cuts a worktree. Pointing a
# fixture at a nonexistent origin therefore proves which path --repo actually
# aimed the run at, using the worker's own control flow, with no network and no
# live data path touched.
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
NOTIFY_STUB="$WORK/notify.sh"
cat > "$NOTIFY_STUB" <<NOTIFYEOF
#!/usr/bin/env bash
printf 'NOTIFY-STUB: %s\n' "\$*" >> "$WORK/notify.log"
NOTIFYEOF
chmod +x "$NOTIFY_STUB"
# KIPI_NOTIFY AND KIPI_STATE_DIR ARE BOTH MANDATORY HERE. The worker pages on the
# INFRA stop and appends to $HOME/.config/kipi/linear-worker.log. Three tests
# leaked real Slack pages to the founder on 2026-08-01 and PR #54 exists to close
# that class; this is not adding a fourth, and it is not writing the live log.
TGT="$(make_good_repo targetrepo)"
fixture_git "$TGT" remote set-url origin "$WORK/definitely-not-here.git" >/dev/null 2>&1
run_worker() {
  KIPI_NOTIFY="$NOTIFY_STUB" KIPI_STATE_DIR="$WORK/wstate" \
    bash "$WORKER" "$@" 2>&1
}
WOUT="$(run_worker --repo "$TGT")"; WRC=$?
if printf '%s' "$WOUT" | grep -q 'unknown arg: --repo'; then
  bad "THE DEFECT (finding-1): the worker rejects --repo, so no opted-in repo can be entered"
else
  ok "the worker accepts a --repo argument"
fi
if [ "$WRC" -eq 9 ] && printf '%s' "$WOUT" | grep -qF "$TGT"; then
  ok "--repo aims the run at the TARGET repo (stopped at its fetch, naming it)"
else
  bad "--repo did not aim the run at $TGT (rc=$WRC): $(printf '%s' "$WOUT" | tail -2 | tr '\n' ' ')"
fi
# The run must NOT have aimed at the skeleton. Without this, a worker that ignored
# --repo entirely and failed for its own reasons could still satisfy the case above.
printf '%s' "$WOUT" | grep -q "git fetch failed in $REPO\b" \
  && bad "the run aimed at the SKELETON despite --repo, so work would land in the wrong repo" \
  || ok "the run did not fall back to the skeleton checkout"
# No real Slack. Assert the stub is what absorbed the page.
if [ -f "$WORK/notify.log" ]; then
  grep -q 'NOTIFY-STUB' "$WORK/notify.log" \
    && ok "the INFRA page went to the stub, not to real Slack" \
    || bad "notify.log exists but carries no stub marker"
else
  ok "no page emitted on this path (and none could reach real Slack: KIPI_NOTIFY is stubbed)"
fi

echo
echo "== 12. control code stays on the SKELETON while work follows the target =="
# $SKEL means two different things and conflating them breaks the agent. Registered
# instances carry a worker copy but NO ./kipi entrypoint and no plugins/prd-os, so a
# --repo that repointed everything would hand the agent "bash <instance>/kipi linear
# progress ..." and "python3 <instance>/plugins/prd-os/..." -- both nonexistent.
# Work (fetch, worktree, auto-merge, project identity) follows the target; tooling
# references stay on the skeleton that is actually running.
grep -qE 'TARGET_REPO' "$WORKER" \
  && ok "the worker has a TARGET_REPO identity distinct from SKEL" \
  || bad "no TARGET_REPO in the worker: work and control code are still the same variable"
grep -qE 'git -C "\$TARGET_REPO" (fetch|worktree|rev-parse)' "$WORKER" \
  && ok "git work (fetch/worktree) follows TARGET_REPO" \
  || bad "git work still runs against SKEL, so an opted-in repo would never be checked out"
grep -qE '\$SKEL/kipi|\$SKEL/plugins' "$WORKER" \
  && ok "control-code references still point at the skeleton" \
  || bad "the agent's kipi/prd-os references were repointed at a repo that has neither"
# The registry itself lives in the skeleton; only the path being looked UP is the target.
grep -qE 'REG="\$SKEL/instance-registry.json"' "$WORKER" \
  && ok "identity is resolved from the SKELETON's registry, keyed on the target path" \
  || bad "the registry is read from the target repo, which does not carry one"

echo
echo "== 13. branch protection must carry a REVIEW or CHECK gate (codex finding-2) =="
# The exact shape codex called: protection that exists but only blocks force
# pushes. The endpoint returns 200, so the first version accepted it -- while the
# worker arms auto-merge and lands code with nothing in its way. This fixture
# passes the OLD check and must fail the new one.
WEAK="$WORK/weakprot"; mkdir -p "$WEAK"
cat > "$WEAK/gh" <<'WEAKSTUB'
#!/usr/bin/env bash
case "$1 ${2:-}" in
  "auth status") echo ok; exit 0 ;;
esac
case "${*}" in
  *"/protection"*) echo '{"allow_force_pushes":{"enabled":false},"required_linear_history":{"enabled":true}}'; exit 0 ;;
  "repo view"*)    echo seen; exit 0 ;;
  "api repos/"*)   echo main; exit 0 ;;
esac
exit 0
WEAKSTUB
chmod +x "$WEAK/gh"
WOUT2="$(PATH="$WEAK:$PATH" bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" 2>&1)"
WRC2=$(PATH="$WEAK:$PATH" bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" >/dev/null 2>&1; echo $?)
{ [ "$WRC2" != "0" ] && printf '%s' "$WOUT2" | grep -q 'branch-protection'; } \
  && ok "protection with no required review and no required check is REFUSED" \
  || bad "THE DEFECT (finding-2): force-push-only protection passed as a review gate: $WOUT2"
# Control: a branch that DOES require reviews must still pass, or the check has
# just become "always refuse", which is safe and useless.
[ "$(pf_rc "$GOOD")" = "0" ] \
  && ok "protection WITH required reviews still passes (not a blanket refusal)" \
  || bad "the review-gated control was refused, so this check now refuses everything"

echo
echo "== 14. hook parity compares GUARD SCRIPTS, not event names (codex finding-3) =="
# The bypass codex found: keep one hook under every event, drop the blocking
# guards. Event names all still present, so the old check passed.
HK2="$(make_good_repo hookshallow)"
python3 - "$HK2/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
# Keep EVERY event name, with one harmless hook each. This is the shape that
# defeated the event-name comparison.
d["hooks"] = {ev: [{"hooks": [{"command": "true"}]}] for ev in d.get("hooks", {})}
json.dump(d, open(p, "w"), indent=2)
PY
fixture_git "$HK2" commit -qam shallow >/dev/null 2>&1
HOUT="$(run_preflight "$HK2")"
{ [ "$(pf_rc "$HK2")" != "0" ] && printf '%s' "$HOUT" | grep -q 'hooks'; } \
  && ok "every event present but the guards stripped is REFUSED" \
  || bad "THE DEFECT (finding-3): guard-stripped hooks passed on event names alone: $HOUT"
printf '%s' "$HOUT" | grep -q 'guards=' \
  && ok "the refusal names the missing guard scripts, not just the events" \
  || bad "the refusal does not say which guards are missing: $HOUT"

echo
echo "== 15. the whole selection turn is under one lock (codex finding-4) =="
grep -q '^turn_lock() {' "$DISPATCH" \
  && ok "a turn lock exists" \
  || bad "no turn_lock: read-select-advance is still three unsynchronised steps"
# It must be taken BEFORE the pick list is computed, or it locks nothing that matters.
LOCK_LINE="$(grep -n 'turn_lock' "$DISPATCH" | grep -v '^.*turn_lock() {' | head -1 | cut -d: -f1)"
PICK_LINE="$(grep -n 'PICKS="\$(pick_list)"' "$DISPATCH" | head -1 | cut -d: -f1)"
{ [ -n "$LOCK_LINE" ] && [ -n "$PICK_LINE" ] && [ "$LOCK_LINE" -lt "$PICK_LINE" ]; } \
  && ok "the turn lock is acquired before the pick list is computed" \
  || bad "the lock is taken after selection, so two dispatchers still select together"
# Behavioural: a second acquirer must actually be refused while the first holds it.
TL="$WORK/turnlock.d"
LOCKH="$WORK/lock.sh"
{ echo 'set -uo pipefail'; echo 'say() { :; }'
  awk '/^turn_lock\(\) \{/,/^\}/' "$DISPATCH"
  echo 'turn_lock && echo GOT || echo DENIED'; } > "$LOCKH"
mkdir -p "$(dirname "$TL")"
A="$(KIPI_DISPATCH_TURNLOCK="$TL" bash "$LOCKH" 2>/dev/null)"
# The first shell exited, and its EXIT trap released the lock -- so hold it by
# hand to model a dispatcher that is still mid-turn.
mkdir -p "$TL"
B="$(KIPI_DISPATCH_TURNLOCK="$TL" bash "$LOCKH" 2>/dev/null)"
rmdir "$TL" 2>/dev/null || true
{ [ "$A" = "GOT" ] && [ "$B" = "DENIED" ]; } \
  && ok "a second dispatcher is DENIED while the turn is held ($A then $B)" \
  || bad "the turn lock is not exclusive ($A then $B)"

echo
echo "== 16. null review protection is NOT a review gate (codex r2) =="
# GitHub returns required_pull_request_reviews with a value of NULL when review
# requirements are disabled. A presence test reads that as "reviews required".
NULLP="$WORK/nullprot"; mkdir -p "$NULLP"
cat > "$NULLP/gh" <<'NULLSTUB'
#!/usr/bin/env bash
case "$1 ${2:-}" in
  "auth status") echo ok; exit 0 ;;
esac
case "${*}" in
  *"/protection"*) echo '{"required_pull_request_reviews":null,"required_status_checks":null}'; exit 0 ;;
  "repo view"*)    echo seen; exit 0 ;;
  "api repos/"*)   echo main; exit 0 ;;
esac
exit 0
NULLSTUB
chmod +x "$NULLP/gh"
NOUT="$(PATH="$NULLP:$PATH" bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" 2>&1)"
NRC=$(PATH="$NULLP:$PATH" bash "$PREFLIGHT" "$GOOD" "https://github.com/assafkip/good.git" >/dev/null 2>&1; echo $?)
{ [ "$NRC" != "0" ] && printf '%s' "$NOUT" | grep -q 'branch-protection'; } \
  && ok "required_pull_request_reviews:null is REFUSED, not read as a gate" \
  || bad "THE DEFECT: null review protection accepted as a review gate: $NOUT"

echo
echo "== 17. named guard scripts must EXIST in the target (codex r2 / adversarial) =="
# The green fixture copies settings.json and none of the hook files, which is
# exactly the shape that passed a basename comparison. Give one repo the real
# guard files and prove the difference is what decides it.
NOGUARD="$(make_good_repo noguard noguards)"
GOUT="$(run_preflight "$NOGUARD")"
{ [ "$(pf_rc "$NOGUARD")" != "0" ] && printf '%s' "$GOUT" | grep -q 'hooks'; } \
  && ok "a repo naming guards it does not actually have is REFUSED" \
  || bad "THE DEFECT: guard scripts named but absent still passed: $GOUT"
printf '%s' "$GOUT" | grep -q 'absent=' \
  && ok "the refusal names the guard files that are missing from disk" \
  || bad "the refusal does not distinguish absent files from unwired ones: $GOUT"

echo
echo "== 18. a non-home repo is NOT entered while gh scoping is unfinished =="
# The rotation still offers it a turn, and the dispatcher still refuses to run an
# agent in it. Selection being correct is not the same as execution being safe.
grep -q 'sp-9421b9b7' "$DISPATCH" \
  && ok "cross-repo entry is held against a captured spillover item" \
  || bad "cross-repo entry has no captured blocker reference"
HOLD_LINE="$(grep -n 'HOLD \$TARGET_NAME' "$DISPATCH" | head -1 | cut -d: -f1)"
WORKLINE="$(grep -n 'bash ./kipi work' "$DISPATCH" | head -1 | cut -d: -f1)"
{ [ -n "$HOLD_LINE" ] && [ -n "$WORKLINE" ] && [ "$HOLD_LINE" -lt "$WORKLINE" ]; } \
  && ok "the hold is reached BEFORE any worker is invoked" \
  || bad "the hold does not precede the worker call, so an agent could still start"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: no repo is entered until seven named preflight checks pass, and selection rotates"
