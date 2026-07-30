#!/usr/bin/env bash
# portability-lint.sh -- catch the "green locally, wrong where it runs" defect class.
#
# WHY THIS EXISTS. Three defects in one session (2026-07-30, ASK-221), all the
# same shape: the code was green on the machine it was written on and wrong on
# the machine it actually runs on.
#
#   1. the tree guard derived its root from BASH_SOURCE, so it followed where the
#      CODE lives instead of where the WORK lives, and refused 100% of autonomous
#      reviews (sp-a72a9567)
#   2. two worker tests set PATH=$STUB:$PATH with no `codex` stub, so a TEST
#      reached the real codex CLI and real spend (sp-cb48c3c0)
#   3. `mktemp -t name` works on BSD (macOS) and is REJECTED by GNU mktemp, so
#      the reviewer's body file was never created on the Linux CI runner. 14/14
#      locally, `validate` red on the PR.
#
# THIS REPO STRADDLES TWO KERNELS. The founder's machine is macOS/BSD; the CI
# runner is Linux/GNU; instances run on both. So BOTH directions are real bugs,
# and a lint that only knew one of them would keep half the class.
#
# The individual fixes are each one line. This check is worth more than all three
# because it is the only one that generalises.
#
# THE CLASS IS "ANYTHING THAT DIFFERS ACROSS THE TWO KERNELS", NOT "THE LIST
# BELOW". This started as flag divergences only, because those were the failures I
# had personally hit, and it then MISSED a macOS-only binary -- the fourth instance
# of the very class it was built for. Building the tool from the examples in hand
# rather than from the class is the same defect one level up. When you find a new
# way the two kernels disagree, add it here rather than fixing the one site.
#
# What this cannot see, by construction: state. A suite that passes because
# ~/.config/kipi exists is invisible to a grep. That half belongs to
# ci-shaped-run.sh, which runs a test with a clean $HOME. Neither tool alone
# covers the set.
#
# Exit 0 = clean. Exit 1 = findings (advisory by default; the caller decides
# whether to block, per the exit-code contract in skill-hook-pairing.md).
set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
FOUND=0

report() {  # report <class> <file:line> <text> <fix>
  FOUND=$((FOUND + 1))
  printf '%s\n  %s\n  %s\n  fix: %s\n\n' "$1" "$2" "$3" "$4"
}

# A line is exempt with an explicit marker, one per line, so a deliberate
# platform-specific branch is possible but must be stated out loud.
scan() {  # scan <regex> <class> <fix> [inverse-regex-that-makes-it-ok]
  local re="$1" class="$2" fix="$3" ok="${4:-}"
  while IFS= read -r hit; do
    [ -n "$hit" ] || continue
    case "$hit" in *portability-lint-skip*) continue ;; esac
    # FILE-LEVEL EXEMPTION for scripts that are inherently platform-specific.
    # install-plist.sh installs launchd plists; verify-codex-review-live.sh reads
    # one. Flagging those is the lint failing CORRECT code, which is how a lint
    # gets ignored -- the same trap as reporting its own prose. The marker must be
    # in the file, so the exemption is a decision someone wrote down, not a
    # hardcoded allowlist here that drifts out of sight.
    _hf="${hit%%:*}"
    if head -20 "$_hf" 2>/dev/null | grep -q 'portability-lint-skip-file'; then continue; fi
    if [ -n "$ok" ] && printf '%s' "$hit" | grep -qE "$ok"; then continue; fi
    local loc="${hit%%:*}" rest="${hit#*:}"
    local body="${rest#*:}"
    # COMMENTS ARE NOT CODE. The first run of this lint flagged its own
    # why-comment explaining the mktemp bug, which is the fastest way to make a
    # lint that nobody keeps on: two of its three findings were prose.
    case "$(printf '%s' "$body" | sed 's/^[[:space:]]*//')" in '#'*) continue ;; esac
    # A GUARDED use is correct use. open-loops-heartbeat.sh does
    # `command -v timeout >/dev/null && TO="timeout 1800"`, which is exactly the
    # right shape; flagging it teaches people to ignore the lint.
    case "$body" in *'command -v'*|*'which '*|*'|| '*'date -'*) continue ;; esac
    report "$class" "$loc:${rest%%:*}" "$(printf '%s' "${rest#*:}" | sed 's/^[[:space:]]*//' | cut -c1-100)" "$fix"
  # SELF-EXCLUDED, because a detector's vocabulary is not a defect. Every pattern
  # this thing looks for appears in its own message strings and fix hints, so the
  # first real run reported 5 findings and all 5 were its own prose. A lint whose
  # own output is mostly itself is a lint people turn off.
  #
  # The cost, stated rather than hidden: a genuine BSD/GNU bug inside this file is
  # invisible to it. That is why the fix hints live in strings here and the actual
  # commands this file RUNS are kept to grep/sed/printf, which behave the same on
  # both kernels.
  done < <(grep -rnE "$re" "$ROOT" \
             --include='*.sh' --include='*.bash' \
             --exclude='portability-lint.sh' \
             --exclude-dir=.git --exclude-dir=node_modules --exclude-dir='.pr*rev*' \
             2>/dev/null || true)
}

echo "portability-lint: scanning $ROOT"
echo

# --- BSD-only: breaks on the Linux CI runner --------------------------------
# GNU mktemp requires >=3 X's in the template; BSD appends the suffix itself.
scan 'mktemp[^|;)#]*-t[[:space:]]+[^[:space:]"]' \
     'BSD-ONLY mktemp -t (GNU rejects a template with under three X'"'"'s)' \
     'mktemp "${TMPDIR:-/tmp}/name.XXXXXX"' \
     'XXX'

# BSD sed -i REQUIRES an argument (often ''), GNU sed -i must NOT have one.
scan "sed[[:space:]]+-i[[:space:]]+''" \
     'BSD-ONLY sed -i '"''"' (GNU sed reads the next arg as the script)' \
     "write to a temp file and mv, which needs no -i at all"

# macOS-ONLY BINARIES. Not a flag difference -- these do not exist on Linux at all,
# so the failure is command-not-found rather than wrong output. Added after this
# lint MISSED the fourth instance of its own class: a new test invoked
# verify-codex-review-live.sh, which reads a launchd plist via `plutil` and
# `launchctl`, and turned `validate` red on the Linux runner. The lint I had just
# built to catch "green locally, wrong where it runs" did not catch it, because I
# had only taught it flag divergences.
#
# A test or script that needs these is not portable -- it must either guard with
# `command -v` and skip LOUDLY, or be declared macOS-only.
scan '(^|[^[:alnum:]_./-])(plutil|launchctl|osascript|sw_vers|diskutil|scutil|pmset)[[:space:]]' \
     'macOS-ONLY binary (does not exist on Linux; command-not-found in CI)' \
     'guard with `command -v <cmd>` and skip loudly, or declare the script macOS-only'

# BSD stat uses -f, GNU uses -c.
scan 'stat[[:space:]]+-f[[:space:]]' \
     'BSD-ONLY stat -f (GNU stat uses -c)' \
     'use wc -c / ls, or branch explicitly on uname'

# --- GNU-only: breaks on the founder'"'"'s macOS ------------------------------
# macOS ships no `timeout` unless coreutils is installed. Already a known scar in
# linear-worker.sh, which implements run_bounded by hand -- this keeps it from
# creeping back in elsewhere.
scan '(^|[^[:alnum:]_./-])timeout[[:space:]]+[0-9]' \
     'GNU-ONLY timeout (macOS ships none; a `|| true` makes it a silent no-op)' \
     'bound it by hand: background the job, poll, kill (see run_bounded)'

# BSD date uses -v, GNU uses -d. kipi-dispatch.sh does this correctly by TRYING
# both; a lone GNU form is the bug.
scan 'date[[:space:]]+-d[[:space:]]' \
     'GNU-ONLY date -d (BSD date uses -v)' \
     'try both: date -v-7H ... 2>/dev/null || date -d "-7 hours" ...' \
     'date -v'

# GNU grep -P (PCRE) is not compiled into BSD grep.
scan 'grep[[:space:]]+(-[a-zA-Z]*)?P[[:space:]]' \
     'GNU-ONLY grep -P (BSD grep has no PCRE)' \
     'rewrite as -E, or use awk'

# BSD readlink has no -f.
scan 'readlink[[:space:]]+-f[[:space:]]' \
     'GNU-ONLY readlink -f (BSD readlink has no -f)' \
     'cd "$(dirname "$x")" && pwd -P'

echo "---"
if [ "$FOUND" -eq 0 ]; then
  echo "portability-lint: clean"
  exit 0
fi
echo "portability-lint: $FOUND finding(s)"
echo
echo "Each of these is green on ONE of the two kernels this repo runs on."
echo "Mark a deliberate platform-specific line with: # portability-lint-skip"
exit 1
