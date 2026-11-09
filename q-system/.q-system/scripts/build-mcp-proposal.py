#!/usr/bin/env python3
"""Regenerate proposals/mcp-denylist-operation-split.json from the shell text.

The proposal's payload is one long shell insert living inside a JSON string.
Hand-editing escaped shell inside JSON is how a subtle quoting defect gets into
a security gate, so the shell is written here as ordinary source and the JSON is
GENERATED. One writer for that file; run this, never edit the JSON by hand.

    python3 q-system/.q-system/scripts/build-mcp-proposal.py
    python3 q-system/.q-system/scripts/build-mcp-proposal.py --check
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROPOSAL = HERE.parent / "proposals" / "mcp-denylist-operation-split.json"

ANCHOR = "# ---- MCP destructive tool denials ----\n"

INSERT = r'''# ---- MCP read/write split, keyed on the OPERATION (ASK-1923, 2026-09-20) ----
# The block BELOW matches SERVER-NAME wildcards. That shape is wrong twice over,
# and the two errors hide each other:
#
#   OVER-BROAD   a wildcard on a namespace denies that server's READS too.
#                mcp__plugin_linear_linear__list_issues, __get_issue,
#                mcp__plugin_vercel_vercel__list_deployments and
#                mcp__plugin_Notion_notion__notion-search all measured DENY.
#                The only carve-out was *authenticate*.
#   UNDER-BROAD  the namespaces it names are not the ones that load. The
#                registered Linear server is mcp__linear__, not
#                mcp__plugin_linear_linear__, so mcp__linear__delete_issue
#                measured ALLOW -- and the founder's global CLAUDE.md names
#                Linear *delete* as hook-blocked regardless of mode.
#                mcp__supabase__delete_branch was on no list at all.
#                A wildcard on a name nobody calls reads exactly like protection.
#
# So the rule is keyed on the OPERATION, which is stable across servers, instead
# of on a server name, which is not. It runs FIRST so its read-only exit
# short-circuits the wildcards below.
#
# IT LOOSENS AS WELL AS TIGHTENS, AND THAT IS SAID OUT LOUD. apply-claude-changes
# is additive-only so an agent cannot widen a gate; an early `exit 0` is the one
# shape that gets around that. It is named here rather than smuggled. What the
# read-verb list opens is reads and, at most, non-destructive writes: `resolve`
# was on it and mcp__linear__resolve_diff_thread WRITES, so `resolve` came off
# (PR #390 review). Nothing on the list now reaches a write on the namespaces
# the block below wildcards.
#
# Measured in both directions, by RUNNING the matcher, by
# q-system/.q-system/scripts/mcp-denylist-namespace-check.py; its cases are
# pinned by q-system/.q-system/tests/test_destructive_op_mcp_namespace.py, which
# drives this exact insert against a copy and watches each direction flip.
#
# `drop` is NOT on the destructive list. It reads as the SQL verb and the only
# operations that match it here are mcp__playwright__browser_drop and its drag
# partner -- a mouse gesture, denied with a message about vendor-side deletion
# (PR #390 review). A gate that blocks a mouse move is a gate someone switches
# off. If a server ever exposes a real DROP, add that operation by name.
#
# AND IT IS FAIL-CLOSED ON A VERB IT CANNOT PLACE. `loop_force_close` on the
# local kipi plugin matches `force_close` and is refused, with a message that
# now says only what the gate knows: an operation verb matched, and this gate
# cannot see whether the state removed sits at a vendor or on this machine (PR
# #390 review round 3). That asymmetry is the same one emit_deny already
# argues below -- the miss costs production data, the false positive costs one
# approval. `drop` is different and stays OFF the list: browser_drop moves a
# mouse and removes no state at all, so refusing it buys nothing.
MCP_DESTRUCTIVE_OP='(^|[_-])(delete|destroy|purge|wipe|erase|remove|trash|truncate|revoke|unlabel|reset|move[_-]pages|force[_-]close)([_-]|$)'
MCP_READ_OP='(^|[_-])(list|get|read|search|query|fetch|describe|status|check|find|show|count|suggest)([_-]|$)'
# Some operations carry their destruction in the PAYLOAD and not in the name.
# mcp__supabase__execute_sql reads as ordinary and runs `DROP TABLE`;
# apply_migration reads as routine and drops a column. Both measured ALLOW while
# the checker printed OK, because the oracle had no case for them (PR #390 review
# round 3, major). Keyed on the STATEMENT, so a SELECT and an additive migration
# still run -- a gate that refuses every query is a gate someone switches off.
# The separator alternation includes `\\n` because TOOL_INPUT is compact JSON,
# where a newline is the two characters backslash and n.
#
# NO LIST OF NAMES ON EITHER SIDE OF THIS RULE, ON PURPOSE, AND THAT TOOK THREE
# ROUNDS. The same shape was found wrong three times in three spellings:
#   PR #390 round 4   an OBJECT keyword list made the PostgreSQL object
#                     mandatory, so `TRUNCATE users;` and
#                     `ALTER TABLE users DROP email;` allowed.
#   PR #686 round 4   the same list, grown, still allowed `TRUNCATE users;`,
#                     `DROP CONSTRAINT` and `DROP TRIGGER`.
#   PR #686 round 5   with the objects gone, the OPERATION-NAME gate
#                     (`MCP_SQL_OP`: execute_sql / apply_migration / run_sql)
#                     was the same defect one layer out:
#                     `mcp__supabase__run_notebook` carrying `DROP TABLE`
#                     allowed, because nobody had listed that name.
# A list of the things that can carry a destructive statement is wrong until
# someone meets the entry it is missing, so the operation gate is GONE. The
# payload of EVERY MCP call is read. The destruction is in the statement, and the
# statement is the only place this rule looks.
#
# WHAT KEEPS THAT FROM REFUSING ORDINARY PROSE IS STATEMENT POSITION, NOT A LIST.
# Dropping the operation gate points this rule at Gmail bodies, Linear
# descriptions and Notion pages, where the English word "drop" is ordinary. So
# the verb has to sit where a SQL statement starts: at the beginning of a JSON
# string value, after a `;`, or after a newline -- or be reached through an
# `ALTER`, which is how a column, a constraint and a trigger are destroyed. SQL's
# top-level statement verbs are a closed set in the grammar; the vendor's object
# types are not, which is the difference between this and the list it replaces.
#
# IT STILL OVER-REFUSES, AND HERE IS EXACTLY WHERE. Said out loud rather than
# discovered next round: this gate parses no SQL. A message body that BEGINS
# "Drop the legacy flag" is refused, and so is a search for the literal phrase
# "drop table". It cannot tell a `DELETE FROM` that runs from one sitting in a
# trigger body an additive migration is defining, and it refuses both (PR #390
# review round 4, minor). The asymmetry is emit_deny's own -- a miss costs a
# production table, a false positive costs one approval -- and the deny message
# says the gate refused on a keyword in statement position rather than claiming
# it understood the statement.
MCP_DESTRUCTIVE_SQL='(^|[;"]|\\n)[[:space:]]*(drop|truncate)([[:space:]]|\\n)|(^|[;"]|\\n)[[:space:]]*delete([[:space:]]|\\n)+from([^a-zA-Z_]|$)|(^|[;"]|\\n)[[:space:]]*alter([[:space:]]|\\n)[^;"]*[^a-zA-Z_](drop|truncate)([[:space:]]|\\n)'
# Servers where EVERY non-read op is denied, not only a destructive verb
# (founder CLAUDE.md: "Vercel mutating ops"). Matched case-INSENSITIVELY against
# the server segment: the registered connector is mcp__claude_ai_Vercel__, with
# a capital V, and a case-sensitive match missed it -- the same server-name miss
# this whole insert exists to fix (PR #390 review).
MCP_MUTATION_SCOPED_SERVER='(^|_)vercel(_|$)'
# Auth is how you EARN the connection, so it is never blocked. The block below
# carves it out as `*authenticate*` against the WHOLE TOOL NAME, which is two
# holes: it matched any server (not the 7 it names), and `*auth*`-shaped
# substrings anywhere in an operation name walked past every rule after it (PR
# #390 review round 4, minor). `mcp__claude_ai_Vercel__update_auth_settings` is
# a mutating op on a mutation-scoped server and a substring carve-out hands it
# over. So this is an ANCHORED ALLOWLIST of whole operation names, taken from the
# operations that actually load. A new auth operation has to be added by name --
# correct for a carve-out in a security gate, where the cost of guessing wide is
# a bypass and the cost of guessing narrow is one approval.
MCP_AUTH_OP='^(authenticate|authorize|re[_-]?auth|re[_-]?authenticate|setup[_-]auth|auth[_-]setup|complete[_-]authentication|notion-complete-mcp-setup)$'
# RULINGS MADE BELOW THIS INSERT ARE NOT THIS INSERT'S TO REVERSE.
#
# This block runs FIRST, before the guard's own MCP section, which is the whole
# point of the read-only exit. The cost of running first is that every ALLOW
# ruling further down the file is one this block can silently overturn, and it
# overturned two (PR #686 review round 5, major):
#
#   GMAIL TRASH    allowed by the FOUNDER on 2026-10-29 (ASK-3361). He asked for
#                  bots that clean his inbox, was shown this hook denying the
#                  connector's trash in every bot run, was offered three fixes
#                  and picked lifting it here. Trash is not deletion: Gmail keeps
#                  it 30 days and untrash_thread / untrash_message restore it.
#                  The `trash` verb above denied it anyway, and this PR's oracle
#                  pinned that reversal as correct, which is the worse half.
#   SESSION RESET  allowed by review (PR #279): `..._notebooklm__reset_session`
#                  clears a conversation and destroys no data. The `reset` verb
#                  above denied it with a destructive-operation message and an
#                  approval-token instruction, which is how a gate gets switched
#                  off. `reset_branch` is a database branch and keeps its deny.
#
# EXACT NAMES ON BOTH, and the Gmail one on the WHOLE TOOL NAME rather than the
# operation, because `trash_thread` is shared: Drive's trash_file and any other
# server's trash_* keep the verb rule's deny. The founder ruled on one server.
#
# This is a mirror of a decision whose owner is the guard, so it is a second
# source of truth and it is covered as one: the suite DERIVES every ruling out of
# the installed guard at run time and requires the patched guard to still allow
# each (test_the_patch_honors_every_ruling_the_guard_makes_below_it). A new
# ruling landing below with no entry here turns that case red instead of being
# discovered by the founder when his bot stops working.
MCP_RULED_ALLOW_TOOL='^mcp__claude_ai_Gmail__trash_(thread|message)$'
MCP_RULED_ALLOW_OP='^(reset[_-]?session|reset[_-]?chat|reset[_-]?conversation)$'

case "$TOOL_NAME" in
  mcp__*)
    _mcp_rest="${TOOL_NAME#mcp__}"
    _mcp_server="${_mcp_rest%%__*}"
    _mcp_op="${_mcp_rest#*__}"
    # SCOPE THE APPROVAL TOKEN TO THIS CALL, AND KEEP THE PAYLOAD OUT OF THE LOG.
    # emit_deny hashes "$COMMAND" plus "$CWD", and an MCP payload has no
    # .tool_input.command -- so every MCP denial in one cwd hashed the EMPTY
    # STRING, and one `kipi-approve` for a Gmail delete_label was consumed by the
    # next Calendar delete_event. That is exactly the ambient authority the token
    # exists to remove (PocketOS 2026-05-17; PR #390 review, major).
    #
    # Binding to the VERBATIM tool_input fixed that and opened a second hole:
    # log_decision writes "$COMMAND" into $HOME/.claude/audit/destructive-op-deny.log
    # in plaintext, so every MCP argument -- label ids, message bodies, tokens --
    # was written to disk on both the deny and the allow path (PR #390 review
    # round 3, minor). A DIGEST binds the grant exactly as tightly (a different
    # payload is a different hash) and logs nothing readable. Assigned before any
    # block can deny, so the SERVER-NAME block below inherits the scoping too.
    #
    # If neither digest tool resolves, the raw payload is used rather than
    # nothing: the per-call binding is the security property, log hygiene is not
    # worth trading for it.
    _mcp_scope="$(printf '%s' "${TOOL_INPUT:-}" | shasum -a 256 2>/dev/null | cut -d' ' -f1)"
    [ -n "$_mcp_scope" ] || _mcp_scope="$(printf '%s' "${TOOL_INPUT:-}" | sha256sum 2>/dev/null | cut -d' ' -f1)"
    [ -n "$_mcp_scope" ] || _mcp_scope="${TOOL_INPUT:-}"
    COMMAND="$TOOL_NAME $_mcp_scope"
    # The guard's own ALLOW rulings, honored BEFORE any rule here can refuse
    # them. First, because that is where the guard itself puts them and because
    # a ruling that only survives when no other rule matches is not a ruling.
    if echo "$TOOL_NAME" | grep -Eq "$MCP_RULED_ALLOW_TOOL" \
       || echo "$_mcp_op" | grep -Eqi "$MCP_RULED_ALLOW_OP"; then
      log_decision "allow" "ruled allowed by the guard below this insert and honored here: gmail trash (founder, 2026-10-29, ASK-3361) / a session reset clears a conversation and not data (PR #279)"
      exit 0
    fi
    if echo "$_mcp_op" | grep -Eqi "$MCP_DESTRUCTIVE_OP"; then
      emit_deny "MCP operation '$_mcp_op' on server '$_mcp_server' matches a destructive-operation verb. This gate cannot see whether the state it removes is at the vendor or on this machine, so it refuses either way: the miss costs production data, the false positive costs one approval. Keyed on the operation, not the server name (ASK-1923)"
    fi
    if echo "${TOOL_INPUT:-}" | grep -Eqi "$MCP_DESTRUCTIVE_SQL"; then
      emit_deny "MCP operation '$_mcp_op' on server '$_mcp_server' carries DROP, TRUNCATE or DELETE FROM in STATEMENT POSITION in its payload. This gate does not parse SQL: it refused on the keyword where a statement starts, and it cannot tell a statement that runs from one being defined. No operation-name list, because run_notebook was missing from the last one: every MCP payload is read. So a SELECT, an additive migration, a column named 'raindrop' and the word 'drop' mid-sentence still run, while a value that BEGINS 'Drop ...' is refused (ASK-1923)"
    fi
    # AFTER the destructive checks, never before them. The carve-out is an
    # anchored allowlist now, so no destructive name can reach it either way --
    # the order is the second layer, kept so widening the allowlist later cannot
    # silently reopen the hole the substring match opened (PR #390 round 4).
    if echo "$_mcp_op" | grep -Eqi "$MCP_AUTH_OP"; then
      log_decision "allow" "mcp auth operation '$_mcp_op'"
      exit 0
    fi
    if echo "$_mcp_server" | grep -Eqi "$MCP_MUTATION_SCOPED_SERVER" \
       && ! echo "$_mcp_op" | grep -Eqi "$MCP_READ_OP"; then
      emit_deny "MCP operation '$_mcp_op' mutates '$_mcp_server', where every non-read operation is denied (founder CLAUDE.md: Vercel mutating ops)"
    fi
    if echo "$_mcp_op" | grep -Eqi "$MCP_READ_OP"; then
      log_decision "allow" "mcp read-only operation '$_mcp_op'"
      exit 0
    fi
    ;;
esac

'''

REASON = (
    "ASK-1923: the hook's MCP denylist is a set of SERVER-NAME wildcards and is "
    "wrong in both directions -- it denies read-only queries on the namespaces it "
    "names, and the namespaces it names are not the ones that load, so "
    "mcp__linear__delete_issue and mcp__supabase__delete_branch measure ALLOW "
    "against the founder's global CLAUDE.md. This inserts an OPERATION-keyed "
    "read/write split ahead of the wildcards, and scopes the capability-token "
    "grant to the call (emit_deny hashed an empty $COMMAND for every MCP denial, "
    "so one approval unlocked any other) as a DIGEST, because the guard's audit "
    "log records $COMMAND in plaintext. It also denies a destructive SQL "
    "statement carried in an MCP payload (mcp__supabase__execute_sql running "
    "DROP TABLE), which no operation name reveals. THIS EDIT LOOSENS AS WELL AS TIGHTENS, "
    "which additive-only ops normally cannot express: its read-verb branch exits 0 "
    "before the wildcards below can fire. That is stated in the inserted comment "
    "rather than smuggled. Measured before and after by "
    "q-system/.q-system/scripts/mcp-denylist-namespace-check.py. Apply with: "
    "bash q-system/.q-system/scripts/apply-claude-changes.sh "
    "q-system/.q-system/proposals/mcp-denylist-operation-split.json --root $HOME")


def build():
    return {
        "schema_version": 1,
        "slug": "mcp-denylist-operation-split",
        "reason": REASON,
        "edits": [
            {
                "file": ".claude/hooks/destructive-op-deny.sh",
                "op": "insert_before",
                "anchor": ANCHOR,
                "insert": INSERT,
                "reason": "ASK-1923: deny on the destructive OPERATION for every "
                          "MCP server, scope the approval token to the call, and "
                          "let read verbs through before the server-name "
                          "wildcards can refuse them",
            }
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the JSON on disk is not what this builds")
    args = parser.parse_args(argv)

    built = json.dumps(build(), indent=2) + "\n"
    if args.check:
        on_disk = PROPOSAL.read_text(encoding="utf-8")
        if on_disk != built:
            print("%s is not what build-mcp-proposal.py builds; run it without "
                  "--check" % PROPOSAL, file=sys.stderr)
            return 1
        print("proposal matches its generator")
        return 0
    PROPOSAL.write_text(built, encoding="utf-8")
    print("wrote %s" % PROPOSAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
