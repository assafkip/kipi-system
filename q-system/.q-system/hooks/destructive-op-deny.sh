#!/bin/bash
# destructive-op-deny.sh - PreToolUse hook that denies destructive
# operations regardless of autonomy mode.
#
# This is the enforcement layer the PocketOS incident (2026-05-17)
# proved was missing in agent stacks: prompt-level rules are advisory,
# only hook-level rules are enforced.
#
# Bypass: set ALLOW_DESTRUCTIVE=1 in the founder's shell session.
# This requires explicit conscious action, which is the whole point.
#
# To revert: remove the PreToolUse entry pointing here from
# ~/.claude/settings.json, or `chmod -x` this file.
#
# THE EXECUTE BIT IS PART OF THE WIRING (ASK-1118, 2026-08-29). The revert line
# above is literally true, and that is the hazard: settings.json runs this as a
# BARE PATH, so `chmod -x` disarms the gate and NOTHING reports it -- no hook
# error, no audit line, no gate goes red. apply_claude_changes.py did exactly
# that by accident: its atomic temp-then-replace created the temp file at the
# default 0644, so landing a CORRECT content fix turned the guard off
# machine-wide, and it was found only because a canary file got deleted after
# the fix was already in this file. That tool now restores the bit on every
# write. If you ever see this file at 0644, the guard is OFF, not merely edited.

set -uo pipefail

LOG="$HOME/.claude/audit/destructive-op-deny.log"
mkdir -p "$(dirname "$LOG")"

INPUT="$(cat)"

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
TOOL_INPUT=$(echo "$INPUT" | jq -c '.tool_input // {}' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

log_decision() {
  local decision="$1" reason="$2"
  printf '{"ts":"%s","tool":"%s","cwd":"%s","decision":"%s","reason":"%s","cmd":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$TOOL_NAME" \
    "$CWD" \
    "$decision" \
    "$reason" \
    "$(echo "$COMMAND" | jq -Rsc .)" \
    >> "$LOG"
}

# DECIDED 2026-08-07: this hook does NOT try to tell prose from invocation.
#
# It fires on a heredoc that merely QUOTES a banned command -- writing a decision
# entry that cites a working-tree wipe as a comparison case gets blocked. That is a
# real false positive and it is the same shape rejected for the no-hourly lint: a
# denylist whose own documentation trips it is a gate someone switches off. It has
# now fired on documentation four times.
#
# It is still the right trade, because the obvious fix is a bypass. Stripping
# heredoc bodies before matching would open `bash <<'EOF' ... EOF`, which EXECUTES
# its body -- and `python3 - <<PY`, and `sh -s`, and every other interpreter that
# reads a script from stdin. Any parser that decides "this string is only prose" is
# a new bypass surface in the one hook standing between an agent and a production
# volume. The asymmetry is decisive: the miss costs a deleted volume, the false
# positive costs one tool call.
#
# The accepted workaround is the Write/Edit tool, which does not route through the
# Bash matcher and is the correct way to author a document anyway. The deny message
# now names it, so the block is signposted instead of merely confusing.
#
# What would change this: a payload field carrying the parsed command WORDS rather
# than the raw string. Matching argv is not guessing. Until then, prose pays a tool
# call and the gate keeps its teeth.
emit_deny() {
  # capability-token-integration: a single-use, command-scoped approval minted
  # out-of-band by the founder (kipi-approve <hash>) allows exactly this command
  # once. Fail closed: a missing or failing token script denies.
  local reason="$1"
  local _ct="$HOME/.claude/bin/capability-token.sh"

  # THE TOKEN'S SCOPE IS THE WHOLE INVOCATION, NOT THE BASH FIELD (ASK-1144).
  #
  # `$COMMAND` is read from `.tool_input.command`, which ONLY Bash payloads
  # carry. Every MCP denial therefore hashed the SAME empty string, so one
  # `kipi-approve <hash>` covered every destructive MCP call on every server --
  # while the deny message said "Approve THIS command". A single-use,
  # command-scoped grant that is neither.
  #
  # It was always wrong and it is load-bearing NOW: before the operation-keyed
  # deny in this change, almost no MCP call reached emit_deny at all, so the
  # shared hash had nothing to unlock. Closing one hole exposed the other, which
  # is why this lands in the same change rather than after it.
  #
  # `jq -cS` sorts keys, so two payloads that differ only in key ORDER hash the
  # same and a token minted for one is not refused for the other. Without -S the
  # scope would be unstable and every grant a coin flip.
  local _scope
  if [ "$TOOL_NAME" = "Bash" ]; then
    _scope="$COMMAND"
  else
    _scope="$TOOL_NAME $(printf '%s' "$INPUT" | jq -cS '.tool_input // {}' 2>/dev/null || echo '{}')"
  fi

  if [ -x "$_ct" ] && "$_ct" check "$_scope" "$CWD"; then
    log_decision "allow" "capability token consumed"
    exit 0
  fi
  local _hash=""
  [ -x "$_ct" ] && _hash="$("$_ct" hash "$_scope" "$CWD" 2>/dev/null || true)"
  log_decision "deny" "$reason"
  jq -nc --arg reason "$reason" --arg hash "$_hash" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("destructive-op-deny: " + $reason + ". Approve THIS command out-of-band: kipi-approve " + $hash + "  (or set ALLOW_DESTRUCTIVE=1 to bypass all).  WRITING DOCS THAT QUOTE THIS COMMAND? Use the Write/Edit tool instead of a heredoc -- this hook cannot tell a quoted string from an invocation, and that is deliberate (see the note above emit_deny).")
    }
  }'
  exit 0
}

# Explicit founder bypass — must be set in the shell session itself,
# cannot be set by an agent inside its own context.
if [ "${ALLOW_DESTRUCTIVE:-0}" = "1" ]; then
  log_decision "allow" "ALLOW_DESTRUCTIVE bypass active"
  exit 0
fi

# ---- Bash destructive patterns ----
if [ "$TOOL_NAME" = "Bash" ] && [ -n "$COMMAND" ]; then
  # Pattern list — extend conservatively.
  declare -a BASH_DENY=(
    'rm[[:space:]]+(-[a-zA-Z]*[rRf][a-zA-Z]*[[:space:]])'
    'rm[[:space:]]+-[a-zA-Z]*[rRf]'
    'git[[:space:]]+reset[[:space:]]+--hard'
    'git[[:space:]]+branch[[:space:]]+-D'
    'git[[:space:]]+filter-(branch|repo)'
    'git[[:space:]]+update-ref[[:space:]]+-d'
    'find[[:space:]]+.+-delete'
    'find[[:space:]]+.+-exec[[:space:]]+rm'
    'dd[[:space:]]+.*of=/dev/'
    'mkfs'
    'shred[[:space:]]'
    'truncate[[:space:]]+-s[[:space:]]+0'
    ':\(\)\{[[:space:]]*:\|:'   # fork bomb
    '>[[:space:]]*/etc/'         # truncate /etc/* only
    '>[[:space:]]*/var/log/'     # truncate /var/log/* only
    'chmod[[:space:]]+-R[[:space:]]+777[[:space:]]+/'
    'chown[[:space:]]+-R.*[[:space:]]+/'
    # FLEET-WIDE DELETE (added 2026-08-07). `kipi update` rsyncs the skeleton into
    # every registered instance with a delete flag. Run from a source tree that is
    # missing a package, it REMOVES that package from every instance at once.
    # Measured that day: a sync sourced from origin/main removed
    # plugins/kipi-core/voicekit from 19 instances, and in the consulting instance
    # pipeline/voice.py imports it at module load, so the whole suite stopped
    # collecting. Recovered from git, but nothing warned first.
    #
    # This is strictly more destructive than most of what is already on this list:
    # the force-clean entry above hits ONE repo, this hits twenty. It was not
    # covered. The carve-out's own logic applies exactly -- prompt-level care gets
    # violated, only hook-level enforcement holds -- and an agent cannot set
    # ALLOW_DESTRUCTIVE for itself, which is the point.
    #
    # A dry run is deliberately NOT matched: previewing is how you earn the run.
  )

  # FLEET-WIDE DELETE, kept in its own list because a DRY RUN must be exempt.
  # Anchored at COMMAND POSITION on purpose: a first attempt matched the script
  # name anywhere in the line and blocked `sed -n '1,20p' kipi-update.sh`, but
  # reading a file is not running it. A gate that blocks reads is a gate someone
  # switches off.
  declare -a FLEET_DENY=(
    'kipi[[:space:]]+update'
    '(^|[;&|][[:space:]]*)(bash|sh|zsh|source)[[:space:]]+[^[:space:]]*kipi-update\.sh'
    '(^|[;&|][[:space:]]*)[./~][^[:space:]]*kipi-update\.sh'
    '(^|[;&|][[:space:]]*)rsync[[:space:]]+[^|;]*--delete'
  )
  # THE COARSE PUSH PATTERN IS GONE TOO, FOR THE SAME REASON (round six).
  #
  # It matched `--force` anywhere after `push`, so a `--dry-run` preview was
  # refused before the argv rule -- which handles the preview correctly -- ever
  # ran. That left this one change carrying both halves of a contradiction:
  # `git clean --dry-run` allowed, the equivalent push denied.
  #
  # Removed rather than taught to spell "force but not dry-run", because the
  # argv rule already covers strictly MORE: --force, --force-with-lease, -f, a
  # leading-plus refspec, --delete, :branch and --mirror, none of which this
  # regex saw. Two copies of one rule is the drift this file keeps warning
  # about, and the weaker copy was winning by running first.
  #
  # Pinned by test_argv_prefilter.py: --force, +main and -f still deny; the
  # three --dry-run spellings do not.
  #
  # THE COARSE `git clean` PATTERN IS GONE, ON PURPOSE (PR #279 minor).
  #
  # It read `-[a-zA-Z]*[fdx]`, so `git clean -nd` matched on the `d` and a DRY
  # RUN was refused. Denying a preview is how a gate gets switched off: this
  # file already records that previewing is how you EARN the run, and FLEET_DENY
  # carves out --dry-run for exactly that reason.
  #
  # It is REMOVED rather than made cleverer because the argv rule below covers
  # the same ground and covers it better: it reads the flags instead of pattern-
  # matching a cluster, so it denies -f/-d/-x/--force and returns for -n and
  # --dry-run. Teaching a regex to mean "contains f, d or x but not n" would be
  # a second, worse copy of a decision the argv path already makes correctly,
  # and two copies of one rule is the drift this file keeps warning about.
  #
  # Pinned by test_argv_prefilter.py's clean cases: -fd still denies, -nd and
  # --dry-run do not.
  for pat in "${BASH_DENY[@]}"; do
    if echo "$COMMAND" | grep -Eq "$pat"; then
      emit_deny "Bash command matches destructive pattern: $pat"
    fi
  done

  # ASK-1131: the patterns above are POSITIONAL, so a leading flag hides the
  # dangerous one. Each of them requires its dangerous token IMMEDIATELY after the
  # command name, and nothing here inspected arguments:
  #
  #   rm -rf DIR         BLOCKED, correctly
  #   rm -v -rf DIR      EXECUTED. Directory deleted, guard never fired, and it
  #                      printed each removed path on the way out.
  #
  # Worse than the dry-run hole below, which needs a compound command. This is a
  # single natural invocation, and adding -v to watch what is being removed is
  # something people type deliberately. Same shape on `git push -q --force`,
  # `git branch -q -D`, `git clean -q -fd`, `git reset -q --hard`, and on
  # `git -C DIR reset --hard`, where a GLOBAL flag moves the subcommand along.
  #
  # HOW IT SURFACED, because the method matters more than the bug. Two agents
  # measured this guard and disagreed: one saw the removal form BLOCKED, the
  # other had run it twice with -q inserted. Neither was wrong, and it was nearly
  # filed as a long-flag-versus-short-flag runbook nit. Two contradictory
  # measurements of one guard meant the guard was broken. Chase a disagreement
  # like that; do not reconcile it.
  #
  # NOT A FOURTH PATTERN. Three patterns for three holes leaves the fourth. This
  # asks what the invocation actually IS: program, subcommand, and every flag
  # wherever it sits. The substring list above is KEPT and runs first -- it can
  # only ever DENY, so everything it already catches is unchanged, including the
  # deliberate prose false positives decided on 2026-08-07.
  #
  # HONEST BOUND. Tokenising on whitespace is approximate for quoted OPERANDS
  # (`rm -rf "my dir"` reads as two operands) and exact for FLAGS, which is the
  # only axis these rules turn on. It resolves nothing: no variable expansion, no
  # alias, no `$(...)`. A payload built at runtime is still invisible here and is
  # still the substring list's problem, which is why that list stays.

  # A single-dash cluster containing <letter>, anywhere in the argv.
  _argv_has_short() {  # _argv_has_short <letter> <token>...
    local letter="$1"; shift
    local tok
    for tok in "$@"; do
      case "$tok" in
        --*) continue ;;
        -*) case "$tok" in *"$letter"*) return 0 ;; esac ;;
      esac
    done
    return 1
  }

  _argv_has_long() {  # _argv_has_long <name> <token>...
    local name="$1"; shift
    local tok
    for tok in "$@"; do
      case "$tok" in "--$name"|"--$name="*) return 0 ;; esac
    done
    return 1
  }

  # Every array below is seeded with one empty token on purpose: bash 3.2 (the
  # /bin/bash this runs under) treats "${arr[@]}" on an EMPTY array as an unbound
  # variable under `set -u`, which would abort the hook and, since a hook that
  # dies produces no decision, fail OPEN on the one gate that must not.
  # CAN A DENY POSSIBLY START AT THIS TOKEN? (PR #279 major.)
  #
  # The every-starting-position scan below called argv_deny_reason once per
  # token, and each call is a COMMAND SUBSTITUTION -- a subshell fork -- that
  # re-parses the remaining tokens. O(n) forks x O(n) work. Measured on this
  # hook before the fix, on a single `git` stage:
  #
  #     120 tokens   0.64s
  #     230 tokens   3.83s
  #     400 tokens  19.43s
  #
  # settings.json wires this hook at timeout 5. A hook that overruns its timeout
  # is KILLED and its verdict DISCARDED -- measured in this repo already (a 0s
  # hook exiting 2 blocks; an 8s hook exiting 2 runs). So a long enough command
  # line was a bypass needing no cleverness at all, and the slow path is the
  # BENIGN one, which is every call the hook ever sees.
  #
  # This is an exact-semantics filter, not a heuristic. argv_deny_reason strips
  # transparent prefixes and then switches on the program basename, so a position
  # whose token is neither a transparent prefix nor a recognised program CANNOT
  # return 0 -- skipping it changes no outcome. The two lists are deliberately
  # adjacent, and test_argv_prefilter_matches_reasons pins them together so
  # adding a program arm without adding it here is caught.
  # HOW FAR A RESCAN LOOKS FROM A PROGRAM TOKEN.
  #
  # De-forking the per-position scans was necessary and not sufficient: each call
  # still slices `"${arr[*]:$i}"`, rebuilding the whole remaining string, so the
  # loop stayed O(n^2). Measured after the fork was removed: 2000 admitted
  # tokens took 5.44s and 4000 took 21.24s, against a wired 5s timeout.
  #
  # Filtering cannot fix this. `git` and `rm` MUST be admitted -- they are the
  # tokens that can deny -- so an adversarial line padded with them is unbounded
  # by construction. The window is the only lever that does not give up the scan.
  #
  # WHAT THIS COSTS, stated rather than discovered later: in these RESCANS, a
  # decisive flag more than 64 tokens after its own program token is not seen.
  # The FIRST-position scan still reads the entire stage unbounded, so an
  # ordinary `git push ... --force` at any length is still caught there; what the
  # rescans add is coverage of a program token HIDDEN mid-line, and 64 tokens is
  # far past any real invocation's flags. A bound that is stated is better than a
  # timeout that silently discards the verdict.
  _ARGV_WINDOW=64

  # A CEILING PADDING CANNOT MOVE (PR #279, round six of one bypass).
  #
  # Five rounds narrowed constants: which tokens are admitted, whether the scan
  # forks, how far each rescan looks, and finally the quadratic quote strip.
  # Every one of them MOVED the threshold and none removed it, because the loop
  # runs once per admitted token and `rm` and `git` must be admitted -- they are
  # the tokens that can deny. Measured after the quote-strip fix, padding a
  # stage with bare program names:
  #
  #     tokens     pad=rm     pad=git
  #      2000       1.84s       0.73s
  #      4000       4.06s       1.95s
  #      6000       6.96s       3.63s   <- past the wired 5s timeout
  #      8000      10.16s       5.85s
  #
  # An overrunning hook is killed and its deny DISCARDED, so past ~5000 rm
  # tokens the answer silently became "allow". A cheaper inner loop would only
  # move the crossing again; a COUNT ceiling is the only bound an attacker
  # cannot pad past.
  #
  # Refusing is the correct direction. "I could not finish checking" is not
  # permission. 500 rescans is ~0.5s of scanning here, ten times under the
  # budget, and reaching it takes 500 bare `rm`/`git`-shaped words in ONE stage
  # -- the pre-filter admits only known deniers, so an ordinary long command
  # (file lists, paths, flags) never approaches it. The refusal says what
  # happened and says to split the command.
  #
  # An earlier version of this cap was written, measured and removed in round
  # five because it fired in the wrong place: it was checked before the cost,
  # so it changed the timings by nothing. The cost is here, in the count.
  _ARGV_MAX_RESCANS=500

  # THE CEILING BOUNDS THE INVOCATION, NOT THE STAGE (round seven, same bypass).
  #
  # Round six added the ceiling and reset it at the top of every `;`-separated
  # stage, so a command bought a fresh 500 rescans per stage and the bound was
  # only ever per-stage. Measured by codex on that build: 14 padded stages,
  # 21KB, reached 5.55s against the wired 5s timeout, where the hook is killed
  # and its deny DISCARDED. The headline claim of the previous commit -- "bound
  # the rescan COUNT" -- was therefore false as shipped.
  #
  # The counter is initialised ONCE here and never reset, so the ceiling is a
  # budget for the whole invocation. Splitting a payload across stages now
  # spends the same budget instead of multiplying it, which is the property the
  # word "bound" was claiming all along.
  #
  # Seventh instance of one bypass in one predicate. That is a signal about the
  # SURFACE -- a 5s-timeout-bounded shell scanner is a poor shape for a refusal
  # that must hold under adversarial padding -- and it is captured as its own
  # row rather than answered with an eighth round here.
  _rescans=0

  # The one ceiling that stays: the git arm below is O(n^2) in its own right
  # (it rebuilds the remaining-token array at every position), and unlike the
  # scan loops that cost is not removed by the tr fix. 600 tokens is ~1s here,
  # five times under the wired 5s timeout, and past any real git invocation.
  # A cap on the SCAN loops was tried and removed in the same round: it denied
  # `echo git git ...`, which is ordinary, and a guard that blocks ordinary work
  # gets switched off.
  _ARGV_MAX_TOKENS=600

  _argv_could_deny_here() {  # _argv_could_deny_here <token>
    case "${1##*/}" in
      rm|git)                                  return 0 ;;
      # NO TRANSPARENT-PREFIX ARM. Same argument as the flag and assignment arms
      # before it, and it is the one that finally ends this bypass: a position
      # starting at `sudo` can only deny if a recognised program FOLLOWS, and
      # that program's own position is scanned separately. Admitting prefixes
      # bought no coverage and cost the third measured blowup -- 300 `sudo`
      # tokens took 5.91s against a 5s timeout, because each forked a subshell.
      #
      # `sudo rm -rf x` still denies, from the `rm` position, and that is pinned
      # by test_transparent_prefixes_still_deny -- a case that predates this
      # change, which is why removing the arm is verifiable rather than
      # arguable. The filter now admits only tokens that can themselves deny, so
      # the fork count is bounded by the number of rm/git tokens rather than by
      # command length.
      # NO ASSIGNMENT ARM AT ALL, and that is not a narrowing of the guard.
      #
      # It used to admit `[!-]*=*` to catch `FOO=bar cmd`. But argv_deny_reason
      # STRIPS leading assignments and then looks at the program, so a position
      # starting at an assignment can only deny if a recognised program follows
      # -- and that program's own position is scanned separately, every time.
      # The arm bought no coverage and cost the bypass it was meant to close:
      # 300 `k=v` tokens took 8.28s against a 5s timeout, because every one of
      # them forked a subshell.
      #
      # `FOO=bar rm -rf x` still denies, from the `rm` position. That is pinned
      # by test_an_env_assignment_prefix_still_denies, which existed before this
      # change and is why removing the arm is safe to do rather than to argue
      # about.
      *)                                       return 1 ;;
    esac
  }

  # REASON IN A VARIABLE, NOT ON STDOUT (PR #279, round four of one bypass).
  #
  # Callers used `$(argv_deny_reason ...)` to capture the reason, and a command
  # substitution is a FORK. The every-position scan therefore forked once per
  # admitted token, so padding with an admitted shape -- `git`, `rm`, the two
  # that must be admitted because they can actually deny -- pushed the hook past
  # its wired 5s timeout at roughly 2000 tokens. An overrunning hook is killed
  # and its deny DISCARDED.
  #
  # Three previous rounds narrowed which tokens are admitted. That only moved the
  # threshold, because the admitted set can never be empty. The cost was never
  # the scan; it was the fork around it. Setting a global and returning a status
  # removes it, and the loop becomes ordinary function calls in one shell.
  argv_deny_reason() {  # sets _ARGV_REASON, rc 0 = deny
    local stage="$1"
    set -f
    local -a w=( $stage )
    set +f
    [ "${#w[@]}" -gt 0 ] || return 1
    # Transparent prefixes change nothing about what actually runs.
    while [ "${#w[@]}" -gt 0 ]; do
      case "${w[0]}" in
        *=*)                             w=( "" "${w[@]:1}" ); w=( "${w[@]:1}" ) ;;
        sudo|command|nohup|nice|time|env) w=( "" "${w[@]:1}" ); w=( "${w[@]:1}" ) ;;
        *) break ;;
      esac
      [ "${#w[@]}" -gt 0 ] || return 1
    done
    [ "${#w[@]}" -gt 0 ] || return 1
    local prog="${w[0]##*/}"
    local -a rest=( "" "${w[@]:1}" )

    case "$prog" in
      rm)
        if _argv_has_short r "${rest[@]}" || _argv_has_short R "${rest[@]}" \
           || _argv_has_short f "${rest[@]}" \
           || _argv_has_long recursive "${rest[@]}" \
           || _argv_has_long force "${rest[@]}"; then
          _ARGV_REASON="rm carries a recursive or force flag (argv-inspected: a leading flag cannot hide it)"
          return 0
        fi
        ;;
      git)
        # Walk git's GLOBAL flags to find the subcommand: `git -C DIR reset
        # --hard` is the same act as `git reset --hard`, and the old pattern saw
        # neither.
        # THE CEILING SITS WHERE THE COST IS (PR #279 round five).
        #
        # The loop below walks every remaining token and rebuilds the
        # remaining-token array at each step, so ONE call over an n-token git
        # stage is O(n^2) with a large constant. Round four bounded the two
        # rescan loops with a 64-token window and wrote, in a comment, that
        # "the FIRST-position scan still reads the entire stage unbounded".
        # That sentence was the hole, shipped. Capping the rescan loops moved
        # the measured timings by nothing, which is how the real site was
        # found: the first cap fired in the wrong place.
        #
        # Measured against the wired 5s timeout, destructive token QUOTED so
        # only the strip-scan can reach a verdict:
        #    500 tokens 0.57s   1000 tokens 3.13s
        #   2000 tokens 22.85s  4000 tokens 186.52s
        # An overrunning hook is killed and its deny DISCARDED, so past ~1200
        # tokens the answer silently became allow.
        #
        # This refuses instead. "I could not finish checking" is not permission
        # -- fail closed is the only correct direction for a guard. The cap is
        # HERE and not at the function entry because the other arms are linear
        # and cheap: a 4000-word `echo` stage is ordinary and stays allowed,
        # which matters because a guard that blocks ordinary work gets switched
        # off. 600 tokens is ~1s here, five times under the budget, and no real
        # git invocation carries 600 words in one stage.
        if [ "${#w[@]}" -gt "$_ARGV_MAX_TOKENS" ]; then
          _ARGV_REASON="this git stage is ${#w[@]} tokens, past the $_ARGV_MAX_TOKENS this guard can finish checking inside its time budget. It refuses rather than answering allow by running out of time. Split the command into separate stages"
          return 0
        fi
        local -a g=( "" "${w[@]:1}" ); g=( "${g[@]:1}" )
        local sub="" i=0
        while [ "$i" -lt "${#g[@]}" ]; do
          case "${g[$i]}" in
            -C|-c|--git-dir|--work-tree|--namespace|--exec-path) i=$((i+2)) ;;
            --*=*|-*) i=$((i+1)) ;;
            *) sub="${g[$i]}"; break ;;
          esac
        done
        [ -n "$sub" ] || return 1
        local -a ga=( "" "${g[@]:$((i+1))}" )
        case "$sub" in
          reset)
            _argv_has_long hard "${ga[@]}" && { _ARGV_REASON="git reset --hard discards the working tree"; return 0; } ;;
          push)
            # A PREVIEW PUSHES NOTHING (codex minor, PR #279 round six).
            #
            # `git push --force --dry-run` was DENIED while `git clean --dry-run`
            # was allowed fifty lines below, on the opposite reasoning -- one
            # change carrying both halves of a contradiction. The clean arm's
            # own note says it plainly: previewing is how you EARN the run, and
            # denying the preview is how a gate gets switched off.
            #
            # `--dry-run` on a push reports what WOULD be sent and updates no
            # ref, forced or not. Same reasoning, so the same answer.
            if _argv_has_long dry-run "${ga[@]}"; then
              return 1
            fi
            if _argv_has_long force "${ga[@]}" || _argv_has_long force-with-lease "${ga[@]}" \
               || _argv_has_short f "${ga[@]}"; then
              _ARGV_REASON="git push is forced, which rewrites published history"; return 0
            fi
            # THE LEADING-PLUS REFSPEC IS ALSO A FORCE PUSH (PR #279 major).
            #
            # `git push origin +main` rewrites remote history exactly as
            # `--force` does, and this checked only the FLAGS. Every spelling of
            # the flag was covered and the form that needs no flag at all was
            # not, which is the shape ASK-1131 already found once: a rule that
            # reads how the dangerous thing is usually written rather than what
            # it does.
            #
            # Matched on the ARGV token, so `+` inside some other word cannot
            # trigger it and a refspec is recognised wherever it sits in the
            # line. `+` alone is not a refspec, so the token needs something
            # after it.
            # DELETION IS NOT SPELLED --force EITHER (PR #279 minors). The
            # +refspec rule above closed one flagless form and left three:
            #   git push origin --delete <branch>
            #   git push origin :<branch>        (the colon refspec)
            #   git push --mirror origin         (deletes every remote ref the
            #                                     local repo does not have)
            # All three destroy published refs. Grouping them here rather than
            # in a second rule keeps every "push destroys something" case in one
            # place, which is the drift the ASK-1131 comment above warns about.
            if _argv_has_long delete "${ga[@]}" || _argv_has_short d "${ga[@]}"; then
              _ARGV_REASON="git push --delete removes a published ref"; return 0
            fi
            if _argv_has_long mirror "${ga[@]}"; then
              _ARGV_REASON="git push --mirror deletes every remote ref this repo lacks"; return 0
            fi
            local _tok
            for _tok in "${ga[@]:1}"; do
              case "$_tok" in
                +?*) _ARGV_REASON="git push with a leading-plus refspec ($_tok) is a force push and rewrites published history"; return 0 ;;
                :?*) _ARGV_REASON="git push with a colon refspec ($_tok) deletes the remote ref"; return 0 ;;
              esac
            done ;;
          branch)
            _argv_has_short D "${ga[@]}" && { _ARGV_REASON="git branch -D deletes a branch unmerged"; return 0; } ;;
          clean)
            # A PREVIEW REMOVES NOTHING (PR #279 minor). `git clean -nd` and
            # `--dry-run` only LIST what would go, and denying a preview is how a
            # gate gets switched off: the fleet rule above already records that
            # previewing is how you EARN the run, and the FLEET_DENY list carves
            # out --dry-run for exactly this reason. This arm did not.
            if _argv_has_short n "${ga[@]}" || _argv_has_long dry-run "${ga[@]}"; then
              return 1
            fi
            if _argv_has_short f "${ga[@]}" || _argv_has_short d "${ga[@]}" \
               || _argv_has_short x "${ga[@]}" || _argv_has_long force "${ga[@]}"; then
              _ARGV_REASON="git clean removes untracked files"; return 0
            fi ;;
          filter-branch|filter-repo)
            _ARGV_REASON="git $sub rewrites every commit in the repository"; return 0 ;;
          update-ref)
            _argv_has_short d "${ga[@]}" && { _ARGV_REASON="git update-ref -d deletes a ref"; return 0; } ;;
        esac
        ;;
    esac
    return 1
  }

  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    _ARGV_REASON=""; argv_deny_reason "$_stage" && _argv_reason="$_ARGV_REASON" && \
      emit_deny "destructive invocation: $_argv_reason. This is decided from the command's ARGV, not from where a flag happens to sit in the line (ASK-1131)."
  done < <(printf '%s\n' "$COMMAND" | tr ';|&' '\n\n\n')

  # ASK-1131 round 2 (Codex major, PR #274). A transparent prefix that takes its
  # OWN options left that option sitting where the program should be:
  #
  #   sudo -u root rm -v -rf DIR   program read as `-u`, no rule matched, ALLOWED
  #   env -i rm -v -rf DIR         same
  #   nice -n 10 rm -i -r DIR      same
  #
  # and the substring list above misses them too, because the leading -v is hole
  # 3 all over again. Both layers failed on the same command.
  #
  # Enumerating each prefix's option arity is the losing game
  # claude-path-write-guard.py names in its own header -- and it does not even
  # work here: skipping `-u` still leaves `root` as the program. So the rules are
  # offered EVERY starting position in the stage instead. Whatever sits in front,
  # the invocation itself is still somewhere in that argv, and the RULES are
  # unchanged: this reuses argv_deny_reason verbatim rather than restating it,
  # because a second copy of a guard is two chances for them to drift apart.
  #
  # The single-position loop above is a strict subset of this one. It is left in
  # place only because the sanctioned write path is additive-only and cannot
  # remove it (sp-ae47f005); it can only ever DENY, so it changes no outcome.
  #
  # ACCEPTED COST, stated rather than discovered later: `docker rm -f NAME` is now
  # refused with a message about recursive file deletion. It is still a forced
  # removal, and this hook already refuses far more prose than that, so a
  # fail-closed misnomer is the cheap side of the trade.
  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    set -f
    _sw=( "" $_stage )
    set +f
    _i=1
    while [ "$_i" -lt "${#_sw[@]}" ]; do
      # Skip positions that provably cannot deny, so the fork below runs a
      # handful of times instead of once per token. See _argv_could_deny_here.
      if _argv_could_deny_here "${_sw[$_i]}"; then
        _rescans=$((_rescans+1))
        if [ "$_rescans" -gt "$_ARGV_MAX_RESCANS" ]; then
          emit_deny "this command stage carries more than $_ARGV_MAX_RESCANS program-name-shaped tokens, more than this guard can finish checking inside its time budget. It refuses rather than answering allow by running out of time. Split the command into separate stages."
        fi
        _ARGV_REASON=""; argv_deny_reason "${_sw[*]:$_i:$_ARGV_WINDOW}" && _argv_reason="$_ARGV_REASON" && \
          emit_deny "destructive invocation: $_argv_reason. Decided from the command's ARGV at every starting position, so neither a leading flag nor a prefix carrying its own options can move it out of view (ASK-1131)."
      fi
      _i=$((_i+1))
    done
  done < <(printf '%s\n' "$COMMAND" | tr ';|&' '\n\n\n')

  # ASK-1131 round 3 (Codex major, PR #274). The program token can be QUOTED or
  # ESCAPED, and then the scan reads a different word:
  #
  #   "rm" -rf DIR    tokenises to `"rm"`, basename `"rm"`, no rule, ALLOWED
  #   'rm' -rf DIR    same
  #
  # and the substring list misses `"rm" -rf` too, because it wants whitespace
  # straight after the name and finds a quote instead. Escaping the name is also
  # the ordinary way to bypass an alias, so it is a form people type on purpose,
  # not only one an attacker would reach for.
  #
  # The shell strips these before exec, so the scan does too: the SAME rules are
  # offered once more over a stage with quote and backslash characters removed.
  # Removing them can only REVEAL a program name, never hide one, so this layer
  # is deny-only like every layer before it and cannot clear anything.
  #
  # It does mean `echo "rm -rf x"` reaches the rm rule. That string is already
  # denied by the substring list above, deliberately, since 2026-08-07: this hook
  # does not try to tell prose from invocation, and nothing here changes that.
  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    # ONE FORK, NOT A QUADRATIC (PR #279 round five -- THE fix).
    #
    # This was three `${var//x/}` substitutions. On bash 3.2, which is what
    # macOS ships and what this hook runs under, that operator is O(n^2) in the
    # string length. Measured here, stripping quotes from a padded stage:
    #
    #   tokens   ${var//}    tr -d
    #    1000       3s        0s
    #    2000      22s        0s
    #    4000     175s        0s
    #
    # The hook's own end-to-end timings were 3.13s / 22.85s / 186.52s at those
    # sizes, so this line WAS the bypass: against the wired 5s timeout the hook
    # was killed here and its deny discarded, which is an allow.
    #
    # Four rounds went into the scan loops -- de-forking them, windowing them,
    # capping them -- and each round re-measured and found the same numbers.
    # Capping the loops changed the timings by nothing, which is the evidence
    # that finally pointed here. The scans were never the cost. One `tr` fork
    # per stage is O(n) and beats every loop optimisation that came before it.
    _norm="$(printf '%s' "$_stage" | tr -d '"'"'"'\\')"
    [ "$_norm" = "$_stage" ] && continue
    set -f
    _dw=( "" $_norm )
    set +f
    _i=1
    while [ "$_i" -lt "${#_dw[@]}" ]; do
      # THE SAME PRE-FILTER AS THE OTHER SCAN (PR #279 major). This loop had
      # none, so a single long QUOTED string reached it unfiltered and forked
      # per word: 3000 words took 6.99s against a 5s timeout. Fixing one of two
      # identical loops is how a bypass survives being "fixed".
      if _argv_could_deny_here "${_dw[$_i]}"; then
        _rescans=$((_rescans+1))
        if [ "$_rescans" -gt "$_ARGV_MAX_RESCANS" ]; then
          emit_deny "this command stage carries more than $_ARGV_MAX_RESCANS program-name-shaped tokens after quote stripping, more than this guard can finish checking inside its time budget. It refuses rather than answering allow by running out of time. Split the command into separate stages."
        fi
        _ARGV_REASON=""; argv_deny_reason "${_dw[*]:$_i:$_ARGV_WINDOW}" && _argv_reason="$_ARGV_REASON" && \
          emit_deny "destructive invocation: $_argv_reason. The program token was quoted or escaped; the shell strips that before exec, so this scan does too (ASK-1131)."
      fi
      _i=$((_i+1))
    done
  done < <(printf '%s\n' "$COMMAND" | tr ';|&' '\n\n\n')

  # ASK-1118: the fleet exemption is decided per STAGE, not over the whole string.
  #
  # THE SCAR, both directions, each measured before this was written. The block
  # below tests `*--dry*` against the ENTIRE command while every FLEET_DENY entry
  # it guards is anchored at COMMAND POSITION. The two halves disagreed about
  # what a command is, and the gap ran both ways:
  #
  #   fails OPEN    a `--dry` ANYWHERE in a compound command exempted every
  #                 fleet-delete in it. An `echo` mentioning the flag on one
  #                 line and a real `rsync -a --delete` on the next really did
  #                 delete the canary file. The deny message below says "Preview
  #                 it first with --dry-run", so running the preview and the
  #                 apply in ONE block is this hook's own recommended workflow
  #                 disarming this hook.
  #   fails CLOSED  the substring never matches rsync's short `-n`, and
  #                 kipi-update-deletion-guard.py's own documented usage line is
  #                 `rsync -ain --delete SRC DEST <excludes> | python3 ...`. The
  #                 documented way to run the fleet DELETION GUARD was blocked
  #                 by this guard (sp-9b01d746; it already cost a false
  #                 spillover finding and an unmeasured propagation claim).
  #
  # A stage is the granularity the FLEET_DENY patterns already use: their own
  # `(^|[;&|][[:space:]]*)` anchors and the rsync entry's `[^|;]*` stop at
  # exactly these boundaries, and claude-path-write-guard.py reached the same
  # split independently (its STATEMENT_OPS). This finishes a distinction the
  # file already made rather than inventing one.
  #
  # THE WHOLE-STRING BLOCK BELOW IS LEFT IN PLACE ON PURPOSE, twice over. It can
  # only ever DENY, so leaving it keeps the fail-closed direction for anything
  # this split does not see (`kipi` and `update` separated by a newline is the
  # real case). And it could not have been removed anyway: the only write path
  # an agent has into ~/.claude is apply-claude-changes.sh, which is
  # additive-only and cannot change an existing predicate. That limitation is
  # reported alongside this fix, not worked around.
  fleet_stage_is_preview() {
    case "$1" in
      *--dry*) return 0 ;;
    esac
    # rsync's short dry-run flag, in any cluster (-n, -ain, -avn). Gated on the
    # stage naming rsync, because `-n` means something else to nearly every
    # other program: `rsync -a --delete a/ b/ | head -n 20` is an APPLY, and its
    # `-n` sits in a later stage precisely so this test never sees it.
    case "$1" in
      *rsync*) ;;
      *) return 1 ;;
    esac
    echo "$1" | grep -Eq '(^|[[:space:]])-[A-Za-z]*n[A-Za-z]*([[:space:]]|$)'
  }

  # Process substitution, never a pipe: a pipe runs the loop in a SUBSHELL, so
  # emit_deny's exit would end only that subshell and the parent would carry on
  # and log an allow after the deny JSON was already emitted.
  _fleet_preview=0
  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    # ";" is prepended so each pattern's own `[;&|][[:space:]]*` alternative
    # absorbs the stage's leading whitespace. Without it a stage starting with a
    # space matches neither `^` nor a boundary and the deny silently vanishes.
    if fleet_stage_is_preview "$_stage"; then
      for pat in "${FLEET_DENY[@]}"; do
        if echo ";$_stage" | grep -Eq "$pat"; then _fleet_preview=1; break; fi
      done
      continue
    fi
    for pat in "${FLEET_DENY[@]}"; do
      if echo ";$_stage" | grep -Eq "$pat"; then
        emit_deny "fleet-wide delete: this rsyncs the skeleton into EVERY registered instance with a delete flag, and a source tree missing a package removes it from all of them at once (2026-08-07: voicekit deleted from 19 instances). Preview it first with --dry-run IN ITS OWN TOOL CALL and read what will be REMOVED, not only what changes -- a preview sharing a command block with the apply does not exempt the apply (ASK-1118). Pattern: $pat"
      fi
    done
  done < <(printf '%s\n' "$COMMAND" | tr ';|&' '\n\n\n')

  if [ "$_fleet_preview" = "1" ]; then
    log_decision "allow" "fleet: every stage matching a fleet pattern is a preview"
    exit 0
  fi

  # A preview is how you EARN the run, so it is never blocked. Checked as a plain
  # substring rather than folded into each regex: `--dry` and `--dry-run` are the
  # only two spellings kipi-update.sh accepts, and an exemption that is easy to
  # read is worth more here than one that is clever.
  case "$COMMAND" in
    *--dry*) : ;;
    *)
      for pat in "${FLEET_DENY[@]}"; do
        if echo "$COMMAND" | grep -Eq "$pat"; then
          emit_deny "fleet-wide delete: this rsyncs the skeleton into EVERY registered instance with a delete flag, and a source tree missing a package removes it from all of them at once (2026-08-07: voicekit deleted from 19 instances). Preview it first with --dry-run and read what will be REMOVED, not only what changes. Pattern: $pat"
        fi
      done
      ;;
  esac
fi

# ---- MCP destructive tool denials ----
#
# KEYED ON THE OPERATION, NOT THE VENDOR (ASK-1144, 2026-08-29).
#
# This case used to name `mcp__plugin_linear_linear__*` and
# `mcp__plugin_Notion_notion__*`. Neither is a server that exists. The loaded
# Linear server is `mcp__linear__*`, and `grep -c mcp__linear__` on this file
# returned 0 while the founder's CLAUDE.md called Linear `*delete*` hook-blocked
# and NON-NEGOTIABLE. `mcp__supabase__delete_branch` was in the live tool roster
# matched by nothing at all. The gate ran, passed, and was structurally blind to
# the thing it existed to catch -- a confident wrong answer, not a missing check.
#
# The repair is NOT a wider vendor wildcard. Adding the two missing servers closes
# exactly two holes and re-opens the class on the next server nobody guessed; and
# a `mcp__linear__*` wildcard denies `list_issues`, which is the over-block that
# gets a gate switched off (`design-auto-invoke.md`: a gate that is off protects
# nothing).
#
# An MCP tool name is `mcp__<server>__<operation>`. The vendor half drifts --
# account connectors, plugin renames, a marketplace reinstall. The OPERATION half
# does not: every server that deletes spells it `delete`. So the deny reads the
# operation and the vendor stops mattering.
#
# THE `un` GUARD IS LOAD-BEARING. `untrash_message` and `untrash_thread` both
# contain `trash` and both RESTORE. A verb list without the guard turns the
# recovery path into a blocked path, which is worse than the hole it closed.
# `browser_drop` is why `drop` is not a verb here: it is a drag gesture. A SQL
# `DROP` arrives inside `execute_sql`'s PAYLOAD, which no name-matching rule can
# see -- captured as spillover rather than papered over with a verb that would
# only look like coverage.
#
# The paired checker `q-system/.q-system/scripts/mcp-denylist-namespace-check.py`
# refuses any `mcp__<ns>__` in this file that names no registered server, so the
# dead-entry shape cannot come back silently. Tests:
# `q-system/.q-system/tests/test_destructive_op_mcp_namespace.py`.
if [ "${TOOL_NAME:0:5}" = "mcp__" ]; then
  # Everything after the LAST `__` is the operation. Server names may contain a
  # single underscore (`claude_ai_Gmail`), so the last separator is the only one
  # that reliably splits vendor from operation.
  MCP_OP="${TOOL_NAME##*__}"
  # camelCase IS a word boundary (PR #279 minor). `batchDelete` lowercases to
  # `batchdelete`, where `delete` is preceded by a letter, so the anchored verb
  # rule below did not match and a compound deletion was ALLOWED. MCP servers
  # name operations both ways -- `delete_branch` and `batchDelete` -- so the
  # separator has to cover both. An underscore is inserted at every lower-to-
  # upper transition before folding case.
  # `un` STAYS ATTACHED THROUGH THE FOLD (PR #279 minor). The camelCase rule
  # above turns `unDelete` into `un_delete`, where `delete` sits behind an
  # underscore -- a non-letter -- so the anchored verb rule matched and a RESTORE
  # was denied. My camelCase fix broke my own un-guard, and both were mine.
  #
  # The second sed re-joins `un` to whatever follows it, so `unDelete`,
  # `unTrash` and `unRemove` end as `undelete`, `untrash`, `unremove` -- the
  # exact shape the guard was written for -- while `batchDelete` still becomes
  # `batch_delete` and denies.
  MCP_OP_LOWER="$(printf '%s' "$MCP_OP" \
    | sed 's/\([a-z0-9]\)\([A-Z]\)/\1_\2/g' \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/^un_/un/')"

  # Read-only auth handshakes, exempt on every server. Checked FIRST so no verb
  # rule below can ever deny the call that makes a server usable.
  case "$MCP_OP_LOWER" in
    *authenticate*|*complete_authentication*) : ;;
    # A SESSION RESET CLEARS A CONVERSATION, NOT DATA (PR #279 minor).
    # `..._notebooklm__reset_session` matched the `reset` verb and came back with
    # a destructive-operation message and an approval-token instruction.
    # Clearing chat history destroys nothing, and a gate that blocks routine work
    # with a scary message is a gate someone switches off.
    #
    # It sits beside the auth exemption because both are evaluated before the
    # verb rules; placed after them it never runs. My first attempt did exactly
    # that. The ordering is held by test_a_session_reset_is_allowed, which drives
    # the hook and goes red if this stops taking effect.
    #
    # `reset_branch` DOES discard a database branch's state and keeps its deny,
    # which test_supabase_reset_branch_is_denied pins.
    reset_session|reset_chat|reset_conversation) : ;;
    *)
      # Destructive verbs. Anchored at the start of the operation or after a
      # non-letter, so `untrash` (letter before the verb) does not match and
      # `trash_thread` / `_delete_x` / `-delete-x` do.
      if printf '%s' "$MCP_OP_LOWER" | grep -Eq '(^|[^a-z])(delete|destroy|purge|truncate|wipe|erase|remove|trash|revoke|reset)'; then
        emit_deny "MCP tool $TOOL_NAME performs a destructive operation ($MCP_OP)"
      fi

      # Named by the founder's CLAUDE.md or by the pre-ASK-1144 list, but not
      # verb-shaped. `unlabel_message` is here beside `unlabel_thread`: the old
      # list carried only the thread half, and one of two symmetric operations
      # being denied is an accident, not a policy.
      case "$MCP_OP_LOWER" in
        notion-move-pages|notion_move_pages|unlabel_thread|unlabel_message)
          emit_deny "MCP tool $TOOL_NAME is in the destructive set ($MCP_OP)"
          ;;
      esac

      # Vercel stays denied at the SERVER level, unchanged and deliberately.
      # CLAUDE.md says "Vercel mutating ops" and this box cannot enumerate them
      # (the server exposes only the auth pair until it is connected), so
      # narrowing it here would be guessing at a production deploy surface. The
      # resulting read over-block is real and is captured, not hidden.
      case "$TOOL_NAME" in
        mcp__plugin_vercel_vercel__*)
          emit_deny "MCP tool $TOOL_NAME is a Vercel mutating op"
          ;;
      esac
      ;;
  esac
fi

# Default: do not interfere with non-destructive calls.
log_decision "allow" "no destructive pattern matched"
exit 0
