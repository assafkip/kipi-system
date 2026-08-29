#!/usr/bin/env bash
# THE ONE PLACE a GitHub owner/repo slug is derived, and the one place a review
# artifact path is built (ASK-738).
#
# WHY THIS FILE EXISTS
# --------------------
# `gh` resolves its repository from the PROCESS WORKING DIRECTORY and ignores
# every path variable this fleet carries. Measured 2026-08-13:
#
#   cwd = kipi-system checkout, TARGET_REPO=<other>  ->  assafkip/kipi-system
#   cwd = <other>                                    ->  assafkip/<other>
#
# kipi-dispatch.sh:205 does `cd "$REPO"` and never leaves, so an unqualified `gh`
# anywhere in the dispatched chain answers about the HOME repo while `git -C`
# does the work in the target. Three call sites did exactly that, and the worst
# of them (pr-review-agent.sh) would review the wrong repository's code and post
# a verdict and a commit status on it.
#
# The fix is `-R <owner>/<repo>` on every call. The reason it lives in a lib
# rather than at each call site: sp-421fa27d already records ONE duplicated
# derivation in this codebase (project-name, split between linear-worker.sh and
# spillover-promote.py). A second copy of a rule about which repository an
# unattended self-merging agent may act on is not a style problem. Every caller
# reads the answer from here.
#
# ORDER OF AUTHORITY, and why it is this order:
#   1. the registry row's dispatch.expected_remote -- the PIN. repo-preflight.sh
#      already refuses to enter any repo whose row does not carry it, so for
#      every cross-repo target this is always the answer. Deriving from the pin
#      rather than from the repo's own origin means a re-pointed or spoofed local
#      origin cannot aim an agent at a repository the registry never named.
#   2. the repo's own configured origin -- the FALLBACK, and it exists for
#      exactly one case: the dispatcher's OWN checkout, which fleet_candidates
#      emits with an empty expected_remote and which carries no registry row.
#      Refusing there would break the only repo this loop runs in today.
#      It is still derived from the TARGET PATH, never from cwd, so it does not
#      reintroduce the defect.
#
# `git config --get remote.origin.url`, NOT `git remote get-url origin`:
# get-url APPLIES url.<base>.insteadOf rewriting, so on a box that rewrites
# github.com to a mirror it returns the mirror path and no slug forms. Measured
# in this repo's own test fixture, which uses insteadOf for local transport.

# slug_from_remote <remote-url> -> owner/repo, or empty
# Handles the two forms git remotes actually take here. Empty output means "no
# slug", and every caller must treat that as "do not scope", never as a default.
slug_from_remote() {
  local u="${1:-}" s=""
  case "$u" in
    git@*:*)            s="${u#*:}" ;;
    ssh://*|https://*|http://*)
                        s="${u#*://}"; s="${s#*@}"; s="${s#*/}" ;;
    *)                  s="" ;;
  esac
  s="${s%.git}"
  s="${s%/}"
  # An owner/repo has exactly one slash. Anything else is a path or a malformed
  # URL, and guessing at it is how a query lands on the wrong repository.
  case "$s" in
    */*/*) s="" ;;
    */*)   : ;;
    *)     s="" ;;
  esac
  printf '%s' "$s"
}

# _registry_remote_for <repo-path> <registry-path> -> the pinned expected_remote
# Quoted heredoc + argv, never `python3 -c "..."` inside $( ): the inline form
# broke bash parsing at RUNTIME ONLY elsewhere in this tree (repo-preflight.sh
# carries the same scar), and a path with an apostrophe in it is enough to do it.
_registry_remote_for() {
  [ -f "${2:-}" ] || return 0
  python3 - "$1" "$2" <<'PY' 2>/dev/null
import json, os, sys
want = os.path.realpath(sys.argv[1])
try:
    data = json.load(open(sys.argv[2]))
except Exception:
    raise SystemExit(0)          # unreadable registry means "no pin", never a guess
entries = data.get("instances", data) if isinstance(data, dict) else data
for e in entries if isinstance(entries, list) else []:
    if not isinstance(e, dict):
        continue
    p = e.get("path")
    if not p:
        continue
    try:
        if os.path.realpath(p) != want:
            continue
    except Exception:
        continue
    d = e.get("dispatch")
    if isinstance(d, dict) and d.get("expected_remote"):
        print(d["expected_remote"])
    break
PY
}

# slug_for_repo <repo-path> [registry-path] -> owner/repo, or empty
slug_for_repo() {
  local repo="${1:-}" reg="${2:-${KIPI_SLUG_REGISTRY:-}}" remote="" slug=""
  [ -n "$repo" ] || return 0
  [ -d "$repo" ] || return 0
  remote="$(_registry_remote_for "$repo" "$reg")"
  slug="$(slug_from_remote "$remote")"
  # FALL BACK ON A PIN THAT YIELDS NO SLUG, not merely on an absent pin. A row
  # whose expected_remote is malformed -- or a registry read that returned
  # something that is not a remote at all -- would otherwise leave the slug empty,
  # and an empty slug means every gh call silently reverts to cwd binding. That
  # is the exact defect this lib exists to close, reappearing as a quiet
  # degradation instead of a loud one. Caught by this repo's own worker
  # reproducer, where a stubbed python3 made the registry read return JSON.
  if [ -z "$slug" ]; then
    remote="$(git -C "$repo" config --get remote.origin.url 2>/dev/null)"
    slug="$(slug_from_remote "$remote")"
  fi
  printf '%s' "$slug"
}

# gh_repo_args <slug> -> the argv fragment to splice into a gh call
#
# UNQUOTED WORD-SPLITTING IS THE POINT and it is why this returns a string rather
# than an array: bash 3.2 (what /bin/bash is on macOS) treats an EMPTY array's
# "${a[@]}" as unbound under `set -u`, so an array-based helper dies on exactly
# the no-slug path. Callers splice $(gh_repo_args "$SLUG") unquoted. A slug is
# [-.\w]+/[-.\w]+ by construction above, so it can never contain whitespace or a
# glob character.
gh_repo_args() {
  [ -n "${1:-}" ] || return 0
  printf -- '-R %s' "$1"
}

# --- artifact keying --------------------------------------------------------
# Review artifacts used to be keyed `pr-<number>` in ONE shared state dir, so
# PR #42 in kipi-system and PR #42 in a client repo were the same three paths:
# the verdict record the gates read, the review prose the round counter globs,
# and the detached worktree the reviewer reads files from. The second review
# overwrote the first, and a gate could read an APPROVE earned by a different
# repository's code.
#
# `/` -> `__` because these are path SEGMENTS. Keeping the slash would make the
# owner a directory level, which silently changes what every `find` and glob in
# the suite matches.

# artifact_key <slug> <pr> -> the basename stem for this repo's PR
artifact_key() {
  local slug="${1:-}" pr="${2:-}"
  if [ -z "$slug" ]; then
    printf 'pr-%s' "$pr"          # no slug: legacy shape, and it is the home repo
    return 0
  fi
  printf '%s__pr-%s' "$(printf '%s' "$slug" | tr '/' '_' | tr -c 'A-Za-z0-9._-' '_')" "$pr"
}

# verdict_record_path <dir> <slug> <pr> -> the path to READ
#
# WRITES ALWAYS USE THE REPO-KEYED PATH (verdict_record_write_path). Reads fall
# back to the legacy `pr-<N>.verdict.json` when the repo-keyed file does not
# exist, for one bounded reason: ~90 records under ~/.config/kipi/pr-reviews/
# predate this change and all belong to the home repo. Dropping them would make
# every open PR look unreviewed and trigger a re-review round on each. The
# fallback is read-only and lives HERE, in the single resolver, so there is still
# exactly one writer and one reader of this path shape.
verdict_record_path() {
  local dir="${1:-}" slug="${2:-}" pr="${3:-}" keyed=""
  keyed="$dir/$(artifact_key "$slug" "$pr").verdict.json"
  if [ -f "$keyed" ]; then printf '%s' "$keyed"; return 0; fi
  local legacy="$dir/pr-$pr.verdict.json"
  if [ -f "$legacy" ]; then printf '%s' "$legacy"; return 0; fi
  printf '%s' "$keyed"
}

verdict_record_write_path() {
  printf '%s/%s.verdict.json' "${1:-}" "$(artifact_key "${2:-}" "${3:-}")"
}

# review_tree_path <state-dir> <slug> <pr>
# One detached worktree per (repo, PR). Sharing one path across repos meant a
# tree re-checked out to whichever repo asked last, which is a review reading the
# wrong repository's files with the right-looking provenance.
review_tree_path() {
  printf '%s/review-trees/%s' "${1:-}" "$(artifact_key "${2:-}" "${3:-}")"
}
