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
MCP_SQL_OP='(^|[_-])(execute[_-]?sql|apply[_-]?migration|run[_-]?sql|sql)([_-]|$)'
MCP_DESTRUCTIVE_SQL='(drop|truncate)([[:space:]]|\\n)+(table|database|schema|view|index|type|function|sequence|column|policy|role|extension|publication)|delete([[:space:]]|\\n)+from'
# Servers where EVERY non-read op is denied, not only a destructive verb
# (founder CLAUDE.md: "Vercel mutating ops"). Matched case-INSENSITIVELY against
# the server segment: the registered connector is mcp__claude_ai_Vercel__, with
# a capital V, and a case-sensitive match missed it -- the same server-name miss
# this whole insert exists to fix (PR #390 review).
MCP_MUTATION_SCOPED_SERVER='(^|_)vercel(_|$)'

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
    # Auth is how you EARN the connection, so it is never blocked. Kept from the
    # block below so a fix cannot quietly drop it.
    case "$TOOL_NAME" in
      *authenticate*|*complete_authentication*)
        log_decision "allow" "mcp auth operation"
        exit 0 ;;
    esac
    if echo "$_mcp_op" | grep -Eqi "$MCP_DESTRUCTIVE_OP"; then
      emit_deny "MCP operation '$_mcp_op' on server '$_mcp_server' matches a destructive-operation verb. This gate cannot see whether the state it removes is at the vendor or on this machine, so it refuses either way: the miss costs production data, the false positive costs one approval. Keyed on the operation, not the server name (ASK-1923)"
    fi
    if echo "$_mcp_op" | grep -Eqi "$MCP_SQL_OP" \
       && echo "${TOOL_INPUT:-}" | grep -Eqi "$MCP_DESTRUCTIVE_SQL"; then
      emit_deny "MCP operation '$_mcp_op' on server '$_mcp_server' carries a destructive SQL statement in its payload (DROP / TRUNCATE / DELETE FROM). Keyed on the statement, so a SELECT and an additive migration still run (ASK-1923)"
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
