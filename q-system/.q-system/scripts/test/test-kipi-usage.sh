#!/usr/bin/env bash
# Reproducer + acceptance criterion for "the kipi directive help line is
# unquoted" (ASK-208, PR #22 review round 4, finding 2).
#
# THE DEFECT: the line added for `kipi directive` was
#
#   echo "  kipi directive <ASK-n> "<text>"  Standing instruction ...
#   kipi dor [--apply]   ..."
#
# Bash closes the string at `"<`, so `<text>` parses as a REDIRECTION. `bash -n`
# passes; the damage is semantic. `kipi help` printed a "No such file or
# directory" error, exited 1, and dropped BOTH its own line and the pre-existing
# `kipi dor` line. `usage` is the `*` fallthrough, so every typo'd subcommand
# hit it too. Where a file named `text` happened to exist in the cwd, the
# redirection SUCCEEDED and silently truncated it.
#
# WHY THE ASSERTIONS ARE SHAPED THIS WAY: "grep for the two missing lines" would
# have caught this one instance and nothing else. A stray redirection anywhere in
# usage shows up as an exit code, a stderr line, or a file touched in the cwd, so
# those three are asserted directly and catch the whole class.
#
# Case 5 is the deterministic half of wiring-check.md's "a new command is
# registered": `kipi help` IS the registration surface for kipi subcommands (no
# peer -- review, work, converge, jobs -- is listed in CLAUDE.md either), so a
# subcommand the case statement handles and usage never mentions is unreachable
# by anyone who did not read the source.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
KIPI="$ROOT/kipi"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$KIPI" ] || fail "the kipi CLI does not exist at $KIPI"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/empty"

# --- 1. kipi help exits 0 and says nothing on stderr ------------------------
( cd "$WORK/empty" && bash "$KIPI" help ) >"$WORK/help.out" 2>"$WORK/help.err"
RC=$?
[ "$RC" = "0" ] \
  || fail "kipi help exited $RC. stderr: $(cat "$WORK/help.err")"
[ ! -s "$WORK/help.err" ] \
  || fail "kipi help wrote to stderr: $(cat "$WORK/help.err")"
ok "kipi help exits 0 with an empty stderr"

# --- 2. it touches nothing in the working directory ------------------------
# The general detector for the whole redirection class: usage only prints. Any
# stray `>` or `<` in it shows up here regardless of which line it is on.
LEFT="$(ls -A "$WORK/empty" | tr '\n' ' ')"
[ -z "$LEFT" ] \
  || fail "kipi help created files in the cwd: $LEFT -- a line in usage is being
      parsed as a redirection instead of printed"
ok "kipi help creates no files in the working directory"

# The amplification the reviewer measured: where the redirect target already
# exists, the redirection SUCCEEDS and truncates it, so there is no error to see.
printf 'PRECIOUS\n' > "$WORK/empty/text"
( cd "$WORK/empty" && bash "$KIPI" help ) >/dev/null 2>&1
[ "$(cat "$WORK/empty/text")" = "PRECIOUS" ] \
  || fail "kipi help TRUNCATED a file named 'text' in the cwd. A usage line is
      being parsed as `> text`."
ok "an existing file named 'text' in the cwd survives kipi help untouched"
rm -f "$WORK/empty/text"

# --- 3. the lines the broken quoting swallowed are present ------------------
grep -q "kipi directive" "$WORK/help.out" \
  || fail "kipi directive is missing from kipi help; the command it documents is
      undiscoverable. Output ended: $(tail -3 "$WORK/help.out")"
ok "kipi help lists kipi directive (the command this PR added)"
grep -q "kipi dor" "$WORK/help.out" \
  || fail "kipi dor is missing from kipi help -- a PRE-EXISTING line taken out by
      the same broken quoting"
ok "kipi help still lists kipi dor (the collateral line)"

# --- 4. the fallthrough is usable ------------------------------------------
# `*` routes every unrecognized subcommand here, so a broken usage turns any
# typo into an error instead of help.
( cd "$WORK/empty" && bash "$KIPI" not-a-real-subcommand ) >"$WORK/typo.out" 2>"$WORK/typo.err"
TRC=$?
[ "$TRC" = "0" ] || fail "a typo'd subcommand exited $TRC: $(cat "$WORK/typo.err")"
[ ! -s "$WORK/typo.err" ] || fail "a typo'd subcommand wrote to stderr: $(cat "$WORK/typo.err")"
diff -q "$WORK/help.out" "$WORK/typo.out" >/dev/null \
  || fail "the fallthrough prints something different from kipi help"
ok "an unrecognized subcommand falls through to the same clean usage"

# --- 5. every subcommand the CLI handles is documented ---------------------
# wiring-check.md: a new command has to be registered. usage is the registration
# surface, so an undocumented case label is a command only the source reveals.
MISSING=""
while IFS= read -r label; do
  case "$label" in help|--help|-h|'*') continue ;; esac
  grep -q "kipi $label" "$WORK/help.out" || MISSING="$MISSING $label"
done < <(sed -n 's/^  \([a-z][a-z-]*\))$/\1/p' "$KIPI")
[ -z "$MISSING" ] \
  || fail "subcommands the CLI handles but kipi help never mentions:$MISSING"
ok "every subcommand in the case statement appears in kipi help"

bash -n "$KIPI" || fail "the kipi CLI does not parse"
ok "the kipi CLI parses (bash -n)"

echo "PASS: kipi usage ($PASS checks)"
