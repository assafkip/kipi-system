#!/usr/bin/env bash
# test-rearm-degraded-approvals.sh -- the ASK-3832 re-arm sweep, on a fixture.
#
# The sweep arms auto-merge on real PRs across the fleet, client repos included,
# so every selection rule gets a case that can fail, and the two refusals that
# protect the archived engagement (RULE-2026-10-23-B) get a mutation each.
#
# Nothing here reaches GitHub, the founder's state dir or his hook: gh is a stub
# on PATH, HOME and KIPI_STATE_DIR are temp dirs, and the archive guard is a
# stand-in placed at $HOME/.claude/hooks/ps-archive-deny.sh, the path the sweep
# reads. The stand-in answers in the real hook's output shape and honours
# ALLOW_PS_ARCHIVE the way the real hook does, so case 7 proves the sweep strips
# that bypass rather than proving the stand-in ignores it.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
SWEEP="$SCRIPTS/rearm-degraded-approvals.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

[ -f "$SWEEP" ] || { echo "  FAIL: no sweep at $SWEEP"; echo "-------- 0 passed, 1 failed --------"; exit 1; }

SHA_A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SHA_B="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SHA_X="cccccccccccccccccccccccccccccccccccccccc"

# --- the fleet ---------------------------------------------------------------
# home       the skeleton checkout; its slug comes from its git origin
# client     dispatch-enabled in the registry, pinned remote (a client repo)
# overlay    only in the private overlay, the way client pins really live
# off        in the registry with dispatch.enabled false: never swept
# archive    dispatch-enabled, but the guard refuses its path
# drifted    dispatch-enabled, but gh from its checkout resolves another PR
HOME_REPO="$WORK/home"
mkdir -p "$HOME_REPO" "$WORK/client" "$WORK/overlay" "$WORK/off" \
         "$WORK/ARCHIVED-FIXTURE-repo" "$WORK/drifted" "$WORK/fakehome/.claude/hooks" \
         "$WORK/state/pr-reviews" "$WORK/bin"
cp "$REPO/kipi-dispatch.sh" "$HOME_REPO/kipi-dispatch.sh"
git init -q "$HOME_REPO"
git -C "$HOME_REPO" remote add origin git@github.com:fix/home.git

cat > "$WORK/registry.json" <<JSON
{"instances": [
  {"name": "client",  "path": "$WORK/client",  "dispatch": {"enabled": true, "expected_remote": "git@github.com:fix/client.git"}},
  {"name": "off",     "path": "$WORK/off",     "dispatch": {"enabled": false, "expected_remote": "git@github.com:fix/off.git"}},
  {"name": "archive", "path": "$WORK/ARCHIVED-FIXTURE-repo", "dispatch": {"enabled": true, "expected_remote": "git@github.com:fix/archived.git"}},
  {"name": "drifted", "path": "$WORK/drifted", "dispatch": {"enabled": true, "expected_remote": "git@github.com:fix/drifted.git"}}
]}
JSON
cat > "$WORK/overlay.json" <<JSON
{"instances": [
  {"name": "overlay", "path": "$WORK/overlay", "dispatch": {"enabled": true, "expected_remote": "git@github.com:fix/overlay.git"}}
]}
JSON

# --- the guard stand-in ------------------------------------------------------
# Same output contract as ~/.claude/hooks/ps-archive-deny.sh: print a
# PreToolUse deny on a match, print nothing otherwise, and allow everything when
# ALLOW_PS_ARCHIVE=1 is in its own environment.
cat > "$WORK/fakehome/.claude/hooks/ps-archive-deny.sh" <<'SH'
#!/bin/bash
INPUT="$(cat)"
printf '%s\n' "$INPUT" >> "$GUARD_LOG"
case "$INPUT" in *ARCHIVED-FIXTURE*) : ;; *) exit 0 ;; esac
[ "${ALLOW_PS_ARCHIVE:-0}" = "1" ] && exit 0
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"fixture"}}\n'
SH

# --- records -----------------------------------------------------------------
rec() {   # rec <slug> <pr> <verdict> <degraded> <head_sha>
  local key
  key="$(printf '%s' "$1" | tr '/' '_' | tr -c 'A-Za-z0-9._-' '_')__pr-$2"
  cat > "$WORK/state/pr-reviews/$key.verdict.json" <<JSON
{"pr":$2,"verdict":"$3","engine":"codex","reviewed_by":"claude-opus-5","degraded":$4,"head_sha":"$5","ts":"2026-10-20T00:00:00Z"}
JSON
}
rec fix/home     11 "APPROVE"            true  "$SHA_A"   # selected
rec fix/home     12 "APPROVE"            true  "$SHA_A"   # head moved to SHA_B
rec fix/home     13 "APPROVE WITH NITS"  true  "$SHA_A"   # CONFLICTING
rec fix/home     14 "APPROVE"            false "$SHA_A"   # not degraded: not this sweep's
rec fix/home     15 "REQUEST CHANGES"    true  "$SHA_A"   # not an approval
rec fix/home     16 "APPROVE"            true  "$SHA_A"   # already armed
rec fix/home     17 "APPROVE"            true  "$SHA_A"   # draft
rec fix/client   21 "APPROVE WITH NITS"  true  "$SHA_A"   # selected (client repo)
rec fix/overlay  31 "APPROVE"            true  "$SHA_A"   # selected (overlay-only repo)
rec fix/off      41 "APPROVE"            true  "$SHA_A"   # repo is off: never seen
rec fix/archived 51 "APPROVE"            true  "$SHA_A"   # archived: never read
rec fix/drifted  61 "APPROVE"            true  "$SHA_A"   # cwd binds elsewhere

# --- gh ----------------------------------------------------------------------
# `pr list -R <slug>` answers in the TSV the sweep's -q asks for. `pr view` and
# `pr merge` have no -R (automerge_arm binds by cwd), so they answer by $PWD.
cat > "$WORK/bin/gh" <<SH
#!/usr/bin/env bash
printf '%s\t%s\n' "\$PWD" "\$*" >> "$WORK/gh-calls"
T=\$'\t'
case "\$*" in
  "pr list -R fix/home "*)
    printf '11\t$SHA_A\tMERGEABLE\tfalse\n12\t$SHA_B\tMERGEABLE\tfalse\n13\t$SHA_A\tCONFLICTING\tfalse\n'
    printf '14\t$SHA_A\tMERGEABLE\tfalse\n15\t$SHA_A\tMERGEABLE\tfalse\n16\t$SHA_A\tMERGEABLE\tfalse\n'
    printf '17\t$SHA_A\tMERGEABLE\ttrue\n18\t$SHA_A\tMERGEABLE\tfalse\n' ;;
  "pr list -R fix/client "*)   printf '21\t$SHA_A\tMERGEABLE\tfalse\n' ;;
  "pr list -R fix/overlay "*)  printf '31\t$SHA_A\tMERGEABLE\tfalse\n' ;;
  "pr list -R fix/off "*)      printf '41\t$SHA_A\tMERGEABLE\tfalse\n' ;;
  "pr list -R fix/archived "*) printf '51\t$SHA_A\tMERGEABLE\tfalse\n' ;;
  "pr list -R fix/drifted "*)  printf '61\t$SHA_A\tMERGEABLE\tfalse\n' ;;
  "pr view "*"--json headRefOid"*)
    case "\$PWD" in */drifted) echo $SHA_X ;; *) echo $SHA_A ;; esac ;;
  "pr view 16 --json autoMergeRequest"*) echo true ;;
  "pr view "*"--json autoMergeRequest"*)
    n="\$(printf '%s' "\$*" | awk '{print \$3}')"
    if grep -q "\$PWD\${T}pr merge --auto --squash \$n\\\$" "$WORK/gh-calls"; then echo true; else echo false; fi ;;
  "pr merge --auto --squash "*) : ;;
esac
exit 0
SH
chmod +x "$WORK/bin/gh" "$WORK/fakehome/.claude/hooks/ps-archive-deny.sh"

# run_sweep <out> [extra env assignments...] -- [sweep args...]
run_sweep() {
  local out="$1"; shift
  local -a extra=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do extra+=("$1"); shift; done
  [ "${1:-}" = "--" ] && shift
  : > "$WORK/gh-calls"; : > "$WORK/guard.log"
  env PATH="$WORK/bin:$PATH" HOME="$WORK/fakehome" KIPI_REPO="$HOME_REPO" \
      KIPI_DISPATCH_REGISTRY="$WORK/registry.json" KIPI_DISPATCH_TARGETS="$WORK/overlay.json" \
      KIPI_STATE_DIR="$WORK/state" GUARD_LOG="$WORK/guard.log" KIPI_NOTIFY=/usr/bin/true \
      ${extra[@]+"${extra[@]}"} \
      bash "${SWEEP_UNDER_TEST:-$SWEEP}" "$@" > "$out" 2>&1
  echo $? > "$out.rc"
}
has()  { grep -qF -- "$2" "$1"; }

echo "== 1. --dry is the default and selects exactly the four rules =="
run_sweep "$WORK/dry.out" --
sed 's/^/    | /' "$WORK/dry.out"
has "$WORK/dry.out" "[dry] would arm fix/home#11" \
  && ok "a degraded APPROVE pinned to the head and MERGEABLE is selected" \
  || bad "fix/home#11 was not selected"
has "$WORK/dry.out" "[dry] would arm fix/client#21" \
  && ok "a client repo is swept (RULE-2026-10-30-A)" \
  || bad "the client repo's PR was not selected"
has "$WORK/dry.out" "[dry] would arm fix/overlay#31" \
  && ok "a repo opted in only through the private overlay is swept" \
  || bad "the overlay-only repo was not swept"
has "$WORK/dry.out" "skip fix/home#12 (home): the degraded approval is for aaaaaaa, the head is now bbbbbbb" \
  && ok "a moved head is a re-review, not an arm" \
  || bad "fix/home#12 (head moved) was not skipped for the drift"
has "$WORK/dry.out" "skip fix/home#13 (home): degraded approval at the head, but GitHub says mergeable=CONFLICTING" \
  && ok "a CONFLICTING PR is not armed" \
  || bad "fix/home#13 (conflicting) was not skipped on mergeable"
has "$WORK/dry.out" "fix/home#14" \
  && bad "a NON-degraded PR showed up; this sweep only owns what gate 50 parked" \
  || ok "a non-degraded approval is left alone"
has "$WORK/dry.out" "skip fix/home#15 (home): the degraded record reads 'REQUEST CHANGES', not an approval" \
  && ok "a degraded REQUEST CHANGES is not armed" \
  || bad "fix/home#15 was not skipped as not-an-approval"
has "$WORK/dry.out" "ok fix/home#16 (home): already armed" \
  && ok "an already-armed PR is reported, not re-armed" \
  || bad "fix/home#16 was not reported already armed"
has "$WORK/dry.out" "skip fix/home#17 (home): degraded approval at the head, but it is a draft" \
  && ok "a draft is not armed" \
  || bad "fix/home#17 (draft) was not skipped"
has "$WORK/dry.out" "fix/home#18" \
  && bad "a PR with no record showed up" \
  || ok "a PR with no verdict record is left alone"
grep -q 'pr merge' "$WORK/gh-calls" \
  && bad "THE DEFECT: --dry called gh pr merge: $(grep 'pr merge' "$WORK/gh-calls" | head -2 | tr '\n' ' ')" \
  || ok "--dry never calls gh pr merge"
# 5 repos: home, client, overlay, archive, drifted (off is never a candidate).
# 11 PRs: home 8, client 1, overlay 1, drifted 1 (the archive is never listed).
# 9 degraded: home 11-13 and 15-17, client 21, overlay 31, drifted 61.
# 4 selected: 11, 16 (already armed), 21, 31. drifted 61 fails before selection.
has "$WORK/dry.out" "-- dry: 5 dispatch-enabled repo(s), 1 excluded as archived, 0 unreadable; 11 open PR(s), 9 with a degraded record; 4 selected (1 already armed, 3 would arm); 1 failed" \
  && ok "the summary counts add up (5 repos, 11 PRs, 9 degraded, 4 selected, 3 would arm, 1 failed)" \
  || bad "the summary line is wrong: $(grep '^-- ' "$WORK/dry.out")"
[ "$(cat "$WORK/dry.out.rc")" = "2" ] \
  && ok "a failed PR (the drifted checkout) makes the run exit 2, not a clean 0" \
  || bad "exit $(cat "$WORK/dry.out.rc"), want 2 (one PR failed the cwd check)"

echo
echo "== 2. the repo set is the dispatcher's own =="
has "$WORK/dry.out" "fix/off" \
  && bad "THE DEFECT: a repo with dispatch.enabled false was swept" \
  || ok "a repo with dispatch.enabled false is never swept"
grep -q -- "-R fix/off " "$WORK/gh-calls" \
  && bad "gh was asked about the disabled repo" \
  || ok "gh was never asked about the disabled repo"

echo
echo "== 3. the archived engagement is never read (RULE-2026-10-23-B) =="
has "$WORK/dry.out" "EXCLUDED archive: the archive guard refuses it" \
  && ok "the archived repo is reported EXCLUDED" \
  || bad "the archived repo was not reported excluded"
grep -q "fix/archived" "$WORK/gh-calls" \
  && bad "THE DEFECT: gh was called for the archived repo" \
  || ok "gh was never called for the archived repo"
grep -q "ARCHIVED-FIXTURE" "$WORK/guard.log" \
  && ok "the guard was asked about the archived path (the exclusion came from the guard)" \
  || bad "the guard never saw the archived path, so the exclusion came from somewhere else"

echo
echo "== 4. gh bound to the wrong repo from cwd is a failure, never an arm =="
has "$WORK/dry.out" "FAILED fix/drifted#61 (drifted): gh run from $WORK/drifted resolves PR 61 to head 'cccccccccccccccccccccccccccccccccccccccc'" \
  && ok "a checkout whose gh resolves PR 61 to another head is FAILED" \
  || bad "the drifted checkout was not failed"

echo
echo "== 5. --apply arms exactly the selected PRs, from their own checkouts =="
run_sweep "$WORK/apply.out" -- --apply
MERGES="$(grep 'pr merge' "$WORK/gh-calls" | sort)"
WANT="$(printf '%s\tpr merge --auto --squash 11\n%s\tpr merge --auto --squash 21\n%s\tpr merge --auto --squash 31\n' \
  "$HOME_REPO" "$WORK/client" "$WORK/overlay" | sort)"
[ "$MERGES" = "$WANT" ] \
  && ok "gh pr merge --auto ran for 11, 21 and 31 only, each from its own repo" \
  || bad "the arm calls were wrong:
$(printf '%s\n' "$MERGES" | sed 's/^/      got  /')
$(printf '%s\n' "$WANT" | sed 's/^/      want /')"
has "$WORK/apply.out" "ARMED fix/client#21 (client)" \
  && ok "--apply reports each arm" \
  || bad "--apply did not report the client arm"
has "$WORK/apply.out" "4 selected (1 already armed, 3 armed now); 1 failed" \
  && ok "the --apply summary says 3 armed now" \
  || bad "the --apply summary is wrong: $(grep '^-- ' "$WORK/apply.out")"

echo
echo "== 6. a missing guard refuses the whole run =="
mv "$WORK/fakehome/.claude/hooks/ps-archive-deny.sh" "$WORK/guard.away"
run_sweep "$WORK/noguard.out" -- --apply
mv "$WORK/guard.away" "$WORK/fakehome/.claude/hooks/ps-archive-deny.sh"
[ "$(cat "$WORK/noguard.out.rc")" = "3" ] && has "$WORK/noguard.out" "REFUSED: the archive guard" \
  && ok "no guard: exit 3 with REFUSED" \
  || bad "no guard gave exit $(cat "$WORK/noguard.out.rc"): $(head -2 "$WORK/noguard.out")"
[ ! -s "$WORK/gh-calls" ] \
  && ok "no guard: gh was never called" \
  || bad "no guard: gh was still called: $(head -2 "$WORK/gh-calls")"

echo
echo "== 7. a founder bypass in the calling shell does not open the archive =="
run_sweep "$WORK/bypass.out" ALLOW_PS_ARCHIVE=1 -- --dry
grep -q "fix/archived" "$WORK/gh-calls" \
  && bad "THE DEFECT: with ALLOW_PS_ARCHIVE=1 exported, the sweep read the archived repo" \
  || ok "ALLOW_PS_ARCHIVE=1 in the caller's env is stripped before the guard runs"

echo
echo "== 8. MUTATIONS: each archive refusal has to be load-bearing =="
# Each mutant is the shipped sweep with ONE refusal removed, run beside copies
# of the two libs it sources. A refusal whose removal changes nothing is
# decoration, and the case that claims it would be green for no reason.
M1D="$WORK/mut-both"; mkdir -p "$M1D"; cp "$SCRIPTS/pr-verdict-lib.sh" "$SCRIPTS/repo-slug-lib.sh" "$M1D/"
sed -e 's/if archived "$path" "$name"; then/if false; then/' \
    -e 's/if archived "$path" "$slug"; then/if false; then/' "$SWEEP" > "$M1D/rearm-degraded-approvals.sh"
if diff -q "$SWEEP" "$M1D/rearm-degraded-approvals.sh" >/dev/null; then
  bad "the guard mutation did not apply"
else
  SWEEP_UNDER_TEST="$M1D/rearm-degraded-approvals.sh" run_sweep "$WORK/mut1.out" -- --dry
  grep -q "fix/archived" "$WORK/gh-calls" \
    && ok "mutant KILLED: without the guard calls, gh reads the archived repo (case 3 would go red)" \
    || bad "THE MUTANT SURVIVED: the archived repo stayed unread with no guard call, so case 3 proves nothing"
fi
M2D="$WORK/mut-env"; mkdir -p "$M2D"; cp "$SCRIPTS/pr-verdict-lib.sh" "$SCRIPTS/repo-slug-lib.sh" "$M2D/"
sed -e 's/env -u ALLOW_PS_ARCHIVE bash "$ARCHIVE_GUARD"/bash "$ARCHIVE_GUARD"/' "$SWEEP" > "$M2D/rearm-degraded-approvals.sh"
if diff -q "$SWEEP" "$M2D/rearm-degraded-approvals.sh" >/dev/null; then
  bad "the bypass-strip mutation did not apply"
else
  SWEEP_UNDER_TEST="$M2D/rearm-degraded-approvals.sh" run_sweep "$WORK/mut2.out" ALLOW_PS_ARCHIVE=1 -- --dry
  grep -q "fix/archived" "$WORK/gh-calls" \
    && ok "mutant KILLED: without env -u, a bypass in the caller's env opens the archive (case 7 would go red)" \
    || bad "THE MUTANT SURVIVED: the bypass strip is not load-bearing, so case 7 proves nothing"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: the re-arm sweep selects exactly what gate 50 parked and never reads the archive"
