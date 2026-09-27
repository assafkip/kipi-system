"""Only text the FOUNDER typed is his request, and a route lane is enforced only
where one is installed.

Ported 2026-09-06 from the one instance that ran these live
(automation/test_harness_injection_is_not_the_founder.py and
test_founder_typed_text_rejects_peer_messages.py there), because every fleet
sync replaced that instance's gate with a skeleton copy that had none of this
and its pre-commit went red until the next restore (sp-745f5962). The record
shapes are the ones the harness actually writes: flags TOP-LEVEL on the record,
content as a list of text blocks.

The lane tests build a fake `q-consult/pipeline` package in a temp root and
point the gate's INSTANCE_ROOT at it, so the three outcomes of `_route_context`
(absent, broken, present) are each exercised without the real lane.

Round 2 (PR #313 review): the slash-command and hook-opener cases use record
text lifted verbatim from this fleet's own session logs (a `/goal` turn with his
words in `<command-args>`, a plugin command with `<command-message>` first), and
the receipt cases run against a fake `route_contract` that hashes with the
producer's exact envelope.

Round 3: a lane that RAISES (not ImportError) holds the turn instead of exiting
the hook with 1, the audit-only refusal is reached through a fake route that
matches, and `main()` itself is driven on both paths (short draft, linted
draft) so deleting either `enforce_route_receipt` call site goes red. The
mutation harness beside this file (scratchpad, not shipped) replaces each of
the five receipt checks, the two audit-only branches, the exception guard and
each call site with a no-op; every mutant fails at least one case here.
"""
import importlib.util
import io
import json
import pathlib
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
GATE = REPO / "q-system" / ".q-system" / "scripts" / "voice-stop-gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("voice_stop_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vsg = _load()

FOUNDER_MESSAGE = "Explain simply no tables."
SKILL_BODY = (
    "# Workflow authoring reference\n\n"
    "A workflow structures work across many agents.\n\n"
    "compose novel harnesses when the task calls for it\n\n"
    "To iterate on a workflow, edit that file with Write/Edit and re-invoke "
    "Workflow with scriptPath instead of resending the full script.\n"
)
PEER = (
    '<cross-session-message from="uds:/tmp/cc-socks/41361.sock" '
    'from-name="voice loop" from-mode="bypass">\n'
    'If you add a `social-comment` surface, its pointers are now verified.\n'
    '</cross-session-message>'
)
# Verbatim from a 2026-09-06 session log: the harness's own shape for a slash
# command, indentation included, and not flagged isMeta.
GOAL_TURN = (
    "<command-name>/goal</command-name>\n"
    "            <command-message>goal</command-message>\n"
    "            <command-args>ensure you know from the other projects tht you "
    "know when you can go and then go</command-args>"
)
GOAL_ARGS = "ensure you know from the other projects tht you know when you can go and then go"
# A plugin command: `<command-message>` comes FIRST, and there are no args.
PLUGIN_COMMAND_TURN = (
    "<command-message>kipi-core:wiring-check</command-message>\n"
    "<command-name>/kipi-core:wiring-check</command-name>"
)
REQUEST = "write me a linkedin post about the audit"
DRAFT = "The audit found the gate green and the test never ran."


def _record(text, role="user", **flags):
    record = {
        "type": "user",
        "isSidechain": False,
        "userType": "external",
        "message": {"role": role, "content": [{"type": "text", "text": text}]},
    }
    record.update(flags)
    return record


@pytest.fixture
def transcript(tmp_path):
    def build(records):
        path = tmp_path / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return str(path)
    return build


# --- the founder's words vs the harness's ---------------------------------

def test_a_skill_body_is_not_the_founders_request(transcript):
    path = transcript([
        _record(FOUNDER_MESSAGE),
        _record(SKILL_BODY, isMeta=True, turnCompanion=True),
    ])
    assert vsg.find_final_user_text(path) == FOUNDER_MESSAGE


@pytest.mark.parametrize("flags", [
    {"isMeta": True},
    {"turnCompanion": True},
    {"isMeta": True, "turnCompanion": True},
])
def test_either_flag_alone_is_enough(transcript, flags):
    path = transcript([_record(FOUNDER_MESSAGE), _record(SKILL_BODY, **flags)])
    assert vsg.find_final_user_text(path) == FOUNDER_MESSAGE


def test_stop_hook_feedback_is_not_his_words_either(transcript):
    path = transcript([
        _record(FOUNDER_MESSAGE),
        _record("Stop hook feedback:\nvoice-stop-gate: route request is unsupported",
                isMeta=True),
    ])
    assert vsg.find_final_user_text(path) == FOUNDER_MESSAGE


def test_an_unflagged_user_turn_is_still_read(transcript):
    """The negative control: a filter that swallows his real messages is worse
    than the bug, the gate would look green while measuring nothing."""
    path = transcript([
        _record("first message"),
        _record(SKILL_BODY, isMeta=True, turnCompanion=True),
        _record("write me a linkedin post about the audit"),
    ])
    assert vsg.find_final_user_text(path) == "write me a linkedin post about the audit"


def test_flags_are_read_from_the_record_not_the_message(transcript):
    """A flag INSIDE `message` must not count: that is not where the harness puts
    it, and honouring it there lets a crafted message hide from the gate."""
    record = _record(SKILL_BODY)
    record["message"]["isMeta"] = True
    path = transcript([_record(FOUNDER_MESSAGE), record])
    assert vsg.find_final_user_text(path) == SKILL_BODY.strip()


def test_a_cross_session_message_is_rejected_whole():
    assert vsg.founder_typed_text(PEER) == ""


def test_the_founders_own_words_still_survive():
    typed = "write this as a linkedin comment with voice loop"
    assert vsg.founder_typed_text(typed) == typed


def test_a_peer_block_inside_a_turn_is_stripped_not_kept():
    assert "social-comment" not in vsg.founder_typed_text("ok\n\n" + PEER)


def test_a_command_invocation_is_truncated_at_the_marker():
    typed = "make it shorter <command-name>/foo</command-name>\n# Foo\n\nlong skill body"
    assert vsg.founder_typed_text(typed) == "make it shorter"


def test_assistant_text_is_unaffected(transcript):
    """`_walk_transcript` grew a parameter; its other caller must not change."""
    path = transcript([
        _record(FOUNDER_MESSAGE),
        _record("here is the draft", role="assistant"),
    ])
    assert "here is the draft" in vsg.find_final_assistant_text(path)


# --- a slash command is HIS turn ------------------------------------------

def test_a_slash_command_turn_is_his_arguments():
    assert vsg.founder_typed_text(GOAL_TURN) == GOAL_ARGS


def test_a_slash_command_turn_is_not_an_older_request(transcript):
    """The PR #313 reproducer: truncating at the first tag returned "" and the
    gate answered with the PREVIOUS turn, so the scorer and the route hasher
    were handed words he did not type this turn."""
    path = transcript([
        _record("write me a linkedin post about the audit"),
        _record(GOAL_TURN),
    ])
    assert vsg.find_final_user_text(path) == GOAL_ARGS


def test_a_bare_command_is_still_his_turn(transcript):
    assert vsg.founder_typed_text(PLUGIN_COMMAND_TURN) == "/kipi-core:wiring-check"
    path = transcript([
        _record("write me a linkedin post about the audit"),
        _record(PLUGIN_COMMAND_TURN),
    ])
    assert vsg.find_final_user_text(path) == "/kipi-core:wiring-check"


@pytest.mark.parametrize("typed", [
    "PostToolUse hook is refusing my edit again, why?",
    "Stop hook feedback is firing on every turn, fix it",
    "SessionStart hook output looks wrong",
])
def test_his_message_about_a_hook_is_his_message(typed):
    """He pastes hook errors as a workflow. The harness flags its OWN hook
    feedback isMeta (251 of 251 records over 30 session logs), so prose that
    opens with an event name is his, not the machine's."""
    assert vsg.founder_typed_text(typed) == typed


# --- the route lane: absent, broken, present ------------------------------

# The contract half of the fake lane hashes with the PRODUCER's exact envelope
# (route_contract._hash: NFC-normalised text, sorted compact JSON, sha256) and
# matches on its MATCH_FIELDS, so a receipt minted here is refused or consumed
# for the same reasons a real one is. An empty module here was PR #313's
# finding 3: every verification branch survived deletion with the suite green.
FAKE_CONTRACT = '''
import hashlib, json, pathlib, unicodedata

class route_receipts:
    MATCH_FIELDS = {"attempt_id", "session_id", "origin_message_id",
                    "completion_message_id", "request_hash", "surface",
                    "channel", "output_hash", "loop_sha"}

STORE = pathlib.Path(__file__).with_name("receipts.json")

def normalize_text(text):
    return unicodedata.normalize("NFC", str(text)).replace("\\r\\n", "\\n").replace("\\r", "\\n")

def _hash(kind, text, surface, channel):
    envelope = {"channel": channel, "kind": kind, "surface": surface, "text": normalize_text(text)}
    encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def request_hash(request, surface, channel):
    return _hash("request", request, surface, channel)

def output_hash(output, surface, channel):
    return _hash("output", output, surface, channel)

def create_receipt(request, output, *, surface, channel, **overrides):
    row = {"attempt_id": "attempt-1", "session_id": "session-1",
           "origin_message_id": "origin-1", "completion_message_id": "completion-1",
           "request_hash": request_hash(request, surface, channel),
           "surface": surface, "channel": channel,
           "output_hash": output_hash(output, surface, channel),
           "loop_sha": "loop-1", "status": "pending"}
    row.update(overrides)
    STORE.write_text(json.dumps(row))
    return row

def verify_and_consume(identity, *, draft=None, **_):
    row = json.loads(STORE.read_text()) if STORE.exists() else None
    if row is None or row["status"] != "pending" or any(row.get(k) != v for k, v in identity.items()):
        raise LookupError("no current receipt matches the identity")
    row["status"] = "consumed"
    row["draft"] = draft
    STORE.write_text(json.dumps(row))
    return row
'''


def _fake_lane(root, broken=False, status="NOT_ROUTED", owner=False,
               raises=False, audit_surface=None, route_on=None):
    """A q-consult/pipeline package with the four modules the gate imports.

    `raises`: classify() raises RuntimeError, the shape of a lane whose store
    or classifier is broken at call time rather than at import time.
    `audit_surface`: audit_only_routes.routes() lists one audit-only route on
    that surface (channel "linkedin"), and deny() refuses it by name.
    `route_on`: classify() routes only when this phrase is in the request, the
    way the reviewer's reproducer classified on the words of the request.
    """
    pkg = root / "q-consult" / "pipeline"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    if broken:
        (pkg / "route_classifier.py").write_text("raise ImportError('half-installed lane')\n")
        for name in ("route_contract", "audit_only_routes", "route_registry"):
            (pkg / f"{name}.py").write_text("")
        return pkg
    (pkg / "route_classifier.py").write_text(textwrap.dedent(f"""
        import collections
        NOT_ROUTED = "NOT_ROUTED"
        ROUTE = "ROUTE"
        Result = collections.namedtuple("Result", "status surface channel reason")
        def classify(request):
            if {raises!r}:
                raise RuntimeError("classifier store is unreadable")
            status = {status!r}
            route_on = {route_on!r}
            if route_on is not None:
                status = ROUTE if route_on in request.lower() else NOT_ROUTED
            return Result(status, "linkedin_post", "linkedin", "fixture")
    """))
    (pkg / "route_contract.py").write_text(FAKE_CONTRACT)
    (pkg / "audit_only_routes.py").write_text(textwrap.dedent(f"""
        import collections
        Route = collections.namedtuple("Route", "surface channel route_id")
        class AuditOnlyRouteError(Exception):
            pass
        def routes():
            surface = {audit_surface!r}
            return [Route(surface, "linkedin", "audit-1")] if surface else []
        def deny(route):
            raise AuditOnlyRouteError(
                f"{{route.surface}} is audit-only; file the follow-up issue instead")
    """))
    (pkg / "route_registry.py").write_text(textwrap.dedent(f"""
        class RouteRegistryError(Exception):
            pass
        def resolve(surface, channel):
            if not {owner!r}:
                raise RouteRegistryError("no owner in the fixture")
            return {{"surface": surface, "channel": channel, "owner": "fixture"}}
    """))
    return pkg


@pytest.fixture
def lane_root(tmp_path, monkeypatch):
    """A temp instance root the gate treats as its own, with `pipeline` evicted
    from sys.modules so each test imports the package it built."""
    import sys
    for name in list(sys.modules):
        if name == "pipeline" or name.startswith("pipeline."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(vsg, "INSTANCE_ROOT", tmp_path)
    return tmp_path


def test_no_lane_means_no_enforcement(lane_root):
    """The 24-instance case: nothing under q-consult/pipeline, nothing to verify,
    and no exception either (an uncaught ImportError in a Stop hook fails OPEN)."""
    assert vsg._route_context() is None
    assert vsg.enforce_route_receipt("write me a linkedin post", "a draft") is None


def test_a_lane_that_does_not_import_holds_the_turn(lane_root):
    """Present-but-broken is a broken verifier, not an absent one."""
    _fake_lane(lane_root, broken=True)
    with pytest.raises(vsg.RouteBoundaryError, match="did not import"):
        vsg.enforce_route_receipt("write me a linkedin post", "a draft")


def test_a_not_routed_request_passes_a_present_lane(lane_root):
    _fake_lane(lane_root, status="NOT_ROUTED")
    assert vsg.enforce_route_receipt("explain simply", "a reply") is None


def test_a_routed_request_with_no_owner_is_refused(lane_root):
    """Same words as the live gate: the route family is verbatim from the
    instance, so its refusals read the same on every instance that grows a lane."""
    _fake_lane(lane_root, status="ROUTE")
    with pytest.raises(vsg.RouteBoundaryError, match="no single registered active owner"):
        vsg.enforce_route_receipt("write me a linkedin post", "a draft")


def test_a_lane_that_raises_at_call_time_holds_the_turn(lane_root):
    """Not an ImportError: the lane imports and then its classifier raises. An
    uncaught exception exits the Stop hook with 1, which does not block, so the
    routed turn would complete with no receipt consumed."""
    _fake_lane(lane_root, status="ROUTE", raises=True)
    with pytest.raises(vsg.RouteBoundaryError, match="raised RuntimeError"):
        vsg.enforce_route_receipt("write me a linkedin post", "a draft")


def test_an_audit_only_surface_is_refused_by_name(lane_root):
    """No owner in the registry AND exactly one audit-only route on the
    requested surface: the refusal names the audit-only rule, not the owner."""
    _fake_lane(lane_root, status="ROUTE", audit_surface="linkedin_post")
    with pytest.raises(vsg.RouteBoundaryError, match="is audit-only"):
        vsg.enforce_route_receipt("write me a linkedin post", "a draft")


def test_an_audit_only_route_on_another_surface_does_not_apply(lane_root):
    _fake_lane(lane_root, status="ROUTE", audit_surface="reddit_post")
    with pytest.raises(vsg.RouteBoundaryError, match="no single registered active owner"):
        vsg.enforce_route_receipt("write me a linkedin post", "a draft")


# --- the wiring: main() reaches the receipt check on both of its paths -----

def _run_main(monkeypatch, transcript, assistant_text):
    monkeypatch.setattr("sys.argv", ["voice-stop-gate.py"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"transcript_path": transcript})))
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    with pytest.raises(SystemExit) as exit_info:
        vsg.main()
    return exit_info.value.code, err.getvalue()


def test_main_holds_a_short_routed_reply_with_no_receipt(lane_root, transcript, monkeypatch):
    """The first call site: the founder's most common turn shape is a post in a
    fence with no framing sentence, which the lint declines to grade and which
    used to return before any check. Deleting this call leaves every unit test
    above green; only driving main() sees it."""
    _fake_lane(lane_root, status="ROUTE", owner=True)
    path = transcript([_record(REQUEST), _record("short reply", role="assistant")])
    code, err = _run_main(monkeypatch, path, "short reply")
    assert code == 2
    assert "has no route receipt" in err


# --- whose turn is it: the request must belong to THIS turn ---------------

NOTIFICATION = "<task-notification>agent finished: 3 files</task-notification>"
TOOL_RESULT = {
    "type": "user", "isSidechain": False, "userType": "external",
    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
}


@pytest.mark.parametrize("records, expected", [
    ([_record(REQUEST)], True),
    ([_record(REQUEST), _record(SKILL_BODY, isMeta=True, turnCompanion=True)], True),
    ([_record(REQUEST), _record("a draft", role="assistant"), TOOL_RESULT,
      _record("done", role="assistant")], True),
    ([_record(REQUEST), _record("a draft", role="assistant"),
      _record("Stop hook feedback:\nvoice violations", isMeta=True)], False),
    ([_record(REQUEST), _record("a draft", role="assistant"), _record(PEER)], False),
    ([_record(REQUEST), _record("a draft", role="assistant"), _record(NOTIFICATION)], False),
    ([_record(REQUEST), _record("a draft", role="assistant"), _record(NOTIFICATION),
      _record("noted", role="assistant"), _record("thanks, park it")], True),
], ids=["his-turn", "skill-body-companion", "tool-result-mid-turn", "hook-feedback",
        "peer-message", "notification", "he-types-again"])
def test_request_is_current_reads_who_spoke_last(transcript, records, expected):
    assert vsg.request_is_current(transcript(records)) is expected


@pytest.mark.parametrize("text, expected", [
    ("Noted, three files landed.", False),
    ("```\n" + DRAFT + "\n```", True),
    ("> " + DRAFT, True),
    ("=== DRAFT ===\n" + DRAFT, True),
    ('=== ROUTE RECEIPT ===\n{"surface": "x"}\n=== DRAFT ===\n' + DRAFT, True),
], ids=["prose", "bare-fence", "blockquote", "draft-section", "receipt-block"])
def test_reply_carries_a_draft_reads_the_shape_not_the_trigger(text, expected):
    assert vsg.reply_carries_a_draft(text) is expected


def test_main_holds_a_bare_fenced_draft_after_the_gates_own_feedback(lane_root, transcript, monkeypatch):
    """Round 4's major: the gate refused a draft (exit 2, its feedback lands as
    an isMeta user record), the assistant answered that MACHINE record with the
    same routed draft in a bare fence and no framing, and a who-spoke-last rule
    alone let it complete with no receipt consumed."""
    _fake_lane(lane_root, owner=True, route_on="linkedin post")
    fenced = "```\n" + DRAFT + "\n```"
    records = [
        _record(REQUEST),
        _record(fenced, role="assistant"),
        _record("Stop hook feedback:\nvoice-stop-gate: routed completion has no route receipt",
                isMeta=True),
        _record(fenced, role="assistant"),
    ]
    code, err = _run_main(monkeypatch, transcript(records), fenced)
    assert code == 2 and "has no route receipt" in err


def test_main_does_not_rerun_his_old_request_on_a_machine_turn(lane_root, transcript, monkeypatch):
    """The reviewer's five-turn reproducer, driven through main() on one growing
    transcript with a lane that routes on the words of the request. Before the
    fix, turn 2 exited 2 ("has no route receipt") and so did every redraft after
    it, until he typed again."""
    _fake_lane(lane_root, owner=True, route_on="linkedin post")
    contract = vsg._route_context()[1]
    monkeypatch.setattr(vsg, "authorship_spool", lambda *args, **kwargs: None)
    monkeypatch.setattr(vsg, "finish_ok", lambda: (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setattr(vsg, "run_check", lambda *args, **kwargs: (0, ""))
    receipt = contract.create_receipt(REQUEST, DRAFT, surface="linkedin_post", channel="linkedin")
    records = [_record(REQUEST), _record(_assistant(receipt), role="assistant")]
    code, err = _run_main(monkeypatch, transcript(records), _assistant(receipt))
    assert code == 0, err                                     # turn 1: routed draft + receipt
    records += [_record(NOTIFICATION), _record("Noted, three files landed.", role="assistant")]
    code, err = _run_main(monkeypatch, transcript(records), "Noted, three files landed.")
    assert code == 0, err                                     # turn 2: prose reply to the machine
    records += [_record("thanks, park it"), _record("Parked.", role="assistant")]
    code, err = _run_main(monkeypatch, transcript(records), "Parked.")
    assert code == 0, err                                     # turn 3: he types, not routed
    records += [_record("write me a linkedin post about the audit, again"),
                _record("Here it is.", role="assistant")]
    code, err = _run_main(monkeypatch, transcript(records), "Here it is.")
    assert code == 2 and "has no route receipt" in err        # turn 4: he asks, no receipt


def test_main_holds_a_linted_routed_draft_with_no_receipt(lane_root, transcript, monkeypatch):
    """The second call site, after the voice lints. The lints are stubbed to
    pass (run_check returns 0) and the draft is long enough to be graded, so
    the only thing that can hold the turn is the receipt check."""
    _fake_lane(lane_root, status="ROUTE", owner=True)
    long_draft = "A graded draft. " * 12
    monkeypatch.setattr(vsg, "extract_publishable", lambda text: long_draft)
    monkeypatch.setattr(vsg, "run_check", lambda *args, **kwargs: (0, ""))
    path = transcript([_record(REQUEST), _record(long_draft, role="assistant")])
    code, err = _run_main(monkeypatch, path, long_draft)
    assert code == 2
    assert "has no route receipt" in err


def test_a_receipt_block_must_be_json():
    with pytest.raises(vsg.RouteBoundaryError, match="not valid JSON"):
        vsg._receipt_block("=== ROUTE RECEIPT ===\nnot json")
    assert vsg._receipt_block("no marker here") is None
    assert vsg._receipt_block('=== ROUTE RECEIPT ===\n{"surface": "x"}') == {"surface": "x"}


# --- the receipt: each verification branch refuses for its own reason ------

def _routed_lane(lane_root):
    """A present lane that ROUTES the request to an owner; returns its contract."""
    _fake_lane(lane_root, status="ROUTE", owner=True)
    return vsg._route_context()[1]


def _assistant(receipt, draft=DRAFT):
    return "=== ROUTE RECEIPT ===\n" + json.dumps(receipt) + "\n=== DRAFT ===\n" + draft


def test_a_matching_receipt_passes_and_is_consumed(lane_root):
    contract = _routed_lane(lane_root)
    receipt = contract.create_receipt(REQUEST, DRAFT, surface="linkedin_post", channel="linkedin")
    row = vsg.enforce_route_receipt(REQUEST, _assistant(receipt))
    assert row["status"] == "consumed"
    assert row["draft"] == DRAFT


def test_a_routed_completion_with_no_receipt_is_refused(lane_root):
    _routed_lane(lane_root)
    with pytest.raises(vsg.RouteBoundaryError, match="has no route receipt"):
        vsg.enforce_route_receipt(REQUEST, "=== DRAFT ===\n" + DRAFT)


def test_an_incomplete_identity_is_refused(lane_root):
    contract = _routed_lane(lane_root)
    receipt = contract.create_receipt(REQUEST, DRAFT, surface="linkedin_post", channel="linkedin")
    del receipt["loop_sha"]
    with pytest.raises(vsg.RouteBoundaryError, match="identity is incomplete"):
        vsg.enforce_route_receipt(REQUEST, _assistant(receipt))


def test_a_receipt_for_another_surface_is_refused(lane_root):
    contract = _routed_lane(lane_root)
    receipt = contract.create_receipt(REQUEST, DRAFT, surface="reddit_post", channel="reddit")
    with pytest.raises(vsg.RouteBoundaryError, match="requested surface"):
        vsg.enforce_route_receipt(REQUEST, _assistant(receipt))


def test_a_receipt_for_another_request_is_refused(lane_root):
    contract = _routed_lane(lane_root)
    receipt = contract.create_receipt("write me a linkedin post about another audit", DRAFT,
                                      surface="linkedin_post", channel="linkedin")
    with pytest.raises(vsg.RouteBoundaryError, match="does not match the user request"):
        vsg.enforce_route_receipt(REQUEST, _assistant(receipt))


def test_a_draft_edited_after_minting_is_refused(lane_root):
    contract = _routed_lane(lane_root)
    receipt = contract.create_receipt(REQUEST, DRAFT, surface="linkedin_post", channel="linkedin")
    with pytest.raises(vsg.RouteBoundaryError, match="does not match the assistant output"):
        vsg.enforce_route_receipt(REQUEST, _assistant(receipt, draft=DRAFT + " Edited."))


def test_a_receipt_the_store_does_not_hold_is_refused(lane_root):
    """A well-formed block whose row is gone (or already consumed) is not a
    proof; the store's refusal is surfaced, never swallowed."""
    contract = _routed_lane(lane_root)
    receipt = contract.create_receipt(REQUEST, DRAFT, surface="linkedin_post", channel="linkedin")
    contract.STORE.unlink()
    with pytest.raises(vsg.RouteBoundaryError, match="was not accepted"):
        vsg.enforce_route_receipt(REQUEST, _assistant(receipt))
