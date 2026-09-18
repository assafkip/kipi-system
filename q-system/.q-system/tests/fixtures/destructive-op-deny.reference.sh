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
#
# WHAT THIS GUARD COVERS: DIRECT INVOCATION ONLY (ASK-1247, 2026-09-13).
# It reads the command STRING and denies the programs it knows by name. It
# does not see effects, so the same delete performed by an interpreter walks
# through at exit 0. Measured by q-system/.q-system/tests/probe_hook.py:
#
#   ALLOW  python3 -c "import shutil; shutil.rmtree(...)"
#   ALLOW  python3 -c "import os; os.unlink(...)"
#   ALLOW  node -e "require('fs').rmSync(..., {recursive: true})"
#   ALLOW  perl -e 'unlink(...)'
#   ALLOW  bash /path/to/script.sh   (the script body is never read)
#
# Read this hook as "an agent cannot TYPE the named command", never as "an
# agent cannot delete a directory". Adding interpreter patterns here is
# decided against: the payload can be built at runtime, read from a file or
# base64'd, and a parser that decides a string is harmless is a new bypass
# surface. Closing the gap means moving the boundary to the filesystem or
# syscall layer, which is a PRD, not a pattern. Decision: RULE-2026-09-13-A
# in q-system/canonical/decisions.md. test_destructive_guard_interpreter_bound.py
# pins this paragraph to the probe: if a row above starts being denied, the
# test goes red and this paragraph gets rewritten, not left standing.

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

  # PLACED ABOVE THE _fleet_preview EARLY EXIT (round 2 of PR 323). The first cut
  # sat after it, so one preview stage anywhere in the block set _fleet_preview and
  # exited before either layer ran: `X --dry-run && ( X --only Y )` was ALLOWED,
  # the exact hazard ASK-1118 names. Measured, then moved.
  # ==================================================================== sp-37c08fb1
  # THE FLEET UPDATER AS A SCRIPT FILE, WITH ANY PATH PREFIX OR NONE.
  #
  # FLEET_DENY entry 3 is `[./~][^[:space:]]*kipi-update\.sh`: it requires the path
  # to START with a dot, a slash or a tilde. Measured 2026-09-07 by DRIVING this
  # hook, not by reading it -- the ledger item said the CLI phrase was the only
  # fleet pattern and that was already stale, PR #269 had closed two of the four
  # shapes. Re-measuring is what found the two that were left:
  #
  #   cd DIR && ./kipi-update.sh --only X       DENY   (entry 3)
  #   bash /abs/path/kipi-update.sh             DENY   (entry 2)
  #   /abs/path/kipi-update.sh                  DENY   (entry 3)
  #   projects/kipi-scheduled/kipi-update.sh    ALLOW  <- unmatched, real fleet sync
  #   kipi-update.sh --only X                   ALLOW  <- unmatched
  #   FOO=bar kipi-update.sh --only X           ALLOW  <- unmatched
  #
  # APPENDED RATHER THAN MERGED INTO ENTRY 3, for two independent reasons. The only
  # write path an agent has into ~/.claude is apply-claude-changes, whose `replace`
  # op is pinned to rule TEXT, so an in-place predicate edit cannot reach the live
  # hook at all -- it would land in the repo and never install. And
  # test_destructive_op_deny_anchor.py asserts FLEET_DENY holds exactly four
  # entries, three of them anchored; a fifth entry turns a passing guard test red
  # for a reason that has nothing to do with the guard.
  #
  # STILL ANCHORED AT COMMAND POSITION. The comment above FLEET_DENY records that an
  # unanchored first attempt blocked a `sed -n` read of this same filename, and
  # reading a file is not running it. `cat kipi-update.sh` stays allowed.
  #
  # kipi-update-instance-ahead.py is read-only and ends in .py, so a basename match
  # on kipi-update.sh cannot reach it in any of its three call shapes.
  #
  # Preview stages are skipped through the SAME predicate the block above uses, so
  # the dry-run flag alone in its own tool call still passes.
  # A SUBSHELL OR A GROUP OPENS A NEW COMMAND POSITION. The exact shape that ran
  # unchallenged on 2026-09-07 06:08Z was `cd DIR && ( ./kipi-update.sh --only X
  # > log 2>&1 & )`: after the `&&` split the stage begins with `(`, which is
  # neither the anchor nor a path, so every anchored layer above walked past it.
  # Measured 2026-09-07 by driving both the live hook and this fixture with that
  # command: ALLOW on both before this line. `([({][[:space:]]*)*` skips any run
  # of opening parens or braces; the path still has to be the command itself, so
  # `( cat kipi-update.sh )` stays a read.
  # Transparent prefixes and a quoted path, round 2: `timeout 900 X`, `setsid X`,
  # `exec X`, `eval X` and `"./X"` were each measured ALLOW with the real updater
  # present. The prefix list is the one argv_deny_reason already carries plus the
  # three that hand the stage to their argument unchanged; timeout eats its
  # duration. A quote on either side of the path is skipped, never required.
  _FLEET_PREFIX_RE='(sudo|command|nohup|nice|time|env|exec|setsid|eval|timeout[[:space:]]+[^[:space:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*)'
  # An interpreter in front of the path is the same run: FLEET_DENY entry 2 covers
  # it at the top of a stage, and nowhere else, so `( bash PATH )` and a wrapper
  # line `bash PATH` were both unmatched (round 2 of PR 323). No flags between
  # the interpreter and the path, so `bash -n PATH` stays a syntax check.
  _FLEET_SCRIPT_RE='(^|[;&|][[:space:]]*)([({][[:space:]]*)*('"$_FLEET_PREFIX_RE"'[[:space:]]+)*((bash|sh|zsh|ksh|dash|source)[[:space:]]+)?["'"'"']?[^[:space:]"'"'"']*kipi-update\.sh["'"'"']?([[:space:]]|$)'
  # The CLI spelling at command position, for the wrapper scan below. The bare
  # FLEET_DENY entry 1 is unanchored on purpose for the command line (ASK-1118);
  # inside a script body an unanchored match reads a help string as a run.
  _FLEET_CLI_RE='(^|[;&|][[:space:]]*)([({][[:space:]]*)*('"$_FLEET_PREFIX_RE"'[[:space:]]+)*kipi[[:space:]]+update([[:space:]]|$)'
  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    fleet_stage_is_preview "$_stage" && continue
    # ";" prepended for the same reason as the block above: a stage whose boundary
    # was consumed by the split matches neither `^` nor `[;&|]` without it.
    if echo ";$_stage" | grep -Eq "$_FLEET_SCRIPT_RE"; then
      emit_deny "fleet-wide delete: this stage runs kipi-update.sh directly. Matching the CLI phrase alone missed the script form with a bare or non-dot-prefixed path, which is how a real sync ran unchallenged on 2026-09-07 (sp-37c08fb1). Preview it first with --dry-run IN ITS OWN TOOL CALL and read what will be REMOVED, not only what changes."
    fi
  done < <(printf '%s\n' "$COMMAND" | tr ';|&' '\n\n\n')

  # ==================================================================== sp-dc76e644
  # A WRAPPER SCRIPT IS A DESTRUCTIVE OP WEARING A FILENAME.
  #
  # THE SCAR, measured 2026-09-06 14:55 PDT. ~/.config/kipi/consulting-sync-run.sh
  # set the founder bypass INSIDE ITS OWN TEXT. So the Bash command string this hook
  # sees was `bash ~/.config/kipi/consulting-sync-run.sh --verify-only`, which
  # carries no destructive pattern of any kind, every layer above it passed, and a
  # real fleet sync ran on consulting and reverted a deliberate instance commit four
  # minutes after it landed. The bypass is supposed to require conscious action in
  # the founder's own shell; a script that assigns it hands that action to whoever
  # types the script's name.
  #
  # So the target of a script invocation is READ, bounded, before it runs.
  #
  # TWO RULES, NOT ONE, and the split is the whole design:
  #
  #   a bypass ASSIGNMENT denies unconditionally. A --dry-run on the wrapper says
  #   nothing about whether the wrapper arms the bypass for what it calls.
  #
  #   a FLEET_DENY pattern in the body follows the same preview exemption as a
  #   direct match, so `bash kipi-update.sh --dry` keeps passing.
  #
  # COMMENT LINES ARE DROPPED FIRST, and that is not the prose-versus-invocation
  # distinction this file refused in 2026-08-07. That refusal was about the COMMAND
  # STRING, where `bash <<'EOF'` executes its own body and any parser deciding "this
  # is only prose" becomes a bypass surface. Here the subject is a FILE, `#` is the
  # shell's own comment marker, and a commented line cannot execute. Measured over
  # the 212 tracked .sh files in this repo: the comment drop alone still refused
  # 20 of them (measured 2026-09-07, round 2 of PR 323), so the drop is necessary
  # and not sufficient; the command-position read below is what brings the count
  # down to the scripts that run the updater. A gate red on its population gets
  # switched off, and a gate that is off protects nothing.
  #
  # ACCEPTED COST, stated rather than discovered later: the updater's own test
  # scripts, which run it at command position, now need `kipi-approve` to be run
  # through the Bash tool. That is the fail-closed side, and the out-of-band
  # approval already exists for exactly this.
  #
  # `bash -n FILE` is a SYNTAX CHECK, not a run, so it is skipped -- same reason the
  # patterns above are anchored at command position. Blocking a read gets the gate
  # switched off.
  # ANCHORED AT COMMAND POSITION, round 2. The first cut matched the token
  # anywhere in a line, so this hook's own deny text (`set ALLOW_DESTRUCTIVE=1 to
  # bypass all`, a code line inside an echo, not a comment) refused the fixture
  # and the capability-token installer, the escape hatch this design leans on.
  # An assignment is a stage that BEGINS with the assignment.
  _BYPASS_ASSIGN_RE='(^|[;&|][[:space:]]*)([({][[:space:]]*)*(export[[:space:]]+|env[[:space:]]+)?ALLOW_DESTRUCTIVE[[:space:]]*='

  # Echoes the path of the script a stage RUNS, rc 0. rc 1 means "this stage runs no
  # readable script file", which is the overwhelmingly common case and must be cheap.
  _fleet_script_target() {
    local stage="$1"
    set -f
    local -a w=( "" $stage )
    set +f
    w=( "${w[@]:1}" )
    [ "${#w[@]}" -gt 0 ] || return 1
    # Same transparent-prefix list as argv_deny_reason above. Not shared with it
    # because that function answers a different question and returning two values
    # from one bash function is worse than repeating six words.
    while [ "${#w[@]}" -gt 0 ]; do
      case "${w[0]}" in
        # A subshell or a group opens a new command position, the same shape the
        # regex above skips. `( bash wrapper.sh )` after an && split tokenises to
        # `(` then `bash`, and `(bash` when the paren is glued; either way the
        # program token was the paren, the scan returned rc 1, and the wrapper's
        # text was never read. Measured 2026-09-07 with a wrapper that assigns the
        # bypass: the plain form was DENY, every paren or brace form was ALLOW.
        \(|\{)                           w=( "" "${w[@]:1}" ); w=( "${w[@]:1}" ) ;;
        \(*|\{*)                         w[0]="${w[0]#[\(\{]}" ;;
        \"*|\'*)                         w[0]="${w[0]#[\"\']}" ;;
        *=*)                             w=( "" "${w[@]:1}" ); w=( "${w[@]:1}" ) ;;
        sudo|command|nohup|nice|time|env|exec|setsid|eval) w=( "" "${w[@]:1}" ); w=( "${w[@]:1}" ) ;;
        timeout)                         w=( "" "${w[@]:2}" ); w=( "${w[@]:1}" ) ;;
        *) break ;;
      esac
    done
    [ "${#w[@]}" -gt 0 ] || return 1
    # The closing half of the same shape: `(bash w.sh)` glues the paren to the
    # last argument and `( ./w.sh )` can leave it on the path, so the file lookup
    # below misses by one character. Trailing parens and braces are not part of
    # any path this scanner is asked to read.
    local _i
    for _i in "${!w[@]}"; do
      while :; do
        case "${w[$_i]}" in
          *\)|*\}|*\"|*\') w[$_i]="${w[$_i]%?}" ;;
          *) break ;;
        esac
      done
    done
    local prog="${w[0]##*/}" cand="" tok
    case "$prog" in
      bash|sh|zsh|ksh|dash|source|.)
        # Seeded with "" for the bash 3.2 set -u reason documented above.
        local -a r=( "" "${w[@]:1}" )
        for tok in "${r[@]}"; do
          [ -n "$tok" ] || continue
          case "$tok" in
            -*n*)
              case "$tok" in
                --*) continue ;;   # --norc contains an n and is not noexec
                *) return 1 ;;     # -n really is "read, do not execute"
              esac ;;
            -*) continue ;;
          esac
          cand="$tok"; break
        done ;;
      *.sh) cand="${w[0]}" ;;
    esac
    [ -n "$cand" ] || return 1
    case "$cand" in
      "~") return 1 ;;
      "~"/*) cand="$HOME/${cand#\~/}" ;;
    esac
    case "$cand" in
      /*) : ;;
      *) [ -n "$CWD" ] && cand="$CWD/$cand" ;;
    esac
    [ -f "$cand" ] && [ -r "$cand" ] || return 1
    printf '%s' "$cand"
    return 0
  }

  while IFS= read -r _stage; do
    [ -n "$_stage" ] || continue
    _target="$(_fleet_script_target "$_stage")" || continue
    # Bounded on purpose: the updater itself is 145 KB and this runs on every Bash
    # tool call. 64 KB is far past where a wrapper declares its environment.
    # THE BODY IS READ AS COMMANDS, NOT AS TEXT (round 2). The first cut grepped
    # the whole body for every FLEET_DENY pattern. Measured 2026-09-07 on this
    # repo: 20 of 212 tracked scripts refused, among them an install hint that
    # echoes the CLI phrase, a script that carries it inside a Python string, and
    # the capability-token installer; across the founder's projects, 1933 of the
    # 5276 scripts carrying any matchable token. A gate red on that population
    # gets switched off. So every non-comment line is split into stages the way
    # the command line is, and only a stage whose COMMAND is the updater, or
    # whose command is an assignment of the bypass, counts. A backup script's
    # rsync is not the fleet updater and is not matched here at all.
    # Six process spawns per script, not one per stage: the first cut of this
    # read looped a grep over every stage of every line and a population sweep
    # that took nine minutes stopped finishing at all. Every stage is put on its
    # own line with the same split the command line gets, prefixed with the
    # boundary the anchored patterns expect, and matched once per pattern.
    _bstages="$(head -c 65536 "$_target" 2>/dev/null | grep -v '^[[:space:]]*#' | tr ';|&' '\n\n\n' | sed 's/^/;/')"
    _bypass_hit=0; _fleet_hit=""
    if printf '%s\n' "$_bstages" | grep -Eq "$_BYPASS_ASSIGN_RE"; then _bypass_hit=1; fi
    # A preview stage inside the body is exempt the way one on the command line is.
    _fleet_hit="$(printf '%s\n' "$_bstages" | grep -v -- '--dry' | grep -E -m1 "$_FLEET_CLI_RE|$_FLEET_SCRIPT_RE" || true)"
    if [ "$_bypass_hit" = "1" ]; then
      emit_deny "wrapper script arms the founder bypass in its own text: $_target. The bypass exists to require conscious action in the founder's own shell, and an agent cannot set it for itself; a script that assigns it hands that action to whoever types the script's name. On 2026-09-06 exactly this ran a real fleet sync on consulting and reverted a deliberate commit (sp-dc76e644). Fix the script to REFUSE unless the bypass comes from the calling shell."
    fi
    fleet_stage_is_preview "$_stage" && continue
    if [ -n "$_fleet_hit" ]; then
      emit_deny "wrapper script runs the fleet updater: $_target carries the stage [${_fleet_hit}] at command position in its own text (the leading semicolon is the stage boundary), so this command rsyncs the skeleton into EVERY registered instance with a delete flag while the command line itself looks harmless (sp-dc76e644). Preview it first with --dry-run IN ITS OWN TOOL CALL and read what will be REMOVED, not only what changes."
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
