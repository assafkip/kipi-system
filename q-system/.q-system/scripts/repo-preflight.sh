#!/usr/bin/env bash
# Decide whether an autonomous dispatcher may ENTER a repo. Exit 0 = may enter.
# Any non-zero = refuse, with every failed check named on stdout.
#
# Usage: repo-preflight.sh <repo-path> <expected-remote>
#
# WHY THIS EXISTS (finding-8, a BLOCKER on prd-terminal-state-redrive-2026-08-01)
# ------------------------------------------------------------------------------
# One dispatch job exists fleet-wide, bound to the kipi-system checkout, so 18
# ready owner:sana issues across 14 projects are skipped as out-of-repo every
# cycle. The fix -- let the dispatcher iterate the registry -- aims an unattended
# loop that runs agents, pushes branches and arms auto-merge at Alice,
# Prodigy_Gold and Pure_spectrum_Q, which are CLIENT repos.
#
# Codex reviewed the first design and called opt-in plus a project filter
# inadequate protection. That is the correct call and it is worth stating why,
# because the two look similar: opt-in records which repos a human MEANT to allow,
# once, at registry-edit time. It says nothing about whether entering one is safe
# NOW -- whether the control code there is current, whether main is protected,
# whether somebody has uncommitted work in the tree this minute. Consent is not a
# safety check. This script is the safety check.
#
# FAIL CLOSED. THIS IS THE OPPOSITE POSTURE FROM stale_check().
# stale_check() in kipi-dispatch.sh deliberately fails OPEN: a failed git fetch
# logs and proceeds, because a network blip must not wedge the whole loop. That is
# right for a check on our OWN checkout. It is wrong here. "I could not determine
# whether main is protected" is not permission to push to a client's repo. Every
# unanswerable question in this file refuses. Two different safe directions, chosen
# per blast radius, and mixing them up is how a gate quietly becomes a filter.
#
# NO BYPASS SURFACE, BY CONSTRUCTION. There is no --force, no KIPI_SKIP_*, and no
# registry field that exempts a repo. `gh` is taken from PATH rather than from an
# override variable specifically so that no documented knob exists to aim the
# credential and branch-protection checks at /bin/true. A skippable safety gate on
# a client repo is worse than no gate, because it reads as protection to everyone
# downstream of it.
set -uo pipefail

REPO_PATH="${1:-}"
EXPECTED_REMOTE="${2:-}"

# The skeleton this script SHIPPED FROM, derived from the script's own location
# rather than from $PWD or an env var. The control-code check compares an
# instance's copy against this one, so the reference has to follow the code; a
# $PWD-derived root would compare a repo against itself whenever the caller
# happened to be standing in it.
SKELETON="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

FAILED=0
refuse() { FAILED=1; printf 'FAIL %s: %s\n' "$1" "$2"; }

[ -n "$REPO_PATH" ] || { printf 'FAIL usage: repo-preflight.sh <repo-path> <expected-remote>\n'; exit 2; }
[ -d "$REPO_PATH" ] || { printf 'FAIL repo-path: %s is not a directory\n' "$REPO_PATH"; exit 1; }

# --- 0. client engagement repo -------------------------------------------
# Founder decision 2026-08-13, verbatim: "no. unattended agents should not reach
# a client repo."
#
# THIS REFUSES EVEN WHEN THE ROW IS OPTED IN, WHICH IS THE WHOLE POINT.
# `dispatch.enabled` defaulting to absent is a DEFAULT, and a default is not a
# refusal: it records that nobody has switched a repo on yet, and it evaporates
# the moment anyone -- a person editing the registry, or some later script that
# opts rows in automatically -- writes `true`. What is on the other side of that
# edit is a self-merging loop (converge, code, PR, review rounds, auto-merge) with
# no human in the path, pointed at work the founder is accountable to a CLIENT
# for, where there is a person on the other end and no undo. So this is checked
# ahead of the kill-switch and ahead of every network call: it is the one refusal
# that no state of the target repo, and no registry field, can argue with.
#
# DERIVED FROM PATH SHAPE, NEVER FROM A LIST OF CLIENTS. Measured 2026-08-13
# against instance-registry.json: 12 of 25 rows sit under an engagement root.
# Naming those twelve here would be a list that goes stale the day the thirteenth
# client is onboarded -- and the failure mode of a stale allowlist is that the new
# client is the one that gets dispatched into. The shape is the fact: the founder's
# own systems live at <root>/projects/<thing> under roots he owns, and client
# engagements live under exactly these two. A repo added under one of them next
# month is refused with no code change, which is the only property that makes this
# hold over time.
#
# NOT AN ENV VAR, NOT A REGISTRY FIELD. Same reason `gh` is taken from PATH and the
# dispatcher hardcodes $PREFLIGHT off $REPO: a knob here would be a documented way
# to aim the client-repo gate at nothing while every log line still read normally.
ENGAGEMENT_ROOTS="consulting intel"

# BOTH THE REGISTRY'S PATH AND ITS RESOLVED TARGET ARE TESTED, AND EITHER ONE
# MATCHING REFUSES. A symlink is the obvious way this check gets walked around by
# accident: a row pointing at an innocent-looking path that resolves into an
# engagement dir, or an engagement-shaped path that resolves elsewhere. Refusing on
# either side means the answer does not depend on which of the two a later reader
# happens to think is "the" path. Fail closed, like every other item in this file.
RESOLVED_PATH="$(cd "$REPO_PATH" 2>/dev/null && pwd -P)" || RESOLVED_PATH=""
for _root in $ENGAGEMENT_ROOTS; do
  for _cand in "$REPO_PATH" "$RESOLVED_PATH"; do
    [ -n "$_cand" ] || continue
    case "$_cand" in
      # THE ROOT ITSELF, NOT ONLY WHAT IS NESTED UNDER IT (ASK-754).
      # This case previously PASSED, and the test suite asserted that it should:
      # the earlier reading of the founder's wording was "the engagement instances
      # NESTED UNDER consulting/projects/*", so <root>/projects/<x> refused and
      # <root> did not. Measured 2026-08-14 against the repo that reading lets in,
      # the ASK_AI_consultant row, whose path IS the consulting engagement root:
      #   - `git ls-files clients/` -> 12 TRACKED files under clients/alma,
      #     clients/portant, clients/restaurent. Client material is in this repo's
      #     own history, so an agent-authored PR here is a client-facing diff.
      #   - projects/ holds all 11 engagement repos as nested SEPARATE git repos,
      #     and the root tracks 0 files under projects/ -- so check 5 (dirty) is
      #     structurally blind to them while the agent still has filesystem reach.
      #   - q-consult/ is 998 tracked files: the LIVE social publishing engine.
      # The root is not a neutral parent, it is the container of every engagement
      # plus a live outbound path. Refusing the nested repos while admitting the
      # directory that holds them is a gate with a door beside it.
      #
      # WHY THIS WAS ONLY LATENT: preflight already refused this repo today, but on
      # control-code/hooks/dirty/branch-protection -- every one of them curable by a
      # `kipi update`, a commit, and a protection toggle. An incidental refusal is
      # not a rule, and it evaporates the day somebody tidies the repo.
      #
      # STILL DERIVED FROM SHAPE, STILL NO LIST. Same ENGAGEMENT_ROOTS constant,
      # one extra glob. It discriminates: only a path whose LAST component is an
      # engagement root matches, so the founder's own persona and product roots are
      # untouched -- which the OWNPROJ and NEARMISS cases both assert.
      #
      # NO ABSOLUTE HOME PATHS AND NO INSTANCE NAMES IN THIS COMMENT. The skeleton
      # sweep in validate-separation.py greps every q-system/ file for an absolute
      # home-directory prefix and for a fleet instance name, and this file ships to
      # every instance. The first draft of this comment spelled out both and turned
      # CI red; the second spelled them out again while explaining not to, because a
      # text check cannot tell a rule from a mention of the rule. Describe, do not
      # quote.
      # TWO SHAPES, TWO REASONS, BECAUSE THE REASON IS READ BY A HUMAN. The root and
      # the repos nested under it are both refused, but they are refused for
      # different facts, and one message cannot state both without lying about one
      # of them. Codex round 2 caught the first cut telling the founder that
      # <root> is "under <root>/projects/", which is false and unfalsifiable-looking
      # in a log. This line is what he reads in the daily digest's "tried, could not
      # be worked" section, so a refusal he cannot tell from an empty queue -- or one
      # that misdescribes itself -- is the defect this whole change is about.
      */"$_root")
        printf 'FAIL client-repo: %s IS the %s engagement root; it holds the client engagement repos plus client material of its own, so unattended dispatch is not allowed there, even when dispatch.enabled is true -- a supervised founder-initiated run is the way in\n' "$REPO_PATH" "$_root"
        printf 'REFUSED %s\n' "$REPO_PATH"
        exit 1 ;;
      */"$_root"/projects/*)
        printf 'FAIL client-repo: %s is a client engagement repo (under %s/projects/); unattended dispatch is not allowed there, even when dispatch.enabled is true -- a supervised founder-initiated run is the way in\n' "$REPO_PATH" "$_root"
        printf 'REFUSED %s\n' "$REPO_PATH"
        exit 1 ;;
    esac
  done
done

# --- 1. kill-switch -------------------------------------------------------
# Checked FIRST and short-circuits everything, including the network calls. A
# founder or a client dropping this file is saying "stay out of here", and the
# correct response to that is to stop, not to finish auditing the repo first. One
# `touch` halts dispatch into a repo with no code change, no registry edit and no
# deploy -- which is the property you want at 2am.
if [ -f "$REPO_PATH/.kipi-no-dispatch" ]; then
  printf 'FAIL kill-switch: %s/.kipi-no-dispatch is present, this repo is off limits\n' "$REPO_PATH"
  exit 1
fi

# --- 2. control-code ------------------------------------------------------
# The dispatcher would run the WORKER COPY THAT LIVES IN THE TARGET REPO, and
# `kipi update` is manual, so an instance can be arbitrarily far behind. Running a
# stale copy means running control code nobody reviewed, on a loop that merges its
# own PRs -- an instance frozen before the stale-checkout refusal or the
# sensitive-path guard has neither. Byte equality against the skeleton is a blunt
# rule on purpose: "close enough" has no meaning for code that self-merges.
WORKER_REL="q-system/.q-system/scripts/linear-worker.sh"
if [ ! -f "$REPO_PATH/$WORKER_REL" ]; then
  refuse "control-code" "$REPO_PATH/$WORKER_REL is missing, the repo carries no worker to run"
elif [ ! -f "$SKELETON/$WORKER_REL" ]; then
  refuse "control-code" "the skeleton reference $SKELETON/$WORKER_REL is missing, so drift cannot be judged"
else
  have="$(shasum -a 256 "$REPO_PATH/$WORKER_REL" 2>/dev/null | awk '{print $1}')"
  want="$(shasum -a 256 "$SKELETON/$WORKER_REL"  2>/dev/null | awk '{print $1}')"
  if [ -z "$have" ] || [ -z "$want" ]; then
    refuse "control-code" "could not hash the worker on both sides, so drift is unknown"
  elif [ "$have" != "$want" ]; then
    # THE REMEDY NAMED HERE USED TO BE THE FLEET UPDATER, AND THAT WAS WRONG
    # (ASK-755). The updater is a fleet-wide rsync WITH a delete flag: to fix one
    # file in one repo it walks every registered instance and can remove anything
    # on the way (2026-08-07: voicekit deleted from 19 instances). A refusal that
    # names a tool with a blast radius three orders of magnitude wider than the
    # defect is an invitation to overcorrect at 2am. control-file-propagate.py
    # does the same hash classification for ONE file in ONE repo, copy only, and
    # refuses anything it cannot prove came from this skeleton.
    refuse "control-code" "linear-worker.sh differs from the skeleton (${have:0:12} vs ${want:0:12}); fix with: python3 $SKELETON/q-system/.q-system/scripts/control-file-propagate.py --target $REPO_PATH --file $WORKER_REL --apply"
  fi
fi

# --- 3. hooks -------------------------------------------------------------
# The enforcement layer is hooks, not prose (the repo's own rule: a prompt cannot
# enforce behaviour). A repo missing a hook EVENT the skeleton wires is running an
# agent with fewer blocking guards than the machine dispatching into it.
#
# Compared against the SKELETON'S OWN settings rather than a hand-written list of
# event names, for the same reason Piece B enumerates exits from source: a hand
# list cannot notice the day a seventh event class is added.
#
# THE REFERENCE IS settings-template.json, NOT THE SKELETON'S RUNTIME settings.json
# (ASK-755). Those two files are not the same claim. `kipi update` builds every
# instance's settings.json from the TEMPLATE; the skeleton's own runtime file is
# what the skeleton runs on itself, and it deliberately carries hooks that must
# never ship -- settings-template-sync-check.py is SKELETON_ONLY by its own
# design, because it compares the two settings files and an instance has no
# template to compare against.
#
# Measured 2026-08-14, both opted-in repos: against the runtime file each was
# "missing" exactly settings-template-sync-check.py, and against the template each
# was at FULL parity. So this check was unsatisfiable for every instance in the
# fleet at once -- no `kipi update` run could ever have cleared it, because the
# thing it demanded is the one hook update refuses to ship. A gate nothing can
# pass is not strict, it is broken, and it reads as a fleet-wide instance defect.
#
# NOT A WEAKENING, AND THE NUMBERS ARE THE ARGUMENT. The two guard sets are 41 and
# 41. Switching the reference DROPS one requirement (settings-template-sync-check.py,
# which can never be satisfied) and ADDS one (instance-automation-guard.py, which
# is FLEET_ONLY: it ships to instances and the skeleton self-detects and no-ops, so
# the old reference could not require it and the new one does). The hook EVENT sets
# of the two files are identical, so nothing changes there.
SETTINGS_REL=".claude/settings.json"
# Fall back to the runtime file when no template exists, so a skeleton that has
# not adopted the template still gets a comparison rather than a silent pass.
SKEL_SETTINGS="$SKELETON/settings-template.json"
[ -f "$SKEL_SETTINGS" ] || SKEL_SETTINGS="$SKELETON/$SETTINGS_REL"
if [ ! -f "$REPO_PATH/$SETTINGS_REL" ]; then
  refuse "hooks" "$REPO_PATH/$SETTINGS_REL is missing, so no hook fires in this repo"
else
  MISSING="$(python3 - "$SKEL_SETTINGS" "$REPO_PATH/$SETTINGS_REL" "$SKELETON" "$REPO_PATH" <<'PY' 2>/dev/null
import json, sys
try:
    skel = json.load(open(sys.argv[1])).get("hooks", {})
    repo = json.load(open(sys.argv[2])).get("hooks", {})
except Exception as e:
    print("UNREADABLE:%s" % e)
    sys.exit(0)
# An event present but wired to nothing is the same hole as an absent event.
# EVENT NAMES ARE NOT PARITY (codex finding-3). A target that keeps a nonempty
# hook under every event while dropping a blocking guard still had every event
# name present, so the first version of this passed it. What is being claimed is
# that the guards the skeleton runs also run there, so compare the SCRIPTS.
import re
def scripts(h):
    out = set()
    for arr in h.values():
        for matcher in arr or []:
            for hk in matcher.get("hooks", []) or []:
                for m in re.findall(r"[\w.-]+\.(?:py|sh)", hk.get("command", "") or ""):
                    out.add(m)
    return out
missing_events = sorted(set(skel) - {k for k, v in repo.items() if v})
missing_scripts = sorted(scripts(skel) - scripts(repo))
# A NAME IS NOT AN EXECUTABLE. Comparing basenames pulled out of settings.json
# passed a repo that copied settings.json and none of the guard files -- the
# green fixture in this test suite was itself that shape. Resolve each guard the
# skeleton wires and require the file to actually be present in the target.
import os
# A GUARD IS ABSENT ONLY IF NO SKELETON PATH FOR IT EXISTS IN THE TARGET.
#
# The previous rule took hits[:1] -- the first os.walk hit anywhere under the
# skeleton -- and demanded THAT exact relative path in the instance. The skeleton
# root also holds PR review worktrees (.pr31rev/, .pr25rev/) and template-repo/,
# none of which ship to any instance, so the first hit routinely resolved to a
# path no instance could ever have.
#
# Measured 2026-08-14 against both dispatch-enabled repos by replicating this block
# verbatim: each reported 36 guards absent, 35 of them PHANTOM -- present in the
# instance at a different skeleton path, e.g. a lint script resolving to its copy
# inside a PR review worktree instead of its shipped location. Exactly ONE was
# real. os.walk order is not stable across machines either, so the same repo could
# pass or fail depending on directory iteration.
#
# NO INSTANCE NAMES ABOVE, DELIBERATELY. This file ships to every instance, so
# validate-separation Gate 1.2 sweeps it for live instance names and the first cut
# of this comment named the two repos and turned CI red. The measurement is the
# durable part; the names belong in the PR body. A text check cannot tell a rule
# from a mention of one, which is why this warning names no repo either.
#
# This is NOT a loosening. The check still demands the guard file exist in the
# target; it stops demanding it exist at a path that only ever existed inside a
# scratch worktree. After this fix both repos still REFUSE -- on the one real
# absence -- which is the proof it did not go soft.
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', '.pytest_cache',
             'template-repo', 'worktrees'}


def _shipping(dirname):
    """Directories that never reach an instance, so never define the guard path."""
    if dirname in SKIP_DIRS:
        return False
    # Review/scratch worktrees this repo creates at its own root. `.q-system` is a
    # real shipped directory, so dotted names are filtered by prefix, not wholesale.
    for junk in ('.pr', '.wt-', '.fable-wt', '.sana-tmp'):
        if dirname.startswith(junk):
            return False
    return True


skel_root, repo_root = sys.argv[3], sys.argv[4]
absent = []
for rel in sorted(scripts(skel)):
    hits = []
    for base, dirs, files in os.walk(skel_root):
        dirs[:] = [d for d in dirs if _shipping(d)]
        if rel in files:
            hits.append(os.path.relpath(os.path.join(base, rel), skel_root))
    # Sorted so the reported path is deterministic rather than walk-order dependent.
    hits.sort()
    if hits and not any(os.path.isfile(os.path.join(repo_root, h)) for h in hits):
        absent.append(hits[0])
parts = []
if missing_events:
    parts.append("events=" + "/".join(missing_events))
if missing_scripts:
    parts.append("guards=" + "/".join(missing_scripts[:6]) + ("..." if len(missing_scripts) > 6 else ""))
if absent:
    parts.append("absent=" + "/".join(os.path.basename(a) for a in absent[:6]) + ("..." if len(absent) > 6 else ""))
print(";".join(parts))
PY
)"
  case "$MISSING" in
    UNREADABLE:*) refuse "hooks" "settings.json could not be parsed (${MISSING#UNREADABLE:})" ;;
    "")           : ;;
    *)            refuse "hooks" "hook parity with the skeleton is incomplete: $MISSING" ;;
  esac
fi

# --- 4. remote ------------------------------------------------------------
# The registry row must PIN the remote, and origin must match it exactly.
#
# ABSENCE IS NOT CONSENT: a row with no pinned remote refuses rather than trusting
# whatever origin happens to say. Otherwise a mistyped path, a repo moved on disk,
# or a re-pointed origin silently redirects an agent's push to somebody else's
# GitHub repo, and every log line still reads normally.
if [ -z "$EXPECTED_REMOTE" ]; then
  refuse "remote" "the registry row pins no expected_remote; an unpinned repo is never entered"
else
  ACTUAL_REMOTE="$(git -C "$REPO_PATH" remote get-url origin 2>/dev/null)"
  if [ -z "$ACTUAL_REMOTE" ]; then
    refuse "remote" "no origin remote is configured in $REPO_PATH"
  elif [ "$ACTUAL_REMOTE" != "$EXPECTED_REMOTE" ]; then
    refuse "remote" "origin is $ACTUAL_REMOTE but the registry pins $EXPECTED_REMOTE"
  fi
fi

# --- 5. dirty -------------------------------------------------------------
# Uncommitted work in a client repo belongs to a human. An agent that branches,
# commits and opens a PR from that tree sweeps their work-in-progress into its own
# diff, and the first anyone hears about it is a client-facing PR.
if ! git -C "$REPO_PATH" rev-parse --git-dir >/dev/null 2>&1; then
  refuse "dirty" "$REPO_PATH is not a git repository"
else
  PORCELAIN="$(git -C "$REPO_PATH" status --porcelain 2>/dev/null)"
  if [ -n "$PORCELAIN" ]; then
    refuse "dirty" "working tree has $(printf '%s\n' "$PORCELAIN" | grep -c .) uncommitted change(s); an agent branch would capture them"
  fi
fi

# --- slug, for the two GitHub-side checks ---------------------------------
# Derived from the PINNED remote, never from the repo's own origin. If a repo's
# origin has been re-pointed, check 4 has already refused -- but deriving the API
# target from the pin as well means a spoofed local origin can never aim these
# queries at a repo the registry did not name.
slug_of() {
  case "$1" in
    git@*:*)          printf '%s' "${1#*:}" ;;
    https://*|http://*) printf '%s' "${1#*://*/}" ;;
    *)                printf '%s' "" ;;
  esac
}
SLUG="$(slug_of "$EXPECTED_REMOTE")"; SLUG="${SLUG%.git}"

# --- 6. credentials -------------------------------------------------------
# gh is what pushes the branch and arms auto-merge. Discovering the token is dead
# AFTER an agent has run for twenty minutes wastes the work; discovering it can
# see a repo it should not is worse.
if ! command -v gh >/dev/null 2>&1; then
  refuse "credentials" "gh is not on PATH, so no push or auto-merge could succeed"
elif ! gh auth status >/dev/null 2>&1; then
  refuse "credentials" "gh auth status failed; the token is missing or expired"
elif [ -z "$SLUG" ]; then
  refuse "credentials" "could not derive an owner/repo slug from '$EXPECTED_REMOTE'"
elif ! gh repo view "$SLUG" >/dev/null 2>&1; then
  refuse "credentials" "the current gh token cannot see $SLUG"
fi

# --- 7. branch-protection -------------------------------------------------
# THE ONE THAT MATTERS MOST FOR A CLIENT REPO. This loop arms auto-merge on its
# own PRs. On an unprotected default branch that means agent-authored code lands
# in a client's main with no review and no required check -- the whole review
# apparatus becomes decorative the moment protection is off.
#
# Unanswerable REFUSES (fail closed). A 404 from the protection endpoint is what
# GitHub returns for "no protection configured", and it is indistinguishable here
# from a permissions problem. Both mean the same thing for our purposes: we cannot
# show that main is protected, so we do not enter.
if [ -z "$SLUG" ]; then
  refuse "branch-protection" "no slug to query (see the remote check)"
elif ! command -v gh >/dev/null 2>&1; then
  refuse "branch-protection" "gh is not on PATH, so protection cannot be confirmed"
else
  DEFAULT_BRANCH="$(gh api "repos/$SLUG" --jq .default_branch 2>/dev/null | tr -d '[:space:]')"
  if [ -z "$DEFAULT_BRANCH" ]; then
    refuse "branch-protection" "could not read the default branch for $SLUG"
  else
    PROT_JSON="$(gh api "repos/$SLUG/branches/$DEFAULT_BRANCH/protection" 2>/dev/null)"
    if [ -z "$PROT_JSON" ]; then
      refuse "branch-protection" "$SLUG@$DEFAULT_BRANCH reports no branch protection; auto-merge would land unreviewed code"
    else
      # PRESENCE OF PROTECTION IS NOT A REVIEW GATE. The first cut accepted any
      # successful response, so a branch protected only against force-pushes
      # passed -- while the worker arms auto-merge and lands code immediately.
      # "Protected" is not the property being relied on; "a human or a check has
      # to pass before this merges" is. Parse for that specifically.
      # QUOTED HEREDOC + ENV, NOT python3 -c "...". The inline -c form sat inside
      # $( ) and broke bash parsing at RUNTIME ONLY -- syntax checks passed and the
      # failure showed up as "bad substitution" the first time a fixture reached
      # this branch. The heredoc is quoted so nothing expands, and the payload
      # travels in the environment instead of through another layer of quotes.
      PROT_GATES="$(PROT_JSON="$PROT_JSON" python3 - <<'PY' 2>/dev/null
import json, os
raw = os.environ.get("PROT_JSON") or ""
try:
    d = json.loads(raw)
except Exception:
    print("UNPARSEABLE"); raise SystemExit(0)
g = []
# Not a presence test and not truthiness. GitHub returns this key with NULL when
# review requirements are disabled, so a presence test reads "reviews are off" as
# a review gate. Truthiness was the earlier cut and it wrongly rejected a real
# gate whose object was empty. Only an explicit is-not-None test gets both right.
if d.get("required_pull_request_reviews") is not None:
    g.append("reviews")
rsc = d.get("required_status_checks") or {}
if rsc.get("contexts") or rsc.get("checks"):
    g.append("checks")
# AN ERROR BODY IS NOT A PROTECTION OBJECT (ASK-755).
#
# NO APOSTROPHE AND NO BACKTICK BELOW THIS LINE. This heredoc sits inside $( ),
# and bash tracks quotes while scanning for the closing paren even though the
# heredoc is quoted -- one apostrophe in a PYTHON COMMENT here took the whole
# script to "unexpected EOF while looking for matching quote" at line 429, with
# the error pointing 200 lines away from the character that caused it. The file
# already carries this scar once, a few lines up, for the inline -c form.
#
# The gh CLI prints the GitHub JSON error to STDOUT and its own message to
# stderr, and the caller discards stderr -- so a refused request arrived here as
# a perfectly parseable dict with
# no protection keys in it, and came out the far end as "protected but requires
# NO review and NO status check". That sentence is FALSE and it is the expensive
# kind of false: it names a fixable GitHub setting, so it sent a founder-directed
# run hunting a toggle. Measured on both opted-in repos, which are PRIVATE on a
# personal plan: GET .../protection AND GET .../rulesets both return
#   403 {"message": "Upgrade to GitHub Pro or make this repository public..."}
# There is no setting to change. The refusal was right; only its reason was
# invented. Detected by SHAPE, not by a status allowlist -- any body carrying a
# message and none of the protection keys is an error, whatever its code.
if not g and "message" in d and not any(
    k in d for k in ("required_pull_request_reviews", "required_status_checks",
                     "enforce_admins", "url")
):
    print("APIERROR:%s" % str(d.get("message", "")).replace("\n", " ")[:200])
    raise SystemExit(0)
print(",".join(g))
PY
)"
      case "$PROT_GATES" in
        UNPARSEABLE)
          refuse "branch-protection" "the protection response for $SLUG@$DEFAULT_BRANCH could not be parsed" ;;
        APIERROR:*)
          # Still a refusal -- fail closed is the whole posture of this file, and
          # "I could not read the protection" is never permission to enter. What
          # changes is that the reason is now GitHub's own words, so the reader
          # can tell an unset toggle from a plan that has no toggle to set.
          refuse "branch-protection" "GitHub refused the protection query for $SLUG@$DEFAULT_BRANCH: ${PROT_GATES#APIERROR:}" ;;
        "")
          refuse "branch-protection" "$SLUG@$DEFAULT_BRANCH is protected but requires NO review and NO status check; auto-merge would still land code with nothing in its way" ;;
      esac
    fi
  fi
fi

if [ "$FAILED" -ne 0 ]; then
  printf 'REFUSED %s\n' "$REPO_PATH"
  exit 1
fi
printf 'OK %s\n' "$REPO_PATH"
exit 0
