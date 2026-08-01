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
    refuse "control-code" "linear-worker.sh differs from the skeleton (${have:0:12} vs ${want:0:12}); run kipi update on this repo first"
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
SETTINGS_REL=".claude/settings.json"
if [ ! -f "$REPO_PATH/$SETTINGS_REL" ]; then
  refuse "hooks" "$REPO_PATH/$SETTINGS_REL is missing, so no hook fires in this repo"
else
  MISSING="$(python3 - "$SKELETON/$SETTINGS_REL" "$REPO_PATH/$SETTINGS_REL" <<'PY' 2>/dev/null
import json, sys
try:
    skel = json.load(open(sys.argv[1])).get("hooks", {})
    repo = json.load(open(sys.argv[2])).get("hooks", {})
except Exception as e:
    print("UNREADABLE:%s" % e)
    sys.exit(0)
# An event present but wired to nothing is the same hole as an absent event.
live = {k for k, v in repo.items() if v}
print(",".join(sorted(set(skel) - live)))
PY
)"
  case "$MISSING" in
    UNREADABLE:*) refuse "hooks" "settings.json could not be parsed (${MISSING#UNREADABLE:})" ;;
    "")           : ;;
    *)            refuse "hooks" "no hooks wired for event(s): $MISSING" ;;
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
  elif ! gh api "repos/$SLUG/branches/$DEFAULT_BRANCH/protection" >/dev/null 2>&1; then
    refuse "branch-protection" "$SLUG@$DEFAULT_BRANCH reports no branch protection; auto-merge would land unreviewed code"
  fi
fi

if [ "$FAILED" -ne 0 ]; then
  printf 'REFUSED %s\n' "$REPO_PATH"
  exit 1
fi
printf 'OK %s\n' "$REPO_PATH"
exit 0
