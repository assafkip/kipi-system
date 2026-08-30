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
  if [ -x "$_ct" ] && "$_ct" check "$COMMAND" "$CWD"; then
    log_decision "allow" "capability token consumed"
    exit 0
  fi
  local _hash=""
  [ -x "$_ct" ] && _hash="$("$_ct" hash "$COMMAND" "$CWD" 2>/dev/null || true)"
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
    'git[[:space:]]+push[[:space:]]+(-[a-zA-Z]*f[a-zA-Z]*|--force)'
    'git[[:space:]]+branch[[:space:]]+-D'
    'git[[:space:]]+clean[[:space:]]+-[a-zA-Z]*[fdx]'
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
  argv_deny_reason() {  # argv_deny_reason <stage> -> echoes a reason, rc 0 = deny
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
          echo "rm carries a recursive or force flag (argv-inspected: a leading flag cannot hide it)"
          return 0
        fi
        ;;
      git)
        # Walk git's GLOBAL flags to find the subcommand: `git -C DIR reset
        # --hard` is the same act as `git reset --hard`, and the old pattern saw
        # neither.
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
            _argv_has_long hard "${ga[@]}" && { echo "git reset --hard discards the working tree"; return 0; } ;;
          push)
            if _argv_has_long force "${ga[@]}" || _argv_has_long force-with-lease "${ga[@]}" \
               || _argv_has_short f "${ga[@]}"; then
              echo "git push is forced, which rewrites published history"; return 0
            fi ;;
          branch)
            _argv_has_short D "${ga[@]}" && { echo "git branch -D deletes a branch unmerged"; return 0; } ;;
          clean)
            if _argv_has_short f "${ga[@]}" || _argv_has_short d "${ga[@]}" \
               || _argv_has_short x "${ga[@]}" || _argv_has_long force "${ga[@]}"; then
              echo "git clean removes untracked files"; return 0
            fi ;;
          filter-branch|filter-repo)
            echo "git $sub rewrites every commit in the repository"; return 0 ;;
          update-ref)
            _argv_has_short d "${ga[@]}" && { echo "git update-ref -d deletes a ref"; return 0; } ;;
        esac
        ;;
    esac
    return 1
  }

  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    _argv_reason="$(argv_deny_reason "$_stage")" && \
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
      # ASK-1131 round 4 (Codex major, PR #274). MEASURED, on this machine,
      # against a `cat > f <<EOF` heredoc of filler words -- how this fleet
      # writes RCAs and PRDs, and the input that pays the full cost because a
      # denial short-circuits and a benign command never does:
      #
      #   1000 words 1.41s   3000 words 9.93s   6000 words 34.77s
      #
      # Quadratic: every token opened a subshell that re-split the whole
      # remaining argv. Past roughly 8000 words it crosses the hook timeout, at
      # which point this gate returns NO DECISION at all -- the one failure mode
      # it cannot have. A guard nobody can afford to leave on gets switched off.
      #
      # The filter is outcome-identical, not a heuristic trade. argv_deny_reason
      # returns 1 immediately for any position whose program token is not one of
      # its `case` arms, so skipping those positions cannot change a verdict; and
      # a position that only reaches a rule THROUGH prefix-stripping always has
      # the real program token at a LATER position, which is itself a candidate
      # (`sudo -u root rm -rf x` is caught at `rm`, not at `sudo`).
      #
      # THIS LIST MUST NAME EVERY `case` ARM IN argv_deny_reason. A rule added
      # there and forgotten here would never be offered a position and would
      # read exactly like a rule that works. That is not left to memory:
      # test_candidate_list_covers_every_argv_rule parses both out of this file
      # and fails on a mismatch.
      case "${_sw[$_i]##*/}" in
        rm|git) ;;
        *) _i=$((_i+1)); continue ;;
      esac
      _argv_reason="$(argv_deny_reason "${_sw[*]:$_i}")" && \
        emit_deny "destructive invocation: $_argv_reason. Decided from the command's ARGV at every starting position, so neither a leading flag nor a prefix carrying its own options can move it out of view (ASK-1131)."
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
    _norm="${_stage//\"/}"
    _norm="${_norm//\'/}"
    _norm="${_norm//\\/}"
    [ "$_norm" = "$_stage" ] && continue
    set -f
    _dw=( "" $_norm )
    set +f
    _i=1
    while [ "$_i" -lt "${#_dw[@]}" ]; do
      # Same candidate filter as the loop above, same reason (PR #274 major).
      case "${_dw[$_i]##*/}" in
        rm|git) ;;
        *) _i=$((_i+1)); continue ;;
      esac
      _argv_reason="$(argv_deny_reason "${_dw[*]:$_i}")" && \
        emit_deny "destructive invocation: $_argv_reason. The program token was quoted or escaped; the shell strips that before exec, so this scan does too (ASK-1131)."
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
  # ASK-1118 round 2 (Codex major, PR #274). THE ARGV FIX NEVER REACHED THE FLEET
  # RULES, and the per-stage preview turned that gap into a REGRESSION: commands
  # this guard used to refuse now ran.
  #
  # Measured, before this function existed, on the branch as reviewed:
  #
  #   ALLOW  rsync -n --delete /a/ /b/ && /usr/bin/rsync -a --delete /a/ /b/
  #   ALLOW  rsync -avn --delete /a/ /b/ ; time rsync -a --delete /a/ /b/
  #   ALLOW  kipi update --dry ; env FOO=1 rsync -a --delete /a/ /b/
  #   ALLOW  "rsync" -a --delete /a/ /b/
  #   ALLOW  'rsync' -a --delete /a/ /b/
  #
  # The first two USED TO DENY. The mechanism: the preview stage sets
  # _fleet_preview, the apply stage escapes the positional FLEET_DENY regex via
  # an absolute path, a `time` prefix or a quoted name, nothing denies, and the
  # early `exit 0` below then ALLOWS the whole thing. Closing holes 1 and 3 for
  # `rm` and `git` opened a wider one on the rule the file's own comment calls
  # "strictly more destructive... this hits twenty" instances.
  #
  # A guard fix that makes the guard permit MORE than before is worse than the
  # holes it closes. Same shape as this PR's round-1 finding: a correct fix that
  # turned the gate off.
  #
  # WHY THESE TWO RULES ARE SAFE AT ANY START POSITION and the script-name rules
  # are not. `rsync` and `kipi` each demand corroborating evidence from the REST
  # of their argv -- a `--delete` flag, an `update` subcommand -- so a token that
  # merely NAMES them is inert: `ls -l /usr/bin/rsync` finds no --delete and
  # allows. `kipi-update.sh` carries no such requirement, so offering it every
  # position would deny `sed -n '1,20p' kipi-update.sh`, and the comment above
  # FLEET_DENY records why that matters: reading a file is not running it, and a
  # gate that blocks reads is a gate someone switches off. The script forms are
  # therefore reached only at the stage's own program position, which still
  # covers a transparent prefix because prefix-stripping runs first.
  fleet_argv_reason() {  # fleet_argv_reason <stage> <at-program-position> -> reason, rc 0
    local stage="$1" at_prog="$2"
    set -f
    local -a w=( $stage )
    set +f
    [ "${#w[@]}" -gt 0 ] || return 1
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
    local i tok
    case "$prog" in
      rsync)
        _argv_has_long delete "${rest[@]}" && {
          echo "rsync --delete (argv-inspected, so a path, a prefix or a quoted name cannot move it out of view)"
          return 0; }
        ;;
      kipi)
        i=1
        while [ "$i" -lt "${#rest[@]}" ]; do
          tok="${rest[$i]}"
          case "$tok" in
            -*) i=$((i+1)); continue ;;
            update) echo "kipi update (argv-inspected)"; return 0 ;;
            *) break ;;
          esac
        done
        ;;
    esac
    [ "$at_prog" = "1" ] || return 1
    case "$prog" in
      kipi-update.sh) echo "kipi-update.sh run directly"; return 0 ;;
      bash|sh|zsh|source|.)
        i=1
        while [ "$i" -lt "${#rest[@]}" ]; do
          case "${rest[$i]##*/}" in
            kipi-update.sh) echo "kipi-update.sh run through an interpreter"; return 0 ;;
          esac
          i=$((i+1))
        done
        ;;
    esac
    return 1
  }

  # One place that answers "is this stage a fleet-wide delete", used by BOTH the
  # deny arm and the preview arm below. Two callers asking the question two ways
  # is how the preview and the apply came to disagree about what a command is in
  # the first place.
  fleet_stage_reason() {  # fleet_stage_reason <stage> -> reason, rc 0
    local stage="$1" pat norm r
    # ";" is prepended so each pattern's own `[;&|][[:space:]]*` alternative
    # absorbs the stage's leading whitespace. Without it a stage starting with a
    # space matches neither `^` nor a boundary and the deny silently vanishes.
    for pat in "${FLEET_DENY[@]}"; do
      if echo ";$stage" | grep -Eq "$pat"; then echo "pattern $pat"; return 0; fi
    done
    r="$(_fleet_argv_scan "$stage")" && { echo "$r"; return 0; }
    # Quote and backslash stripped, exactly as the rm/git layer does it: the
    # shell removes them before exec, so `"rsync" -a --delete` is an rsync run.
    # Stripping can only REVEAL a program name, never hide one, so this arm is
    # deny-only and can clear nothing.
    norm="${stage//\"/}"
    norm="${norm//\'/}"
    norm="${norm//\\/}"
    if [ "$norm" != "$stage" ]; then
      r="$(_fleet_argv_scan "$norm")" && { echo "$r"; return 0; }
    fi
    return 1
  }

  _fleet_argv_scan() {  # _fleet_argv_scan <text> -> reason, rc 0
    local text="$1" i r
    set -f
    local -a sw=( "" $text )
    set +f
    r="$(fleet_argv_reason "${sw[*]:1}" 1)" && { echo "$r"; return 0; }
    # Candidate positions only, for the reason argued at length above the rm/git
    # loop: this runs on every Bash tool call and must not be quadratic.
    i=2
    while [ "$i" -lt "${#sw[@]}" ]; do
      # `rsync` ONLY, and the omission of `kipi` is load-bearing (PR #274).
      # Word-splitting does not honour quotes, so every token of a commit
      # message is offered as a program: `git commit -m "the kipi update path
      # never shipped"` read as an invocation and denied. FLEET_DENY's
      # `kipi[[:space:]]+update` has no position anchor and already catches
      # `/usr/local/bin/kipi update` and `time kipi update`, both measured, so
      # scanning for it here added no coverage and cost a real false positive.
      # The rsync entry is the anchored one, so it is the one that needs this.
      case "${sw[$i]##*/}" in
        rsync) ;;
        *) i=$((i+1)); continue ;;
      esac
      r="$(fleet_argv_reason "${sw[*]:$i}" 0)" && { echo "$r"; return 0; }
      i=$((i+1))
    done
    return 1
  }

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
      fleet_stage_reason "$_stage" >/dev/null && _fleet_preview=1
      continue
    fi
    if _fleet_reason="$(fleet_stage_reason "$_stage")"; then
      emit_deny "fleet-wide delete: this rsyncs the skeleton into EVERY registered instance with a delete flag, and a source tree missing a package removes it from all of them at once (2026-08-07: voicekit deleted from 19 instances). Preview it first with --dry-run IN ITS OWN TOOL CALL and read what will be REMOVED, not only what changes -- a preview sharing a command block with the apply does not exempt the apply (ASK-1118). Match: $_fleet_reason"
    fi
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
# Tool names that mutate or delete state at the vendor side.
case "$TOOL_NAME" in
  mcp__claude_ai_Notion__notion-move-pages \
  | mcp__plugin_Notion_notion__* \
  | mcp__claude_ai_Gmail__delete_label \
  | mcp__claude_ai_Gmail__unlabel_thread \
  | mcp__claude_ai_Google_Calendar__delete_event \
  | mcp__plugin_linear_linear__* \
  | mcp__plugin_vercel_vercel__* )
    # Allow read-only auth variants explicitly
    case "$TOOL_NAME" in
      *authenticate*|*complete_authentication*) exit 0 ;;
    esac
    emit_deny "MCP tool $TOOL_NAME is in the destructive set"
    ;;
esac

# Default: do not interfere with non-destructive calls.
log_decision "allow" "no destructive pattern matched"
exit 0
