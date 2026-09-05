"""Route-receipt enforcement, and what it must do on an instance that has no route lane.

WHY THIS IS IN THE SKELETON (ASK-1197). `q-system/` is an rsync --delete fanout
target, so this file has one home per instance and the skeleton copy is the one
that survives. Measured 2026-09-02 across the 25 registered instances:
`enforce_route_receipt` and its four helpers existed in exactly ONE instance
(ASK_AI_consultant) and in no skeleton, so the next `kipi update` would have
deleted a shipped gate. Porting it upstream is what makes the fanout safe; this
file is what makes the port provable.

THE HARD CONSTRAINT, and it outranks the feature. 24 of the 24 instances that
carry this file have no `q-consult/pipeline`. They must behave EXACTLY as they
did before the port: no import error, no traceback, no per-turn noise. That is
the same constraint `resolve_channel_registry` was written under and for the same
reason -- a gate that prints on every turn of 24 instances gets switched off, and
a gate that is off protects nothing.

AND THE OTHER HALF, which is where a naive "just guard the import" goes wrong. A
turn that carries a `=== ROUTE RECEIPT ===` block is a turn whose producer
believes a receipt is being verified. Passing that silently because the verifier
is not installed is the `run_check` scar exactly (PR #290): the value a missing
check returns must not be the value a clean check returns. So an uninstalled lane
is silent on an ordinary turn and says NOT CHECKED on a turn that claims a
receipt.

WHAT THIS DOES NOT PROVE. The stub pipeline below is a stand-in for the
consulting `q-consult/pipeline` modules, so a green here does not prove the real
classifier or the real store agree with it. It proves the CONSUMER contract: that
the gate reads the required identity fields out of `route_receipts.MATCH_FIELDS`
rather than a list of its own, and that it hands the extracted draft to
`verify_and_consume(..., draft=)`. The stub deliberately declares a MATCH_FIELDS
containing a name this gate's source never mentions (`loop_sha`), so a gate that
went back to a hand-kept list fails here instead of passing.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unicodedata

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPTS = os.path.join(REPO, "q-system", ".q-system", "scripts")
GATE = os.path.join(SCRIPTS, "voice-stop-gate.py")

# Deliberately NOT the real consulting set, and deliberately not a subset of it
# either. `loop_sha` is here because the real store added it in R9 and the gate
# must have picked it up without an edit; `nonce_the_gate_never_names` is here
# because that is the property under test -- the gate demands whatever the store
# says, including a field no reader of voice-stop-gate.py would guess.
STUB_MATCH_FIELDS = {
    "attempt_id",
    "request_hash",
    "surface",
    "channel",
    "output_hash",
    "loop_sha",
    "nonce_the_gate_never_names",
}

DRAFT_MARKER = "=== DRAFT ==="
RECEIPT_MARKER = "=== ROUTE RECEIPT ==="

# A stub `q-consult/pipeline`. It records what the gate asked it for into a JSON
# file so the assertions read the gate's actual calls rather than its exit code.
_STUB_PIPELINE = '''
import json, os

_LOG = os.environ["ROUTE_STUB_LOG"]


def _record(event, **fields):
    rows = []
    if os.path.exists(_LOG):
        with open(_LOG) as fh:
            rows = json.load(fh)
    rows.append(dict(event=event, **fields))
    with open(_LOG, "w") as fh:
        json.dump(rows, fh)
'''

_STUB_CLASSIFIER = '''
import json, os
NOT_ROUTED = "not_routed"
ROUTE = "route"


class _Result:
    def __init__(self, status, surface, channel, reason=""):
        self.status, self.surface, self.channel, self.reason = status, surface, channel, reason


def classify(request):
    if os.environ.get("ROUTE_STUB_CLASSIFY") == "route":
        return _Result(ROUTE, "linkedin", "assaf")
    return _Result(NOT_ROUTED, "", "")
'''

_STUB_RECEIPTS = '''
MATCH_FIELDS = %r
''' % (STUB_MATCH_FIELDS,)

_STUB_CONTRACT = '''
import json, os
from pipeline import route_receipts


import hashlib


def _h(prefix, value, surface, channel):
    return prefix + hashlib.sha256(
        ("%s|%s|%s" % (value, surface, channel)).encode("utf-8")).hexdigest()[:16]


def request_hash(request, surface, channel):
    return _h("rh:", request, surface, channel)


def output_hash(output, surface, channel):
    return _h("oh:", output, surface, channel)


def verify_and_consume(identity, *, draft=None):
    log = os.environ["ROUTE_STUB_LOG"]
    rows = []
    if os.path.exists(log):
        with open(log) as fh:
            rows = json.load(fh)
    rows.append({"event": "verify_and_consume",
                 "identity_keys": sorted(identity),
                 "draft": draft})
    with open(log, "w") as fh:
        json.dump(rows, fh)
    return {"consumed": True}
'''

_STUB_REGISTRY = '''
class RouteRegistryError(Exception):
    pass


def resolve(surface, channel):
    return {"surface": surface, "channel": channel}
'''

_STUB_AUDIT = '''
class AuditOnlyRouteError(Exception):
    pass


def routes():
    return []


def deny(route):
    raise AuditOnlyRouteError("audit-only")
'''


def _system_message(proc):
    """The text a real Stop-hook consumer sees, or a failure saying why not.

    THE CHANNEL IS THE ASSERTION (Codex major, ASK-1197 round 4). A Stop hook's
    plain stdout at exit 0 is dropped by the client; the one field that reaches the
    USER is a `systemMessage` key in a JSON document on stdout, which is what
    `finish_ok` has always emitted for the authorship score and what
    `test_voice_stop_gate_drain_only.py` asserts against a real run. Asserting the
    substring "NOT CHECKED" in raw stdout passes on bare text nobody is shown,
    which is how an unchecked receipt read as a verified one.
    """
    raw = proc.stdout.strip()
    assert raw, ("nothing on stdout, so nothing reached the user.\n"
                 f"stderr={proc.stderr!r}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "stdout is not one JSON document, so a consumer that parses it sees "
            f"nothing or breaks: {exc}\nstdout={proc.stdout!r}")
    assert isinstance(payload, dict) and "systemMessage" in payload, (
        "exit-0 output carries no `systemMessage`, the only hook field that puts "
        f"text in front of the user. {payload!r}")
    return payload["systemMessage"]


def _producer_message(receipt, draft):
    """The wire format the REAL producer emits, not one invented here.

    Copied from the producer-side proof at
    `consulting/q-consult/pipeline/tests/test_route_boundary.py:54`:
    RECEIPT first, DRAFT last. The order is load-bearing, because `_route_draft`
    returns everything after the draft marker -- so with the two blocks swapped the
    hashed draft carries the receipt JSON and can never match a producer hash.
    """
    return ("Here's the post for LinkedIn.\n\n"
            + RECEIPT_MARKER + "\n" + json.dumps(receipt) + "\n"
            + DRAFT_MARKER + "\n" + draft + "\n")


def _stub_hash(prefix, value, surface="linkedin", channel="assaf"):
    """The stub's hash, recomputed here so the test states the expected value
    instead of accepting whatever the stub produced."""
    import hashlib
    return prefix + hashlib.sha256(
        ("%s|%s|%s" % (value, surface, channel)).encode("utf-8")).hexdigest()[:16]


def _instance(tmp_path, *, with_route_lane, broken_lane=False):
    """A minimal instance tree: the gate, the two lints it shells, and optionally
    a `q-consult/pipeline`. Built as a COPY so no test can reach the live scripts."""
    root = tmp_path / ("instance" if with_route_lane else "bare")
    scripts = root / "q-system" / ".q-system" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("voice-stop-gate.py", "voice-lint.py", "voice-substance-lint.py"):
        src = os.path.join(SCRIPTS, name)
        if os.path.exists(src):
            shutil.copy2(src, scripts / name)
    if with_route_lane:
        pipeline = root / "q-consult" / "pipeline"
        pipeline.mkdir(parents=True)
        (pipeline / "__init__.py").write_text(_STUB_PIPELINE, encoding="utf-8")
        if broken_lane:
            # Present and unimportable. NOT a missing lane: the difference is the
            # whole point, because "installed and broken" must hold the turn.
            (pipeline / "route_classifier.py").write_text(
                "raise RuntimeError('the route lane is broken')\n", encoding="utf-8")
        else:
            (pipeline / "route_classifier.py").write_text(_STUB_CLASSIFIER, encoding="utf-8")
        (pipeline / "route_receipts.py").write_text(_STUB_RECEIPTS, encoding="utf-8")
        (pipeline / "route_contract.py").write_text(_STUB_CONTRACT, encoding="utf-8")
        (pipeline / "route_registry.py").write_text(_STUB_REGISTRY, encoding="utf-8")
        (pipeline / "audit_only_routes.py").write_text(_STUB_AUDIT, encoding="utf-8")
    return root


def _transcript(tmp_path, user_text, assistant_text, name="t.jsonl"):
    path = tmp_path / name
    lines = [
        json.dumps({"message": {"role": "user",
                                "content": [{"type": "text", "text": user_text}]}}),
        json.dumps({"message": {"role": "assistant",
                                "content": [{"type": "text", "text": assistant_text}]}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _run(root, transcript, log_path, *, classify=None, env_extra=None):
    env = dict(os.environ)
    env["ROUTE_STUB_LOG"] = str(log_path)
    if env_extra:
        env.update(env_extra)
    if classify:
        env["ROUTE_STUB_CLASSIFY"] = classify
    else:
        env.pop("ROUTE_STUB_CLASSIFY", None)
    gate = root / "q-system" / ".q-system" / "scripts" / "voice-stop-gate.py"
    return subprocess.run(
        [sys.executable, str(gate)],
        input=json.dumps({"transcript_path": transcript}),
        capture_output=True, text=True, timeout=60, env=env, cwd=str(root),
    )


def _calls(log_path):
    if not os.path.exists(log_path):
        return []
    with open(log_path) as fh:
        return json.load(fh)


class TestTheLaneIsInstalled:

    def test_a_routed_turn_with_a_good_receipt_consumes_it_with_the_draft(self, tmp_path):
        """The contract: identity from MATCH_FIELDS, and the DRAFT reaches the store.

        `draft=` is asserted on because R9 recomputes the receipt's loop evidence
        against it. A port that dropped the keyword would still exit 0 here, so
        exit code alone is not the assertion.
        """
        root = _instance(tmp_path, with_route_lane=True)
        log = tmp_path / "calls.json"
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        receipt.update({"surface": "linkedin", "channel": "assaf",
                        "request_hash": _stub_hash("rh:", "write it"),
                        "output_hash": _stub_hash("oh:", "The body of the draft")})
        assistant = _producer_message(receipt, "The body of the draft")
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log,
                    classify="route")
        calls = [c for c in _calls(log) if c["event"] == "verify_and_consume"]
        assert calls, (
            "the gate never reached verify_and_consume.\n"
            f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        assert sorted(STUB_MATCH_FIELDS) == calls[0]["identity_keys"], (
            "the identity handed to the store is not the store's own MATCH_FIELDS. "
            "A hand-kept list in the gate is the defect this asserts against.")
        assert calls[0]["draft"] is not None, (
            "verify_and_consume was called without draft=, so R9 loop evidence "
            "is recomputed against nothing.")
        assert calls[0]["draft"] == "The body of the draft", (
            f"the draft passed to the store was {calls[0]['draft']!r}. It must be "
            f"EXACTLY the text after {DRAFT_MARKER}. `in` is not enough here: a "
            f"draft that also carried the receipt JSON or the framing sentence "
            f"contains the body too, and that is the leak this asserts against.")
        assert RECEIPT_MARKER not in calls[0]["draft"], calls[0]["draft"]
        assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"

    def test_a_routed_turn_with_no_receipt_is_refused(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=True)
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log,
                    classify="route")
        assert proc.returncode == 2, (
            f"a routed completion with no receipt must HOLD the turn. "
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "route receipt" in proc.stderr.lower(), proc.stderr

    def test_a_classifier_that_raises_at_runtime_holds_the_turn(self, tmp_path):
        """Codex major, round 1. The lane IMPORTS fine and then throws while being
        used. `_enforce_route_or_exit` caught only RouteBoundaryError, so the
        RuntimeError escaped, Python exited 1, and a Stop hook exiting 1 does NOT
        hold the turn -- the routed draft completed with nothing verified."""
        root = _instance(tmp_path, with_route_lane=True)
        classifier = root / "q-consult" / "pipeline" / "route_classifier.py"
        classifier.write_text(
            "NOT_ROUTED = 'not_routed'\nROUTE = 'route'\n"
            "def classify(request):\n"
            "    raise RuntimeError('the classifier blew up mid-turn')\n",
            encoding="utf-8")
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log)
        assert proc.returncode == 2, (
            "a verifier that crashed has not cleared this draft, so the turn must "
            f"be held. rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "RuntimeError" in proc.stderr, (
            "the turn was held but the reason was swallowed; a fail-closed with no "
            "diagnosis is unfixable.\n" + proc.stderr)

    def test_a_pipeline_package_from_elsewhere_is_refused(self, tmp_path):
        """Codex minor, round 1. `sys.path.insert` loses to `sys.modules`: a
        package named `pipeline` already imported in the process is handed back
        regardless of the path we prepend. An impostor supplying the verifier would
        consume receipts against the wrong store and report success."""
        root = _instance(tmp_path, with_route_lane=True)
        impostor = tmp_path / "impostor"
        (impostor / "pipeline").mkdir(parents=True)
        for mod in ("__init__", "route_classifier", "route_contract",
                    "route_registry", "audit_only_routes"):
            (impostor / "pipeline" / (mod + ".py")).write_text(
                "NOT_ROUTED = 'not_routed'\nROUTE = 'route'\n", encoding="utf-8")
        # PYTHONPATH ALONE DOES NOT REPRODUCE THIS, and the first version of this
        # test proved it by passing against unfixed code: `sys.path.insert(0, ...)`
        # puts the instance FIRST, so the real lane still wins a fresh import. The
        # hazard needs `pipeline` to be in `sys.modules` BEFORE the gate imports it,
        # which is what a sitecustomize does. Getting the precondition wrong is how
        # a security test becomes decoration.
        (impostor / "sitecustomize.py").write_text("import pipeline\n", encoding="utf-8")
        env_extra = {"PYTHONPATH": str(impostor)}
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log,
                    env_extra=env_extra)
        assert proc.returncode == 2, (
            "a `pipeline` package resolved outside this instance must be refused, "
            f"not trusted. rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "not under" in proc.stderr or "which is not" in proc.stderr, (
            "the turn was held, but not for the reason under test. A refusal that "
            "happens to be right is not this assertion.\n" + proc.stderr)

        # THE CONTROL. Same tree, same PYTHONPATH, no pre-import: the real lane must
        # still win and the turn must complete. Without this, a bug that refused
        # EVERY installed lane would pass the assertion above.
        (impostor / "sitecustomize.py").unlink()
        ok = _run(root, _transcript(tmp_path, "hey", assistant), tmp_path / "c.json",
                  env_extra=env_extra)
        assert ok.returncode == 0, (
            "the control failed: the gate refused a lane that resolves correctly, so "
            f"the case above proves nothing. rc={ok.returncode} stderr={ok.stderr}")

    def test_a_lane_that_is_installed_and_broken_holds_the_turn(self, tmp_path):
        """Exit 2, not exit 1. A Stop hook exiting 1 does NOT hold the turn, so an
        uncaught ImportError from a half-installed lane fails OPEN -- the same
        shape Codex found in `channel_surface_lint` (AttributeError escaping)."""
        root = _instance(tmp_path, with_route_lane=True, broken_lane=True)
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log)
        assert proc.returncode == 2, (
            f"an installed-but-unimportable route lane must hold the turn, not "
            f"crash past it. rc={proc.returncode} stderr={proc.stderr}")
        assert "Traceback" not in proc.stderr, (
            "the lane failure escaped as a traceback; Python then exits 1 and the "
            "turn completes ungated.\n" + proc.stderr)


class TestTheLaneIsNotInstalled:
    """24 of 24 registered instances. These are the regression tests for them."""

    def test_an_ordinary_turn_is_silent(self, tmp_path):
        """The hard constraint. No route lane means the gate behaves as it did
        before the port: exit 0, nothing about routes on either stream."""
        root = _instance(tmp_path, with_route_lane=False)
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\nFine ordinary prose.\n"
        proc = _run(root, _transcript(tmp_path, "hey", assistant), log)
        assert proc.returncode == 0, (
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        combined = (proc.stdout + proc.stderr).lower()
        assert "route" not in combined, (
            "an instance with no route lane must say nothing about routes. A line "
            "on every turn of 24 instances is how a gate gets switched off.\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}")
        assert "Traceback" not in proc.stderr, proc.stderr

    def test_a_turn_that_claims_a_receipt_reports_not_checked(self, tmp_path):
        """Fail OPEN, but never silently. The producer emitted a receipt block, so
        something believes a verifier ran. `run_check`'s scar (PR #290): the value
        a missing check returns must differ from the value a clean check returns."""
        root = _instance(tmp_path, with_route_lane=False)
        log = tmp_path / "calls.json"
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        assistant = _producer_message(receipt, "The body of the draft")
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log)
        assert proc.returncode == 0, (
            "an instance with no route lane must not block on a receipt it cannot "
            f"verify. rc={proc.returncode} stderr={proc.stderr}")
        assert "NOT CHECKED" in _system_message(proc), (
            "a turn carrying a route receipt on an instance with no verifier "
            "passed with no NOT CHECKED line reaching the user. That is "
            "indistinguishable from a verified receipt, which is the whole "
            f"defect.\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}")


class TestTheseAssertionsCanFail:
    """Negative self-tests. Each proves the check above distinguishes the two cases.

    Without these the suite is decoration: a `_run` that always returned rc 0 with
    empty output would pass `test_an_ordinary_turn_is_silent` forever.
    """

    def test_the_harness_actually_runs_the_gate(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=False)
        gate = root / "q-system" / ".q-system" / "scripts" / "voice-stop-gate.py"
        gate.write_text("import sys\nsys.stderr.write('CANARY\\n')\nsys.exit(2)\n",
                        encoding="utf-8")
        proc = _run(root, _transcript(tmp_path, "hey", "hello"), tmp_path / "l.json")
        assert proc.returncode == 2 and "CANARY" in proc.stderr, (
            "the harness did not execute the copied gate, so every assertion in "
            f"this file is measuring nothing. rc={proc.returncode} {proc.stderr!r}")

    def test_the_stub_log_records_nothing_when_nothing_calls_it(self, tmp_path):
        assert _calls(tmp_path / "never-written.json") == []


def _load_gate():
    spec = importlib.util.spec_from_file_location("voice_stop_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


class TestFounderTypedText:
    """Named by the scar comment on `_COMMAND_INJECTION_MARK`.

    That comment records three rounds of the same deadlock: machine-injected prose
    read as the founder's request, classified UNSUPPORTED or AMBIGUOUS, and every
    completion in the session refused -- including the turn reporting the block.
    The comment is a paragraph; these are the executable half, which is what the
    prompt-only-enforcement guard demands and what a fourth round would need.
    """

    def test_a_skill_body_is_truncated_not_tag_stripped(self):
        """The 2026-09-01 round. His words come first, the injected body follows
        UNWRAPPED, so removing the little tags leaves the documentation standing."""
        text = ("Explain this simply no tables\n"
                "<command-name>/workflow-authoring</command-name>\n"
                "compose novel harnesses when the task calls for it")
        assert gate.founder_typed_text(text) == "Explain this simply no tables"

    def test_a_wholly_injected_turn_is_rejected_not_trimmed(self):
        """A notification whose text sits OUTSIDE any tag would still read as his
        words, so a turn that OPENS as an injection is dropped whole."""
        assert gate.founder_typed_text(
            "<system-reminder>do the thing</system-reminder>") == ""
        assert gate.founder_typed_text(
            "[SYSTEM NOTIFICATION] a subagent finished the reply-lane work") == ""

    def test_his_own_words_survive_untouched(self):
        """The direction that matters more. A filter that ate his real request
        would make the gate measure nothing, and every assertion above would still
        pass -- which is why this one is here."""
        assert gate.founder_typed_text("write me a linkedin post about the gate") == (
            "write me a linkedin post about the gate")

    def test_a_meta_flagged_skill_body_is_skipped_not_read_and_not_an_ending(self, tmp_path):
        """The label, not the prose. Enumerating carriers in a regex is the shape
        that failed twice; `isMeta` is what the harness already tells us.

        THIS ASSERTION HAS MOVED TWICE AND THIS IS WHY IT LANDED HERE. Round 6
        made it "" on the reasoning that a meta record ends his turn. That was a
        real bypass: a lessons-inject additionalContext or a system reminder
        landing between his routed request and the draft blanked the request and
        the draft shipped with no receipt check. Round 7 splits the two meanings
        an injected record can have -- this gate's OWN refusal fed back (ends the
        turn) versus every other injection (skipped) -- and a skill body is the
        second. So the earlier request stands, and the skill body is still not
        read as his words, which was this test's original point.
        """
        path = tmp_path / "t.jsonl"
        path.write_text("\n".join([
            json.dumps({"message": {"role": "user", "content": [
                {"type": "text", "text": "the real request"}]}}),
            json.dumps({"isMeta": True, "turnCompanion": True,
                        "message": {"role": "user", "content": [
                            {"type": "text", "text": "a skill body with no tags at all"}]}}),
        ]) + "\n", encoding="utf-8")
        assert gate.find_final_user_text(str(path)) == "the real request", (
            "a harness-flagged record must not BE the request (the "
            "third-occurrence deadlock) and must not END the turn either (the "
            "round 6 bypass). It is skipped.")


def _records_transcript(tmp_path, records, name="records.jsonl"):
    """A transcript written record-by-record, so a test can set the top-level
    harness flags and the content-block types `_transcript` hard-codes."""
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(path)


def _user(text, **top_level):
    return dict(top_level,
                message={"role": "user", "content": [{"type": "text", "text": text}]})


def _assistant(text):
    return {"message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]}}


class TestThisTurnsRequestOrNothing:
    """Finding 1, ASK-1197 round 2. `find_final_user_text` kept the last NON-EMPTY
    candidate, so a turn whose own final message is entirely machine prose -- a
    slash command, a hook body, a system-reminder -- silently reverted to an OLDER
    message and the route lane then verified this turn's draft against a request
    the founder made some turns ago. Dropping the injected prose was right; falling
    back to a different turn is a second defect wearing the first one's fix.

    The seam is TEXT vs NO TEXT, not empty vs non-empty. A `user` record carrying
    only a `tool_result` block is transport, not a turn, and must not erase the
    request; a `user` record that carries text which `founder_typed_text` empties
    IS this turn, and must yield nothing.
    """

    def test_a_wholly_injected_final_message_yields_nothing(self, tmp_path):
        path = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the gate"),
            _user("<system-reminder>a background task finished</system-reminder>"),
        ])
        assert gate.find_final_user_text(path) == "", (
            "the final message was entirely injected, so this turn has no founder "
            "text. Returning an earlier message verifies THIS draft against a "
            "request from a different turn.")

    def test_a_slash_command_final_message_yields_nothing(self, tmp_path):
        path = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the gate"),
            _user("<command-name>/q-wrap</command-name>\nrun the evening health check"),
        ])
        assert gate.find_final_user_text(path) == "", (
            "a slash-command turn carries no typed words before the marker, so it "
            "has no founder text. The older post request must not stand in for it.")

    def test_a_tool_result_record_does_not_erase_the_request(self, tmp_path):
        """The direction that matters more, and the one that makes the naive fix
        wrong. Every agentic turn ends user -> assistant(tool_use) -> user(
        tool_result) -> assistant(text): that trailing `user` record is role=user,
        carries NO text block and is NOT flagged isMeta. Assigning unconditionally
        would blank the founder's request on essentially every real turn."""
        path = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the gate"),
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        ])
        assert gate.find_final_user_text(path) == (
            "write me a linkedin post about the gate"), (
            "a tool_result record is transport, not a turn. Treating it as an empty "
            "founder message blanks the request on every tool-using turn.")

    def test_a_no_text_turn_is_not_a_route_request(self, tmp_path):
        """End to end, lane installed. With no founder text this turn there is
        nothing to classify, so the lane must not demand a receipt -- and above all
        must not build one against an earlier turn's words."""
        root = _instance(tmp_path, with_route_lane=True)
        log = tmp_path / "calls.json"
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        transcript = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the gate"),
            _user("<system-reminder>a background task finished</system-reminder>"),
            _assistant(assistant),
        ])
        proc = _run(root, transcript, log, classify="route")
        assert proc.returncode == 0, (
            "the gate refused a turn the founder did not ask for, by classifying an "
            f"older message as this turn's request. rc={proc.returncode} "
            f"stdout={proc.stdout} stderr={proc.stderr}")
        assert _calls(log) == [], (
            "the store was touched for a turn with no founder request: "
            f"{_calls(log)}")

    def test_the_route_lane_still_fires_when_he_did_type(self, tmp_path):
        """The control. Without it, a fix that returned "" for EVERY turn would
        pass the four assertions above and disable the gate outright."""
        root = _instance(tmp_path, with_route_lane=True)
        log = tmp_path / "calls.json"
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        transcript = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the gate"),
            _assistant(assistant),
        ])
        proc = _run(root, transcript, log, classify="route")
        assert proc.returncode == 2 and "receipt" in proc.stderr, (
            "a routed turn the founder DID type, with no receipt, must still be "
            f"refused. rc={proc.returncode} stderr={proc.stderr}")


def _symlinked_lane_instance(tmp_path, *, with_route_lane=True):
    """An instance whose `q-consult` is a SYMLINK to a lane living elsewhere.

    Not exotic: the consulting checkout is reached through a symlink on the
    founder's machine, and every module then resolves to the link TARGET.
    """
    root = _instance(tmp_path, with_route_lane=with_route_lane)
    if not with_route_lane:
        return root
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "q-consult").rename(elsewhere / "q-consult")
    (root / "q-consult").symlink_to(elsewhere / "q-consult", target_is_directory=True)
    return root


class TestTheLaneReachedThroughASymlink:
    """Finding 3, ASK-1197 round 2. The identity check compared an UNRESOLVED
    `pipeline_dir` against `Path(module.__file__).resolve().parents`, so a lane
    reached through a symlink never matched its own modules and the gate refused
    every turn -- a hard block, on the correct lane, for a path spelling."""

    def test_a_symlinked_lane_verifies_instead_of_hard_blocking(self, tmp_path):
        root = _symlinked_lane_instance(tmp_path)
        log = tmp_path / "calls.json"
        draft = "The body of the draft, long enough to be measured."
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        receipt.update(surface="linkedin", channel="assaf",
                       request_hash=_stub_hash("rh:", "write it"),
                       output_hash=_stub_hash("oh:", draft))
        proc = _run(root, _transcript(tmp_path, "write it",
                                      _producer_message(receipt, draft)),
                    log, classify="route")
        assert proc.returncode == 0, (
            "a lane reached through a symlink resolves to its target, so an "
            "unresolved comparison rejects the instance's own modules and blocks "
            f"every turn. rc={proc.returncode} stderr={proc.stderr}")

    def test_an_impostor_behind_a_symlink_is_still_refused_by_resolved_path(self, tmp_path):
        """The control for the fix above AND the message half of the finding: the
        refusal must name the path it actually compared, not the one it did not."""
        root = _symlinked_lane_instance(tmp_path)
        impostor = tmp_path / "impostor"
        (impostor / "pipeline").mkdir(parents=True)
        for mod in ("__init__", "route_classifier", "route_contract",
                    "route_registry", "audit_only_routes"):
            (impostor / "pipeline" / (mod + ".py")).write_text(
                "NOT_ROUTED = 'not_routed'\nROUTE = 'route'\n", encoding="utf-8")
        # See the sibling test: PYTHONPATH alone does not reproduce it, the
        # impostor has to be in `sys.modules` before the gate imports.
        (impostor / "sitecustomize.py").write_text("import pipeline\n", encoding="utf-8")
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant),
                    tmp_path / "c.json", env_extra={"PYTHONPATH": str(impostor)})
        assert proc.returncode == 2, (
            f"the impostor was trusted. rc={proc.returncode} stderr={proc.stderr}")
        resolved = str((tmp_path / "elsewhere" / "q-consult" / "pipeline").resolve())
        assert resolved in proc.stderr, (
            "the refusal printed a path it never compared against, so a reader "
            f"cannot act on it. wanted {resolved!r} in:\n{proc.stderr}")


class TestAClaimedReceiptIsStructural:
    """Finding 4, ASK-1197 round 2. The uninstalled-lane branch decided a receipt
    was claimed by substring, so an assistant that merely NAMES the marker in
    prose -- this file's own docstrings do it, and so does any turn explaining the
    gate -- printed NOT CHECKED on 24 instances that were never asked to check
    anything. A producer emits the marker on its own line; a sentence does not."""

    def test_a_prose_mention_of_the_marker_claims_nothing(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=False)
        assistant = ("Here's the post for LinkedIn.\n\n"
                     "The producer writes a `" + RECEIPT_MARKER + "` block ahead of "
                     "the draft, and the gate consumes it once.\n")
        proc = _run(root, _transcript(tmp_path, "explain the gate", assistant),
                    tmp_path / "c.json")
        assert proc.returncode == 0, (
            f"rc={proc.returncode} stderr={proc.stderr}")
        assert "NOT CHECKED" not in proc.stdout + proc.stderr, (
            "quoting the marker inside a sentence is not a claimed receipt. A "
            "false NOT CHECKED line on ordinary turns is how a gate gets switched "
            f"off.\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}")

    def test_a_real_receipt_block_still_reports_not_checked(self, tmp_path):
        """The control. A shape check tight enough to reject prose must still
        accept what the producer actually emits, or the fix silences the warning
        this whole block exists to print."""
        root = _instance(tmp_path, with_route_lane=False)
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        proc = _run(root, _transcript(tmp_path, "write it",
                                      _producer_message(receipt, "The body")),
                    tmp_path / "c.json")
        assert proc.returncode == 0, proc.stderr
        assert "NOT CHECKED" in _system_message(proc), (
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}")



# --- captured from the producer of record, 2026-09-02 ---------------------------
#
# consulting @ bc4fba6c, branch feat/gtm-visibility-surfaces. Produced by RUNNING
# `pipeline.cycle.draft_reddit_original` with a stubbed model runner and replaying
# `pipeline.social`'s reddit print sequence -- not written from memory: the receipt
# store refuses an out-of-lane mint (it checks `loop.generator` against the call
# stack), so these bytes could not have been faked into existence.
#
# The two load-bearing facts this fixture pins, both read off the producer source:
#   - the reddit lane emits NO `=== DRAFT ===` marker, only its own wrapper;
#   - the receipt hashes `draft.body` ALONE (cycle.py:1387), so the title line and
#     the FOUNDER REVIEW footer must NOT reach the hash.
REDDIT_HANDOFF = '{\n "channel": "reddit",\n "at": "2026-09-02T00:00:00Z",\n "stages": [\n  {\n   "stage": "generate",\n   "status": "ok"\n  },\n  {\n   "stage": "reddit-format",\n   "status": "ok"\n  },\n  {\n   "stage": "gates",\n   "status": "clean",\n   "reasons": []\n  },\n  {\n   "stage": "reddit-format-final",\n   "status": "ok"\n  }\n ],\n "voice_source": "q-consult/voice (reddit pool, founder-supplied 2026-09-02)",\n "publishes": false,\n "human_boundary": "founder must review subreddit rules",\n "archetype": {\n  "id": "thread",\n  "name": "The Thread",\n  "why": "nothing more specific matched, so this is the default, which also carries the strongest evidence in the corpus",\n  "from_corpus": true\n },\n "experience": {\n  "matched": [],\n  "offered_to_writer": false\n },\n "style": {\n  "before_level": "ok",\n  "before_distance": 4.87,\n  "flags": [],\n  "after_level": "ok",\n  "after_distance": 4.87,\n  "revisions": 0,\n  "status": "reviewed",\n  "fingerprint": {\n   "authorship": 0.5025581904034683,\n   "authorship_band": "mid",\n   "authorship_reference": null,\n   "authorship_tokenization": "single-document-512",\n   "authorship_model": "rrivera1849/LUAR-MUD",\n   "authorship_words": 95,\n   "authorship_region_n": 30,\n   "authorship_held_out": 0,\n   "authorship_reference_n": 0\n  }\n },\n "human_review": {\n  "status": "human-review-required",\n  "checks": {\n   "factuality": "human-review",\n   "clickbait": "human-review",\n   "substance": "human-review",\n   "conclusion": "human-review",\n   "self_promotion": "human-review",\n   "subreddit_fit": "human-review"\n  }\n },\n "route_receipt": {\n  "attempt_id": "fcde4845-fb2f-4056-8e4b-d2251eac116a",\n  "session_id": "2026-09-02T00:00:00Z",\n  "origin_message_id": "claude-request:2026-09-02T00:00:00Z",\n  "completion_message_id": "claude-reddit-draft:2026-09-02T00:00:00Z",\n  "request_hash": "5b8e36f443fffe9d05bc6d8a731a73ea065d4e806cd460d1e6aa3ccfaa24ef53",\n  "unchecked": [],\n  "surface": "reddit-post",\n  "channel": "reddit",\n  "issued_at": "2026-09-02T22:45:06Z",\n  "expires_at": 1788390006.166553,\n  "output_hash": "7501b5b3b81e103421dd253f4b6057d0e90a35bbb179012e8bfbfd8aad23d689",\n  "gates": {\n   "deterministic_gates": true,\n   "human_boundary": true\n  },\n  "loop": {\n   "generator": "pipeline.cycle.draft_reddit_original",\n   "corpus_sha": "c771b52dedb4ff7387303a06aea529e358f1afd0e50c40f41cd7451712c7824e",\n   "exemplar_ids": [\n    "post-agent-says-done-receipts",\n    "post-act-as-expert-useless",\n    "post-ai-cyber-turd-polishing",\n    "post-analysts-technical-ceiling"\n   ],\n   "score": {\n    "findings": 0,\n    "exemplars": 131,\n    "unchecked": [],\n    "exit": 0,\n    "text_sha": "ad5f429ea403fb59315350e7f3b386ebc80018b8d9816d31da03574e0f88050a"\n   }\n  },\n  "loop_sha": "1352df52bf30c45e8ae7805685558facd12fdb4e91b055d1e173738881dc0537",\n  "status": "complete"\n }\n}\n\n=== ROUTE RECEIPT ===\n{"attempt_id": "fcde4845-fb2f-4056-8e4b-d2251eac116a", "channel": "reddit", "completion_message_id": "claude-reddit-draft:2026-09-02T00:00:00Z", "expires_at": 1788390006.166553, "gates": {"deterministic_gates": true, "human_boundary": true}, "issued_at": "2026-09-02T22:45:06Z", "loop": {"corpus_sha": "c771b52dedb4ff7387303a06aea529e358f1afd0e50c40f41cd7451712c7824e", "exemplar_ids": ["post-agent-says-done-receipts", "post-act-as-expert-useless", "post-ai-cyber-turd-polishing", "post-analysts-technical-ceiling"], "generator": "pipeline.cycle.draft_reddit_original", "score": {"exemplars": 131, "exit": 0, "findings": 0, "text_sha": "ad5f429ea403fb59315350e7f3b386ebc80018b8d9816d31da03574e0f88050a", "unchecked": []}}, "loop_sha": "1352df52bf30c45e8ae7805685558facd12fdb4e91b055d1e173738881dc0537", "origin_message_id": "claude-request:2026-09-02T00:00:00Z", "output_hash": "7501b5b3b81e103421dd253f4b6057d0e90a35bbb179012e8bfbfd8aad23d689", "request_hash": "5b8e36f443fffe9d05bc6d8a731a73ea065d4e806cd460d1e6aa3ccfaa24ef53", "session_id": "2026-09-02T00:00:00Z", "status": "complete", "surface": "reddit-post", "unchecked": []}\n\n=== REDDIT DRAFT (ATTENDED, PUBLISHES NOTHING) ===\nTITLE: The gate that passed because it had nothing to look at\n\nWe shipped a propagation check that compared every instance copy of a hook against the skeleton copy. It went green and stayed green. Then I read the loop and found it had inspected nothing, because the sibling checkouts it walks only exist on the laptop that owns them. Green meant the population was missing, and that renders the same as a clean fleet.\n\nThe fix wasn\'t a better assertion. It was making the check say how many things it actually looked at, and refuse to report a verdict when it looked at none of them.\n\nFOUNDER REVIEW REQUIRED: subreddit rules, and the six checks above are flags, not passes.\n'

#: The exact bytes the producer passed to `output_hash`. Same run.
REDDIT_BODY = "We shipped a propagation check that compared every instance copy of a hook against the skeleton copy. It went green and stayed green. Then I read the loop and found it had inspected nothing, because the sibling checkouts it walks only exist on the laptop that owns them. Green meant the population was missing, and that renders the same as a clean fleet.\n\nThe fix wasn't a better assertion. It was making the check say how many things it actually looked at, and refuse to report a verdict when it looked at none of them."


def _producer_output_hash(text, surface, channel):
    """The producer's own envelope, transcribed from consulting route_contract.py.

    A SECOND COPY of another repo's algorithm, and that is deliberate: the contract
    between these two repos shares no code and therefore has no test, so the only
    way this side can assert "the draft I extract hashes to the receipt's own
    output_hash" is to recompute it. If consulting changes the envelope this goes
    red, which is the right direction for a cross-repo contract -- a silent
    mismatch is exactly what shipped.
    """
    envelope = {
        "channel": channel,
        "kind": "output",
        "surface": surface,
        "text": unicodedata.normalize("NFC", str(text)).replace(
            "\r\n", "\n").replace("\r", "\n"),
    }
    encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TestTheRedditProducerHandoff:
    """Codex major, ASK-1197 round 3. `_route_draft` knew one wrapper. The reddit
    lane emits another, so every receipt-bearing Reddit draft was refused as an
    output mismatch on every direct handoff -- a valid receipt, rejected."""

    def test_the_extractor_returns_exactly_the_bytes_the_receipt_hashed(self):
        got = gate._route_draft(REDDIT_HANDOFF)
        assert got == REDDIT_BODY, (
            "the extracted draft is not the slab the producer hashed, so the "
            "output-hash comparison can never match.\n"
            "got:  %r\nwant: %r" % (got, REDDIT_BODY))

    def test_the_extracted_draft_hashes_to_the_receipts_own_output_hash(self):
        """The defect itself, not a proxy for it. This is the comparison
        `enforce_route_receipt` makes, run against real producer bytes."""
        receipt = gate._receipt_block(REDDIT_HANDOFF)
        assert isinstance(receipt, dict), receipt
        recomputed = _producer_output_hash(
            gate._route_draft(REDDIT_HANDOFF), receipt["surface"], receipt["channel"])
        assert recomputed == receipt["output_hash"], (
            "a genuine Reddit receipt does not match its own draft, which the gate "
            "reports as `route receipt does not match the assistant output`.\n"
            "  recomputed: %s\n  receipt:    %s"
            % (recomputed, receipt["output_hash"]))

    def test_the_title_line_and_the_review_footer_are_not_in_the_draft(self):
        """Names the two blocks the old extractor swept in. Separate from the hash
        assertion on purpose: this one says WHY it mismatched, so a future failure
        is readable without recomputing anything."""
        extracted = gate._route_draft(REDDIT_HANDOFF)
        assert "TITLE:" not in extracted, extracted[:200]
        assert "FOUNDER REVIEW REQUIRED" not in extracted, extracted[-200:]
        assert "ROUTE RECEIPT" not in extracted, extracted[:200]

    def test_the_receipt_still_parses_out_of_the_reddit_wrapper(self):
        receipt = gate._receipt_block(REDDIT_HANDOFF)
        assert receipt["surface"] == "reddit-post" and receipt["channel"] == "reddit"
        assert "loop_sha" in receipt, sorted(receipt)

    def test_the_x_lane_wrapper_still_extracts(self):
        """THE CONTROL. The idea-lane shape is RECEIPT-then-DRAFT with no reddit
        wrapper, pinned producer-side at test_route_boundary.py:54. A reddit branch
        that stole this path would pass every assertion above while breaking the
        lane that already worked."""
        draft = "The body of an x draft, long enough to be measured."
        message = _producer_message({name: "x" for name in STUB_MATCH_FIELDS}, draft)
        assert gate._route_draft(message) == draft, gate._route_draft(message)


class TestTheNoticeReachesTheUser:
    """Codex major, ASK-1197 round 4, and the contradiction sp-f5144496 recorded.

    `report_not_checked` wrote plain text to stdout and called that delivery,
    while `finish_ok` in the same file emits `{"systemMessage": ...}` and says in
    its own comment that plain stdout from a Stop hook is dropped. Both could not
    be right. The queue-then-one-envelope shape resolves it and also removes the
    second hazard: two `print(json.dumps(...))` calls on one stream is one JSON
    document to every consumer that parses it.
    """

    def test_the_notice_is_delivered_as_one_parseable_envelope(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=False)
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        proc = _run(root, _transcript(tmp_path, "write it",
                                      _producer_message(receipt, "The body")),
                    tmp_path / "c.json")
        assert proc.returncode == 0, proc.stderr
        message = _system_message(proc)
        assert "NOT CHECKED" in message, message
        assert proc.stdout.count("\n") <= 1, (
            "more than one line on stdout means more than one document, and a "
            f"consumer parses the first one only.\nstdout={proc.stdout!r}")

    def test_the_notice_is_not_bare_text_on_stdout(self, tmp_path):
        """The finding stated as its own assertion. Bare text on this stream is
        invisible to the user AND corrupts the envelope if anything is appended."""
        root = _instance(tmp_path, with_route_lane=False)
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        proc = _run(root, _transcript(tmp_path, "write it",
                                      _producer_message(receipt, "The body")),
                    tmp_path / "c.json")
        stripped = proc.stdout.strip()
        assert stripped.startswith("{") and stripped.endswith("}"), (
            "stdout is not a JSON envelope, so the notice was never shown to "
            f"anyone.\nstdout={proc.stdout!r}")

    def test_a_refusal_beats_a_pending_notice(self, tmp_path):
        """Pinning the precedence the reviewer asked for. A held turn must not
        also emit an exit-0 envelope: the block is the louder and truer message,
        and a queued notice is dropped rather than printed alongside it."""
        root = _instance(tmp_path, with_route_lane=True)
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        proc = _run(root, _transcript(tmp_path, "write it", assistant),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            f"rc={proc.returncode} stderr={proc.stderr}")
        assert proc.stdout.strip() == "" or "systemMessage" not in proc.stdout, (
            "a held turn also emitted an exit-0 user envelope. The refusal on "
            f"stderr is the message.\nstdout={proc.stdout!r}")
        assert "receipt" in proc.stderr, proc.stderr


class TestAHookNameIsNotAnEnvelope:
    """Codex minor, ASK-1197 round 4. `_INJECTED_OPENER` matched a bare hook NAME
    at the start of the text, so the founder's own sentence about a hook was
    erased as machine prose. Combined with round 2's "no founder text is not a
    request", that turned one sentence into a route-enforcement bypass."""

    def test_his_sentence_about_a_hook_survives(self):
        text = ("Stop hook keeps eating my linkedin drafts, write me a post "
                "about what that taught me")
        assert gate.founder_typed_text(text) == text, (
            "his request was erased because it opens with a hook's name. A gate "
            "a sentence can switch off is not a gate.")

    def test_a_colonless_hook_mention_survives(self):
        assert gate.founder_typed_text("Stop hook: fix it") == "Stop hook: fix it"

    def test_a_labelled_injection_still_drops(self):
        """THE CONTROL, and it is the half that matters more. A narrowing that
        stopped dropping real injections would reopen the three-occurrence
        deadlock this opener exists to close.

        THE SHAPES HERE ARE THE MEASURED ONES (round 14). Two entries were
        removed: "Stop hook feedback: the draft was refused" and
        "UserPromptSubmit hook output: injected lessons", both written mid-line
        with prose after the colon. Neither was ever measured -- the 621 real
        Stop-feedback records put the colon at END OF LINE -- and both are
        indistinguishable from "Stop hook broke again: here is the trace", which
        is the founder sentence round 14 exists to stop erasing. Keeping them
        would mean keeping the bypass. The narrowed coverage is sp-2694343c.
        """
        for injected in (
            "PostToolUse:Bash hook additional context: 55 minutes since your "
            "last write. You may be stuck.",
            "Stop hook feedback:\n[python3 gate.py]: voice-stop-gate: held",
            "<system-reminder>do the thing</system-reminder>",
            "[SYSTEM NOTIFICATION] a subagent finished the reply-lane work",
        ):
            assert gate.founder_typed_text(injected) == "", injected

    def test_a_founder_sentence_that_reaches_a_colon_survives(self):
        """The round 14 major itself. A colon within four words is ordinary
        prose, not an envelope."""
        for typed in ("Stop hook broke again: here is the trace",
                      "Stop hook fired twice: why?",
                      "PostToolUse hook noisy again: can we quiet it"):
            assert gate.founder_typed_text(typed) == typed, typed

    def test_a_hook_named_request_still_reaches_the_classifier(self, tmp_path):
        """End to end: the bypass, not a proxy for it. With the lane installed and
        the request routed, a receipt is required -- so the turn must be HELD.
        Before the fix his text was erased, the request was empty, and
        enforcement returned early with rc 0."""
        root = _instance(tmp_path, with_route_lane=True)
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        transcript = _records_transcript(tmp_path, [
            _user("Stop hook keeps eating my linkedin drafts, write me a post "
                  "about what that taught me"),
            _assistant(assistant),
        ])
        proc = _run(root, transcript, tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            "a routed request that merely begins with a hook's name was waved "
            f"through with no receipt. rc={proc.returncode} stdout={proc.stdout} "
            f"stderr={proc.stderr}")
        assert "receipt" in proc.stderr, proc.stderr


# --- captured from the idea lane, 2026-09-02 ------------------------------------
#
# consulting @ bc4fba6c. Produced by RUNNING `pipeline.cycle.draft_from_idea`
# with a stubbed writer and replaying `pipeline.social`'s `idea` print sequence.
# The receipt hashes `final_text` alone (cycle.py:1210), and at capture time
# `receipt["output_hash"] == output_hash(text, "social-post", "x")` was verified
# True before these bytes were written down.
#
# X AND LINKEDIN SHARE THIS SHAPE. `social.py`'s `idea` branch has no channel fork
# between the draft marker and the card; only the card's CONTENT differs. A
# linkedin capture run refused on a content contract, which is a producer-side
# content verdict and not a different wrapper, so one fixture covers both and this
# comment says so rather than a second fixture implying a second measurement.
#
# THE DRAFT DELIBERATELY SAYS "My VOICE in the review was wrong" mid-body. That is
# the control the truncation must not trip on: the marker is a line start, not the
# word.
X_HANDOFF = '{\n "channel": "x",\n "at": "2026-09-02T00:00:00Z",\n "stages": [\n  {\n   "stage": "generate",\n   "status": "ok"\n  },\n  {\n   "stage": "gates",\n   "status": "clean",\n   "reasons": []\n  }\n ],\n "archetype": {\n  "id": "thread",\n  "name": "The Thread",\n  "why": "nothing more specific matched, so this is the default, which also carries the strongest evidence in the corpus",\n  "from_corpus": true\n },\n "experience": {\n  "matched": [],\n  "offered_to_writer": false\n },\n "style": {\n  "before_level": "ok",\n  "before_distance": 1.52,\n  "flags": [],\n  "after_level": "ok",\n  "after_distance": 1.52,\n  "revisions": 0,\n  "status": "reviewed",\n  "fingerprint": {\n   "authorship": 0.6214958642981991,\n   "authorship_band": "mid",\n   "authorship_reference": null,\n   "authorship_tokenization": "single-document-512",\n   "authorship_model": "rrivera1849/LUAR-MUD",\n   "authorship_words": 89,\n   "authorship_region_n": 30,\n   "authorship_held_out": 0,\n   "authorship_reference_n": 0\n  }\n },\n "route_receipt": {\n  "attempt_id": "ab2355e0-ed5a-4403-a4c5-95f48a38f9d6",\n  "session_id": "2026-09-02T00:00:00Z",\n  "origin_message_id": "claude-request:2026-09-02T00:00:00Z",\n  "completion_message_id": "claude-draft:2026-09-02T00:00:00Z",\n  "request_hash": "f06c13370af8fcae0632bfb6e957221524b4f53cccbf2abe15842cfa07ad9fd7",\n  "unchecked": [],\n  "surface": "social-post",\n  "channel": "x",\n  "issued_at": "2026-09-02T23:21:39Z",\n  "expires_at": 1788392199.699193,\n  "output_hash": "6c5328f0c938c972974d3e0f0d86029c6e6c4e2c9422d14ec29a57832b5f399e",\n  "gates": {\n   "deterministic_gates": true,\n   "human_boundary": true\n  },\n  "loop": {\n   "generator": "pipeline.cycle.draft_from_idea",\n   "corpus_sha": "c771b52dedb4ff7387303a06aea529e358f1afd0e50c40f41cd7451712c7824e",\n   "exemplar_ids": [\n    "x-29",\n    "x-28",\n    "x-30",\n    "x-31",\n    "post-finish-the-day-founder-revision",\n    "post-obsidian-graph-founder-revision"\n   ],\n   "score": {\n    "findings": 0,\n    "exemplars": 131,\n    "unchecked": [],\n    "exit": 0,\n    "text_sha": "cfba65e2580b34060d322010fb61190c5e572bb9795876392d5821bc11fc9fb4"\n   }\n  },\n  "loop_sha": "0a48a2d9fa472ff97a9fffb21a1ef4b48048ea37629b3f504f170113a0b2310c",\n  "status": "complete"\n }\n}\n\n=== ROUTE RECEIPT ===\n{"attempt_id": "ab2355e0-ed5a-4403-a4c5-95f48a38f9d6", "channel": "x", "completion_message_id": "claude-draft:2026-09-02T00:00:00Z", "expires_at": 1788392199.699193, "gates": {"deterministic_gates": true, "human_boundary": true}, "issued_at": "2026-09-02T23:21:39Z", "loop": {"corpus_sha": "c771b52dedb4ff7387303a06aea529e358f1afd0e50c40f41cd7451712c7824e", "exemplar_ids": ["x-29", "x-28", "x-30", "x-31", "post-finish-the-day-founder-revision", "post-obsidian-graph-founder-revision"], "generator": "pipeline.cycle.draft_from_idea", "score": {"exemplars": 131, "exit": 0, "findings": 0, "text_sha": "cfba65e2580b34060d322010fb61190c5e572bb9795876392d5821bc11fc9fb4", "unchecked": []}}, "loop_sha": "0a48a2d9fa472ff97a9fffb21a1ef4b48048ea37629b3f504f170113a0b2310c", "origin_message_id": "claude-request:2026-09-02T00:00:00Z", "output_hash": "6c5328f0c938c972974d3e0f0d86029c6e6c4e2c9422d14ec29a57832b5f399e", "request_hash": "f06c13370af8fcae0632bfb6e957221524b4f53cccbf2abe15842cfa07ad9fd7", "session_id": "2026-09-02T00:00:00Z", "status": "complete", "surface": "social-post", "unchecked": []}\n\n=== DRAFT ===\nA propagation check compared every instance copy of a hook against the skeleton copy. It went green and stayed green.\n\nThen I read the loop. It had inspected nothing, because the checkouts it walks live on the laptop that owns them. Green meant the population was missing, and that renders the same as a clean fleet.\n\nMy VOICE in the review was wrong for weeks. The fix was making the check say how many things it looked at, and refuse a verdict when it looked at none of them.\n\n=== HOW TO POST THIS ===\nArchetype: The Thread\nWhy: nothing more specific matched, so this is the default, which also carries the strongest evidence in the corpus\nEvidence: thread starter plus a colon-ending setup line, 1.67x on n=226\nThread: YES. Post this, then reply to it with the detail. The reply chain is where the numbers and the mechanism go.\nImage: Optional. Add one only if it carries evidence the text is claiming. A photo on its own measures 1.04x, which is nothing.\nImage must show one of:\n  - a benchmark or comparison table, plain background, real numbers, no styling\n  - the actual first page of a paper or document, at a resolution where the title reads\n  - a chart carrying real counts, plain colors, no 3D and no gradient\n  - a screenshot cropped to the part that matters, with one hand-drawn circle or highlight on it and no caption explaining what is already marked\n  - an unstaged photo of the real thing, phone-camera quality, no product gloss\n  - a terminal or tool session captured mid-task, not a mockup\nNever:\n  - stock photography\n  - an AI-generated illustration\n  - a quote rendered as text on a colored background\n  - a screenshot so wide the text is unreadable on a phone\n'

#: The exact bytes the producer passed to `output_hash`. Same run.
X_DRAFT = 'A propagation check compared every instance copy of a hook against the skeleton copy. It went green and stayed green.\n\nThen I read the loop. It had inspected nothing, because the checkouts it walks live on the laptop that owns them. Green meant the population was missing, and that renders the same as a clean fleet.\n\nMy VOICE in the review was wrong for weeks. The fix was making the check say how many things it looked at, and refuse a verdict when it looked at none of them.'

#: The same captured handoff with the VOICE note in the position `social.py`
#: prints it. The note's text is transcribed from social.py's own literal; its
#: CONDITION (`voice_judged` in the receipt's `unchecked`) did not fire in the
#: capture run, because the style judge ran and the trail recorded
#: `status: "reviewed"`. Said plainly rather than implied: the surrounding bytes
#: are captured, this one block is transcribed from the producer's source.
X_HANDOFF_WITH_VOICE_NOTE = '{\n "channel": "x",\n "at": "2026-09-02T00:00:00Z",\n "stages": [\n  {\n   "stage": "generate",\n   "status": "ok"\n  },\n  {\n   "stage": "gates",\n   "status": "clean",\n   "reasons": []\n  }\n ],\n "archetype": {\n  "id": "thread",\n  "name": "The Thread",\n  "why": "nothing more specific matched, so this is the default, which also carries the strongest evidence in the corpus",\n  "from_corpus": true\n },\n "experience": {\n  "matched": [],\n  "offered_to_writer": false\n },\n "style": {\n  "before_level": "ok",\n  "before_distance": 1.52,\n  "flags": [],\n  "after_level": "ok",\n  "after_distance": 1.52,\n  "revisions": 0,\n  "status": "reviewed",\n  "fingerprint": {\n   "authorship": 0.6214958642981991,\n   "authorship_band": "mid",\n   "authorship_reference": null,\n   "authorship_tokenization": "single-document-512",\n   "authorship_model": "rrivera1849/LUAR-MUD",\n   "authorship_words": 89,\n   "authorship_region_n": 30,\n   "authorship_held_out": 0,\n   "authorship_reference_n": 0\n  }\n },\n "route_receipt": {\n  "attempt_id": "ab2355e0-ed5a-4403-a4c5-95f48a38f9d6",\n  "session_id": "2026-09-02T00:00:00Z",\n  "origin_message_id": "claude-request:2026-09-02T00:00:00Z",\n  "completion_message_id": "claude-draft:2026-09-02T00:00:00Z",\n  "request_hash": "f06c13370af8fcae0632bfb6e957221524b4f53cccbf2abe15842cfa07ad9fd7",\n  "unchecked": [],\n  "surface": "social-post",\n  "channel": "x",\n  "issued_at": "2026-09-02T23:21:39Z",\n  "expires_at": 1788392199.699193,\n  "output_hash": "6c5328f0c938c972974d3e0f0d86029c6e6c4e2c9422d14ec29a57832b5f399e",\n  "gates": {\n   "deterministic_gates": true,\n   "human_boundary": true\n  },\n  "loop": {\n   "generator": "pipeline.cycle.draft_from_idea",\n   "corpus_sha": "c771b52dedb4ff7387303a06aea529e358f1afd0e50c40f41cd7451712c7824e",\n   "exemplar_ids": [\n    "x-29",\n    "x-28",\n    "x-30",\n    "x-31",\n    "post-finish-the-day-founder-revision",\n    "post-obsidian-graph-founder-revision"\n   ],\n   "score": {\n    "findings": 0,\n    "exemplars": 131,\n    "unchecked": [],\n    "exit": 0,\n    "text_sha": "cfba65e2580b34060d322010fb61190c5e572bb9795876392d5821bc11fc9fb4"\n   }\n  },\n  "loop_sha": "0a48a2d9fa472ff97a9fffb21a1ef4b48048ea37629b3f504f170113a0b2310c",\n  "status": "complete"\n }\n}\n\n=== ROUTE RECEIPT ===\n{"attempt_id": "ab2355e0-ed5a-4403-a4c5-95f48a38f9d6", "channel": "x", "completion_message_id": "claude-draft:2026-09-02T00:00:00Z", "expires_at": 1788392199.699193, "gates": {"deterministic_gates": true, "human_boundary": true}, "issued_at": "2026-09-02T23:21:39Z", "loop": {"corpus_sha": "c771b52dedb4ff7387303a06aea529e358f1afd0e50c40f41cd7451712c7824e", "exemplar_ids": ["x-29", "x-28", "x-30", "x-31", "post-finish-the-day-founder-revision", "post-obsidian-graph-founder-revision"], "generator": "pipeline.cycle.draft_from_idea", "score": {"exemplars": 131, "exit": 0, "findings": 0, "text_sha": "cfba65e2580b34060d322010fb61190c5e572bb9795876392d5821bc11fc9fb4", "unchecked": []}}, "loop_sha": "0a48a2d9fa472ff97a9fffb21a1ef4b48048ea37629b3f504f170113a0b2310c", "origin_message_id": "claude-request:2026-09-02T00:00:00Z", "output_hash": "6c5328f0c938c972974d3e0f0d86029c6e6c4e2c9422d14ec29a57832b5f399e", "request_hash": "f06c13370af8fcae0632bfb6e957221524b4f53cccbf2abe15842cfa07ad9fd7", "session_id": "2026-09-02T00:00:00Z", "status": "complete", "surface": "social-post", "unchecked": []}\n\n=== DRAFT ===\nA propagation check compared every instance copy of a hook against the skeleton copy. It went green and stayed green.\n\nThen I read the loop. It had inspected nothing, because the checkouts it walks live on the laptop that owns them. Green meant the population was missing, and that renders the same as a clean fleet.\n\nMy VOICE in the review was wrong for weeks. The fix was making the check say how many things it looked at, and refuse a verdict when it looked at none of them.\n\nVOICE: NOT CHECKED. The gates above are NEGATIVE checks (no emdash, no banned phrase, format, bio). Nothing here asserted this sounds like you. Green means nothing banned was found. You are the voice check.\n\n=== HOW TO POST THIS ===\nArchetype: The Thread\nWhy: nothing more specific matched, so this is the default, which also carries the strongest evidence in the corpus\nEvidence: thread starter plus a colon-ending setup line, 1.67x on n=226\nThread: YES. Post this, then reply to it with the detail. The reply chain is where the numbers and the mechanism go.\nImage: Optional. Add one only if it carries evidence the text is claiming. A photo on its own measures 1.04x, which is nothing.\nImage must show one of:\n  - a benchmark or comparison table, plain background, real numbers, no styling\n  - the actual first page of a paper or document, at a resolution where the title reads\n  - a chart carrying real counts, plain colors, no 3D and no gradient\n  - a screenshot cropped to the part that matters, with one hand-drawn circle or highlight on it and no caption explaining what is already marked\n  - an unstaged photo of the real thing, phone-camera quality, no product gloss\n  - a terminal or tool session captured mid-task, not a mockup\nNever:\n  - stock photography\n  - an AI-generated illustration\n  - a quote rendered as text on a colored background\n  - a screenshot so wide the text is unreadable on a phone\n'


class TestAPublishSentenceDoesNotWidenTheLintToTheEnvelope:
    """Codex finding 1 on PR #295 round 15, MAJOR and confirmed. A regression
    this branch introduces against main.

    THE SHAPE. The assistant announces a delivery ("Here is the post for X.")
    and pastes the producer's handoff under it. `_publish_framed` sees the
    publish sentence, finds no prose fence or blockquote to set the draft off,
    and falls back to `text.strip()` -- the ENTIRE 5023-byte envelope, receipt
    JSON, how-to-post card and all. voice-lint then grades the producer's own
    posting instructions and reports 10 capitalization violations on the
    "Image must show one of:" bullets, exiting 2 and blocking a valid handoff.

    WHY IT IS A REGRESSION, not an inherited defect. `_publish_framed`,
    `_draft_marker_slab` and `_route_draft` do not exist on origin/main; main
    has `extract_publishable` alone. The whole precedence chain arrives with
    this PR, so the false block does too.

    THE FIX IS ORDERING, not classification. When a PRODUCER RECEIPT is present,
    the lane and not the assistant decided where the draft starts, so the lint
    grades `_route_draft(text)`. Narrow on purpose:

      - the publish sentence is still the PRECONDITION, so round 13 holds. An
        instance with no lane that pastes producer output WITHOUT announcing it
        is still not linted at all.
      - a bare `=== DRAFT ===` with no receipt still does NOT win over the
        publish sentence, so round 11 holds (see the control below).

    It can only ever lint LESS than before, never more, so it cannot newly block
    a turn on the 24 lane-less instances.
    """

    FRAMED = "Here is the post for X.\n\n" + X_HANDOFF

    def test_the_lint_grades_the_draft_body_not_the_envelope(self):
        """ASSERT ON THE BODY, not on a violation count. A count can fall to
        zero for reasons that have nothing to do with precedence; the extracted
        bytes are where the decision is actually made."""
        got = gate.extract_publishable(self.FRAMED)
        assert got == X_DRAFT, (
            "the publish sentence widened the lint to the whole producer "
            "envelope instead of the draft the receipt hashed.\n"
            "got %d bytes, want %d bytes\ngot: %r"
            % (len(got.encode()), len(X_DRAFT.encode()), got[:200]))

    def test_the_producer_trailer_is_not_in_what_gets_linted(self):
        """The violations Codex measured came from the how-to-post card. Naming
        the actual offending text, so a future regression says why it matters."""
        got = gate.extract_publishable(self.FRAMED)
        assert "HOW TO POST THIS" not in got, got[-300:]
        assert "stock photography" not in got, (
            "the producer's posting advice is being voice-linted as founder "
            "content; those bullets are the 10 lowercase-start violations")

    def test_a_bare_draft_marker_still_does_not_truncate_the_slab(self):
        """THE ROUND 11 CONTROL. Without a producer receipt, a trailing bare
        `=== DRAFT ===` must NOT win over the publish sentence -- that was the
        round 10 bypass, where content the base version blocked started passing.
        This is the case the fix deliberately leaves alone."""
        bare = ("Here's the post for LinkedIn.\n\n"
                "the body the founder actually announced, long enough to be "
                "measured against the floor.\n\n"
                "=== DRAFT ===\n"
                "a trailing slab appended after the fact\n")
        got = gate.extract_publishable(bare)
        assert "the body the founder actually announced" in got, (
            "a bare draft marker truncated a slab the publish sentence had "
            f"already claimed. round 11 bypass is back. got: {got!r}")


class TestTheIdeaLaneAdvisoryBlocks:
    """Codex major, ASK-1197 round 5 -- and my own capture, sp-20bdfcd9.

    The reddit branch was fixed one round earlier and its sibling was not. The X
    and LinkedIn lane prints the how-to-post card (and sometimes a VOICE note)
    after the draft, so the extractor hashed twenty-odd lines of posting advice
    into the draft and rejected every genuine receipt as an output mismatch.
    """

    def test_the_extractor_returns_exactly_the_bytes_the_receipt_hashed(self):
        got = gate._route_draft(X_HANDOFF)
        assert got == X_DRAFT, (
            "the extracted draft is not the slab the producer hashed.\n"
            "got:  %r\nwant: %r" % (got, X_DRAFT))

    def test_the_extracted_draft_hashes_to_the_receipts_own_output_hash(self):
        """The defect itself: the comparison `enforce_route_receipt` makes, run
        against real producer bytes."""
        receipt = gate._receipt_block(X_HANDOFF)
        recomputed = _producer_output_hash(
            gate._route_draft(X_HANDOFF), receipt["surface"], receipt["channel"])
        assert recomputed == receipt["output_hash"], (
            "a genuine X receipt does not match its own draft, which the gate "
            "reports as `route receipt does not match the assistant output`.\n"
            "  recomputed: %s\n  receipt:    %s"
            % (recomputed, receipt["output_hash"]))

    def test_the_posting_card_is_not_in_the_draft(self):
        extracted = gate._route_draft(X_HANDOFF)
        assert "HOW TO POST THIS" not in extracted, extracted[-300:]
        assert "Archetype:" not in extracted, extracted[-300:]

    def test_the_voice_note_is_truncated_when_it_fires(self):
        extracted = gate._route_draft(X_HANDOFF_WITH_VOICE_NOTE)
        assert extracted == X_DRAFT, (
            "the VOICE note is the FIRST trailing block when it fires, so it is "
            "the one the truncation has to catch.\ngot: %r" % (extracted,))

    def test_a_body_that_says_voice_mid_sentence_survives_whole(self):
        """THE CONTROL the marker shape exists for. Truncating on the word rather
        than the line start would cut this draft in half, and the hash assertion
        above would not notice because it hashes whatever came out."""
        extracted = gate._route_draft(X_HANDOFF)
        assert "My VOICE in the review was wrong for weeks." in extracted, extracted
        assert extracted.endswith("none of them."), extracted[-120:]

    def test_the_reddit_shape_still_extracts_whole(self):
        """The other control. A truncation added to the idea branch must not reach
        into the reddit branch, whose body legitimately has no such markers."""
        assert gate._route_draft(REDDIT_HANDOFF) == REDDIT_BODY

    def test_a_bare_receipt_then_draft_message_still_extracts(self):
        """And the pinned producer-side shape from test_route_boundary.py:54,
        which carries no advisory blocks at all."""
        draft = "The body of an x draft, long enough to be measured."
        message = _producer_message({name: "x" for name in STUB_MATCH_FIELDS}, draft)
        assert gate._route_draft(message) == draft


#: THE MEASURED HARNESS SHAPE of a Stop hook's exit-2 stderr coming back into the
#: transcript. Not assumed: measured 2026-09-02 across 11,156 transcript files
#: under the Claude Code projects tree, 621 records carrying this exact envelope.
#:
#:   {"type": "user", "isMeta": true,
#:    "message": {"role": "user",
#:                "content": "Stop hook feedback:\n[<hook command>]: <stderr>"}}
#:
#: Three details that a guessed fixture gets wrong. `message.content` is a plain
#: STRING, not a list of blocks. `turnCompanion` is ABSENT -- it appears on no
#: record of this kind anywhere in the corpus, so a detector keyed on it would
#: never fire. And the hook's stderr is carried VERBATIM inside, which is what
#: makes a marker this gate writes visible to the gate on the way back.
def _stop_hook_feedback(stderr_text):
    return {
        "type": "user",
        "isMeta": True,
        "message": {
            "role": "user",
            "content": ("Stop hook feedback:\n"
                        '[python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/'
                        'scripts/voice-stop-gate.py"]: ' + stderr_text),
        },
    }


#: The gate's OWN refusal, built from the gate's constant rather than
#: transcribed, and wrapped in the measured envelope. If the marker changes these
#: fixtures follow it instead of quietly testing a string nothing emits any more.
FED_BACK_REFUSAL_TEXT = (
    "voice-stop-gate: routed completion has no route receipt\n"
    + gate._REFUSAL_MARK)

#: What a UserPromptSubmit additionalContext injection looks like: harness
#: flagged, carries real text, and has nothing to do with this gate. Round 6
#: ended the founder's turn on this, which is the bypass.
LESSONS_INJECT_TEXT = (
    "CONTEXT FROM lessons-inject: prior lesson - a gate that cannot see its "
    "population must not report a verdict. Recall 3 of 12 lessons matched this "
    "request.")

class TestWhichInjectedRecordsEndTheTurn:
    """ASK-1197 rounds 5, 6 and 7, which are one argument with three answers.

    Round 5: skipping an injected record left a stale routed request standing, so
    this gate's own refusal, fed back, was judged against the request from before
    the refusal and refused again. Every refusal re-armed itself.

    Round 6 fixed that by ending the turn on ANY text-bearing meta record, and
    that was a real bypass: a lessons-inject additionalContext or a system
    reminder between his routed request and the draft blanked the request and the
    draft shipped with no receipt check.

    Round 7 is the split those two rounds were circling. An injected record means
    one of two opposite things, and record ORDER cannot tell them apart:

      (a) this gate's OWN refusal -- the assistant is answering the gate, his
          request is no longer the subject, the turn is over;
      (b) anything else injected -- his request is still live and still owes a
          receipt.

    (a) is recognised by `_REFUSAL_MARK`, which this gate writes itself, so the
    recogniser cannot drift from the thing it recognises.
    """

    def _routed_turn(self, tmp_path, records):
        root = _instance(tmp_path, with_route_lane=True)
        return _run(root, _records_transcript(tmp_path, records),
                    tmp_path / "c.json", classify="route")

    #: What an error report actually looks like: it QUOTES the refusal, because
    #: that is the information the founder needs. Written this way rather than as
    #: clean prose because clean prose is a draft by `candidate_draft`'s
    #: definition and a fixture that dodges that is testing a turn nobody sends.
    ASSISTANT_REPLY = (
        "The gate held the turn. It reported:\n\n"
        "voice-stop-gate: routed completion has no route receipt\n"
        + gate._REFUSAL_MARK + "\n\n"
        "I have not re-drafted anything yet.\n")


    def test_a_reply_to_refusal_feedback_is_refused_again(self, tmp_path):
        """INVERTED in round 15, and this is THE DEADLOCK, stated honestly.

        This asserted rc==0: his routed request, this gate's refusal arriving as a
        meta record, then the assistant explaining the failure, and the
        explanation completing. That exemption was measured strictly weaker than
        the gate consulting actually runs (2026-09-02, installed refuses this
        exact shape with RouteBoundaryError), and this file syncs over that gate.

        So the re-arm is real and it is BACK, because the alternative was shipping
        an enforcement regression to the founder's publishing instance to buy a
        deadlock fix that does not work. Consulting has lived with this loop and
        does not get worse by waiting.

        NOT a decision to keep the deadlock forever. The accepted fix is the
        producer marker (sp-6ce17a23): enforce only on output the route PRODUCER
        marked as a delivery, which ends the loop with a structural signal instead
        of trying to tell an error report from a draft by looking at the prose.
        Rounds 5-9 plus round 14's echo exemption are what trying that costs.
        """
        proc = self._routed_turn(tmp_path, [
            _user("write me a linkedin post about the propagation gate"),
            _stop_hook_feedback(FED_BACK_REFUSAL_TEXT),
            _assistant(self.ASSISTANT_REPLY),
        ])
        assert proc.returncode == 2, (
            "the reply to a refusal completed, so the route path is relaxed "
            "again relative to the installed gate. "
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "receipt" in proc.stderr.lower(), proc.stderr

    ROUTED_REQUEST = "write me a linkedin post about the propagation gate"

    CORRECTED_DRAFT = ("The corrected body of the draft, long enough to be "
                       "measured and to survive the floor.")

    def test_a_corrected_draft_after_a_refusal_is_still_verified(self, tmp_path):
        """Case 2, THE BYPASS, and the reason rounds 5-7 were wrong.

        After a refusal the assistant sends a CORRECTED draft. It sits in exactly
        the same transcript position as an error report, so no ordering rule can
        tell them apart -- which is why rounds 5, 6 and 7 all cleared the request
        here and let this draft ship with no receipt check at all. The output
        tells them apart: this one carries a draft, so it still owes a receipt.
        """
        assistant = ("Here's the corrected post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\n" + self.CORRECTED_DRAFT + "\n")
        proc = self._routed_turn(tmp_path, [
            _user(self.ROUTED_REQUEST),
            _stop_hook_feedback(FED_BACK_REFUSAL_TEXT),
            _assistant(assistant),
        ])
        assert proc.returncode == 2, (
            "a corrected draft sent after a refusal shipped with no receipt "
            "check. Clearing the request on the gate's own feedback is a bypass, "
            f"not a fix.\nrc={proc.returncode} stdout={proc.stdout}")
        assert "receipt" in proc.stderr, proc.stderr

    def test_a_corrected_draft_with_a_valid_receipt_completes(self, tmp_path):
        """Case 3. The other side of case 2: verification that PASSES must let the
        turn finish, or the loop closes again with the gate refusing correct work.
        """
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        receipt.update(surface="linkedin", channel="assaf",
                       request_hash=_stub_hash("rh:", self.ROUTED_REQUEST),
                       output_hash=_stub_hash("oh:", self.CORRECTED_DRAFT))
        proc = self._routed_turn(tmp_path, [
            _user(self.ROUTED_REQUEST),
            _stop_hook_feedback(FED_BACK_REFUSAL_TEXT),
            _assistant(_producer_message(receipt, self.CORRECTED_DRAFT)),
        ])
        assert proc.returncode == 0, (
            "a corrected draft carrying a VALID receipt was refused, so the "
            f"assistant can never satisfy the gate.\nrc={proc.returncode} "
            f"stdout={proc.stdout} stderr={proc.stderr}")

    def test_an_injected_context_record_does_not_disarm_the_gate(self, tmp_path):
        """Case 2, the round 6 bypass, and the reason (a) and (b) had to split.

        A UserPromptSubmit additionalContext (lessons-inject, voice-dna-loader) or
        a system reminder lands between his routed request and the draft. It is
        harness-flagged and carries real text, exactly like fed-back refusal
        feedback does -- and it means the opposite. His request is still live, so
        a draft with no receipt must still be refused.
        """
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        proc = self._routed_turn(tmp_path, [
            _user("write me a linkedin post about the propagation gate"),
            _user(LESSONS_INJECT_TEXT, isMeta=True),
            _assistant(assistant),
        ])
        assert proc.returncode == 2, (
            "an injected context record blanked the founder's routed request, so "
            "the draft shipped with no receipt check. Injection is not the end of "
            f"his turn.\nrc={proc.returncode} stdout={proc.stdout}")
        assert "receipt" in proc.stderr, proc.stderr

    def test_the_injected_context_is_not_read_as_his_request(self, tmp_path):
        """The other half of (b): skipped means skipped. The injected text must
        not become the request either, which is the third-occurrence deadlock."""
        path = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the propagation gate"),
            _user(LESSONS_INJECT_TEXT, isMeta=True),
        ])
        assert gate.find_final_user_text(path) == (
            "write me a linkedin post about the propagation gate")

    def test_a_new_request_after_the_feedback_re_arms_the_gate(self, tmp_path):
        """Case 2, THE CONTROL that matters most. The reset must not disarm the
        gate: a founder message AFTER the meta record is a genuinely new turn, and
        a routed completion in it still owes a receipt."""
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        proc = self._routed_turn(tmp_path, [
            _user("write me a linkedin post about the propagation gate"),
            _stop_hook_feedback(FED_BACK_REFUSAL_TEXT),
            _user("ok now write me a linkedin post about the reddit lane instead"),
            _assistant(assistant),
        ])
        assert proc.returncode == 2, (
            "a NEW founder request after the feedback was not enforced. The reset "
            f"disarmed the gate.\nrc={proc.returncode} stdout={proc.stdout}")
        assert "receipt" in proc.stderr, proc.stderr

    def test_a_tool_result_after_a_request_still_enforces(self, tmp_path):
        """Case 3, unchanged from round 2. A `user` record with no text block is
        transport: it neither ends the turn nor erases the request, or his request
        is blanked on every tool-using turn."""
        assistant = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER
                     + "\nThe body of the draft, long enough to be measured.\n")
        proc = self._routed_turn(tmp_path, [
            _user("write me a linkedin post about the propagation gate"),
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
            _assistant(assistant),
        ])
        assert proc.returncode == 2, (
            "a tool_result ended the founder's turn, so every tool-using turn now "
            f"bypasses route enforcement.\nrc={proc.returncode} stdout={proc.stdout}")

    def test_a_meta_record_with_no_text_does_not_end_the_turn(self, tmp_path):
        """The seam, stated directly. Only a meta record carrying TEXT is feedback;
        a flagged record with no text block is transport like any other, and
        treating it as an ending would disarm the gate on turns that carry one."""
        path = _records_transcript(tmp_path, [
            _user("write me a linkedin post about the propagation gate"),
            {"isMeta": True, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        ])
        assert gate.find_final_user_text(path) == (
            "write me a linkedin post about the propagation gate")


class TestTheLintAndRouteScopesAreDifferent:
    """ASK-1197 round 9. One cause behind five findings: the R8 net, with its
    contamination disqualifiers, was wired into BOTH paths. They ask different
    questions and need different predicates.

    LINT: framing REQUIRED (voice-enforcement.md scopes it to content sent to
    another person), and no disqualifier applies once framing is present -- a
    bulleted post is still a post.

    ROUTE, under a live routed request: framed is a draft always; unframed goes
    through the block splitter with the disqualifiers OFF, because the founder
    already asked for a post and adding a bullet must not buy a bypass.
    """

    CONVERSATIONAL = (
        "i ran the suite and got three failures. the walker was resetting the "
        "request, so the corrected draft never reached verification. fixed it.\n")

    def test_a_conversational_reply_is_not_linted(self, tmp_path):
        """Finding 1. Round 8 pointed the lint at `candidate_draft`, which needs no
        framing, so ordinary replies to the founder were voice-linted and exited 2.
        This text is full of lowercase sentence starts: if it is linted at all, the
        lint refuses it, so rc 0 proves the lint declined to look."""
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "what happened?", self.CONVERSATIONAL),
                    tmp_path / "c.json")
        assert proc.returncode == 0, (
            "an ordinary reply to the founder was voice-linted. "
            f"rc={proc.returncode} stderr={proc.stderr}")

    def test_a_conversational_reply_yields_no_publishable_draft(self):
        """The same finding at the unit, naming the function."""
        assert gate.extract_publishable(self.CONVERSATIONAL) == ""

    FRAMED_BULLETED = (
        "Here's the post for LinkedIn.\n\n"
        "```\n"
        "The gate held the turn and I could not tell why.\n\n"
        "- it printed nothing on stdout\n"
        "- the stderr went nowhere\n\n"
        "That is the whole bug.\n"
        "```\n")

    def test_a_framed_post_containing_a_list_is_still_linted(self):
        """Finding 2. The contamination disqualifier ran on the draft body, so a
        publish-framed post containing a bullet list stopped being a draft and was
        not voice-checked AT ALL. A bulleted post is still a post."""
        draft = gate.extract_publishable(self.FRAMED_BULLETED)
        assert draft, (
            "a framed post with a bullet list yielded no draft, so nothing was "
            "voice-checked")
        assert "- it printed nothing on stdout" in draft, draft

    def test_a_framed_post_containing_a_list_reaches_the_lint(self, tmp_path):
        """The same finding end to end. The draft carries a lowercase sentence
        start, so a lint that actually ran refuses it."""
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "write it", self.FRAMED_BULLETED),
                    tmp_path / "c.json")
        assert proc.returncode == 2, (
            "the voice lint never graded a framed post because it contained a "
            f"list. rc={proc.returncode} stdout={proc.stdout}")
        assert "voice" in proc.stderr.lower(), proc.stderr

    UNFRAMED_BULLETED_DRAFT = (
        "The gate held the turn and nothing said why. Here is what I learned "
        "about building checks that can actually fail.\n\n"
        "- a check that cannot go red is decoration\n"
        "- name the input that makes it red, or do not ship it\n\n"
        "That rule has caught more of my bugs than any review.\n")

    def test_an_unframed_bulleted_draft_is_refused(self, tmp_path):
        """INVERTED in round 15. This test asserted the defect.

        Rounds 10-14 let an unframed completion under a live routed request pass
        with a NOT VERIFIED notice and exit 0, and this test pinned that. Measured
        2026-09-02 against consulting -- the one instance with the route lane
        installed -- its RUNNING gate refuses this exact input with
        RouteBoundaryError("routed completion has no route receipt").
        `voice-stop-gate.py` is not in kipi-update.sh's INSTANCE_OWNED_SUBTREES,
        so this file syncs over that gate: shipping the notice was a live
        enforcement regression on the founder's publishing instance.

        The route path now enforces unconditionally, matching installed. The
        deadlock this relaxation was reaching for is real and is NOT fixed here;
        the accepted fix is the producer marker (sp-6ce17a23), not a sixth
        prose heuristic.
        """
        root = _instance(tmp_path, with_route_lane=True)
        proc = _run(root, _transcript(tmp_path, "write me a linkedin post",
                                      self.UNFRAMED_BULLETED_DRAFT),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            "unframed publishable prose under a routed request passed without a "
            "receipt, which is weaker than the gate consulting runs today. "
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "receipt" in proc.stderr.lower(), proc.stderr

    def test_a_framed_draft_under_the_same_request_is_still_enforced(self):
        """THE CONTROL. Without it, "framing required" would read as "nothing is
        ever enforced", which is the bypass rounds 6-8 shipped."""
        framed = ("Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\n"
                  + self.UNFRAMED_BULLETED_DRAFT)
        assert gate._output_carries_draft(framed)


class TestTheRoutePathMatchesTheInstalledGate:
    """ASK-1197 round 15. The parity pin: on a lane-installed instance the route
    path refuses ALL THREE unframed shapes, exactly as consulting's running gate
    does today.

    HOW THIS WAS DERIVED, and why it is three cases rather than one. On
    2026-09-02 consulting's INSTALLED gate and this branch's port were loaded
    side by side (importlib, both against consulting's real lane) and called on
    the same inputs:

        case                 INSTALLED                     PORT (pre-fix)
        1 refusal echo       REFUSE RouteBoundaryError     PASS
        2 clarifying question REFUSE RouteBoundaryError    PASS
        3 unframed prose     REFUSE RouteBoundaryError     PASS

    All three diverged. `voice-stop-gate.py` is not in kipi-update.sh's
    INSTANCE_OWNED_SUBTREES, so landing the port replaces that gate; every PASS
    above was a live enforcement regression on the founder's publishing instance.

    Case 3 is the one that matters most -- it ships publishable content with no
    receipt -- but 1 and 2 are pinned too, because a fix that only closed case 3
    would need to tell a draft from a question, and it cannot: `extract_publishable`
    returns "" for both, `candidate_draft` returns content for both, and rounds
    5-9 failed to find a separator. Refusing all three IS the installed contract.

    The cost is the known deadlock, and this class does not pretend otherwise. The
    accepted fix is the producer marker (sp-6ce17a23), which replaces the guess
    with a structural signal. It is deliberately not attempted here.
    """

    REQUEST = "write a linkedin post about detection engineering"

    UNFRAMED_PROSE = (
        "Detection engineering is not about writing more rules.\n"
        "It is about deleting the ones that never fired.\n"
        "Every rule you keep is a promise you have to maintain.\n")

    QUESTION = (
        "Before I draft that, which angle do you want: the alert-fatigue one, "
        "or the rule-lifecycle one? Either works, they land differently.")

    def _refused(self, tmp_path, assistant_text, name):
        root = _instance(tmp_path, with_route_lane=True)
        proc = _run(root, _transcript(tmp_path, self.REQUEST, assistant_text,
                                      name=name),
                    tmp_path / (name + ".json"), classify="route")
        return proc

    def test_case_3_unframed_publishable_prose_is_refused(self, tmp_path):
        """THE REGRESSION THIS PR SHIPPED. Publishable content, no receipt, no
        framing. Pre-fix this exited 0 with a NOT VERIFIED notice."""
        proc = self._refused(tmp_path, self.UNFRAMED_PROSE, "case3")
        assert proc.returncode == 2, (
            "unframed publishable prose shipped without a receipt. This is the "
            "case consulting's installed gate refuses and the port did not. "
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "receipt" in proc.stderr.lower(), proc.stderr

    def test_case_2_a_clarifying_question_is_refused(self, tmp_path):
        """Installed parity, and the honest cost. This is the deadlock: a
        question under a live routed request is refused. Pinned so that a future
        change which relaxes it has to argue with a test rather than slip in as
        a port."""
        proc = self._refused(tmp_path, self.QUESTION, "case2")
        assert proc.returncode == 2, (
            "case 2 passed, so the route path is relaxed again relative to the "
            f"installed gate. rc={proc.returncode} stderr={proc.stderr}")

    def test_case_1_a_refusal_echo_is_refused(self, tmp_path):
        """Installed parity. The gate's own refusal quoted back is still a routed
        completion with no receipt. Round 14 exempted it; installed never did."""
        echoed = ("The previous turn was held: " + gate._REFUSAL_MARK
                  + " I could not deliver without a receipt.")
        proc = self._refused(tmp_path, echoed, "case1")
        assert proc.returncode == 2, (
            "case 1 passed, so the echo exemption is back. "
            f"rc={proc.returncode} stderr={proc.stderr}")

    def test_a_lane_less_instance_is_untouched_by_all_three(self, tmp_path):
        """THE CONTROL, and the reason this revert is safe for the other 24
        instances. The route path is inert without the lane, so none of the three
        shapes above reaches receipt enforcement there. Without this, "refuse
        everything" would read as a fleet-wide behaviour change."""
        for name, text in (("l1", self.UNFRAMED_PROSE), ("l2", self.QUESTION)):
            root = _instance(tmp_path / name, with_route_lane=False)
            proc = _run(root, _transcript(tmp_path, self.REQUEST, text,
                                          name=name + ".jsonl"),
                        tmp_path / (name + ".json"), classify="route")
            assert proc.returncode == 0, (
                "a lane-less instance refused on the route path, so this revert "
                f"changed behaviour on 24 instances. {name} "
                f"rc={proc.returncode} stderr={proc.stderr}")


class TestTheDraftFloor:
    """Finding 5. The R8 comment said the 80-byte floor was deleted while
    MIN_TEXT_BYTES=80 still gated the lint, and no test exercised the 40-79 band
    the two disagreed about. There is now ONE floor, MIN_DRAFT_BYTES, and this
    pins the band so the comment is checkable rather than merely true today."""

    def test_there_is_exactly_one_floor_and_it_is_mains(self):
        assert gate.MIN_TEXT_BYTES == 80, (
            "the port changed main's lint floor, so 40-79 byte framed messages "
            "are newly linted on 24 instances that were promised no change")
        assert not hasattr(gate, "MIN_DRAFT_BYTES"), (
            "two floors disagreed about the 40-79 band. One value only.")

    def _framed(self, body):
        return "Here's the post.\n\n```\n" + body + "\n```\n"

    def test_a_draft_in_the_40_to_79_band_is_not_graded(self, tmp_path):
        """The band the two floors disagreed about, pinned to main's answer.

        This asserted the OPPOSITE while the port ran a 40-byte floor. The port's
        job is to move a working gate into the skeleton without changing what 24
        instances experience, and grading a band main does not grade is a change.
        Lowering the floor is a real question (F9's shipped turn fell through it)
        and it belongs to whoever changes main, not to this port.
        """
        body = "the gate said nothing at all and the draft shipped anyway."
        assert 40 <= len(body.encode("utf-8")) < 80, len(body.encode("utf-8"))
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "write it", self._framed(body)),
                    tmp_path / "c.json")
        assert proc.returncode == 0, (
            "a 40-79 byte framed draft was graded; main does not grade it.\n"
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")

    def test_a_draft_over_the_floor_is_graded(self, tmp_path):
        """THE CONTROL. Without it, a floor of infinity would pass every
        assertion here and the lint would never run at all."""
        body = ("the gate said nothing at all and the draft shipped anyway, "
                "which is how the whole class of silent-pass defects begins.")
        assert len(body.encode("utf-8")) >= 80, len(body.encode("utf-8"))
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "write it", self._framed(body)),
                    tmp_path / "c.json")
        assert proc.returncode == 2, (
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")

    def test_a_draft_under_the_floor_is_not_graded(self, tmp_path):
        """The control. Without it, a floor of zero would pass the test above and
        the gate would fire on every one-line answer."""
        body = "too short to gate."
        assert len(body.encode("utf-8")) < 40, len(body.encode("utf-8"))
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "write it", self._framed(body)),
                    tmp_path / "c.json")
        assert proc.returncode == 0, (
            f"rc={proc.returncode} stderr={proc.stderr}")


class TestTheExtractionPipelineHasNoCycles:
    """Codex major, ASK-1197 round 10. `framed_draft` called `_route_draft`, which
    fell through to `extract_publishable`, which called `framed_draft`. Any
    assistant message carrying `=== ROUTE RECEIPT ===` with no `=== DRAFT ===`
    marker recursed until RecursionError -- and a Stop hook that raises exits 1,
    which the client treats as "hook errored, carry on". The gate failed OPEN in
    exactly the case it exists for.
    """

    RECEIPT_NO_DRAFT_MARKER = (
        "Here's the post for LinkedIn.\n\n"
        "=== ROUTE RECEIPT ===\n"
        '{"surface": "linkedin", "channel": "assaf", "attempt_id": "a1"}\n\n'
        "The body of the draft that follows the receipt with no draft marker.\n")

    def test_a_receipt_with_no_draft_marker_extracts(self):
        """RED on f07959d1 with RecursionError, not an assertion failure."""
        got = gate._route_draft(self.RECEIPT_NO_DRAFT_MARKER)
        assert got == (
            "The body of the draft that follows the receipt with no draft "
            "marker."), repr(got)

    def test_the_whole_turn_completes_for_that_shape(self, tmp_path):
        """End to end: the shape that used to exit 1 must not."""
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "write it",
                                      self.RECEIPT_NO_DRAFT_MARKER),
                    tmp_path / "c.json")
        assert proc.returncode != 1, (
            "exit 1 means the hook crashed, and the client carries on -- the turn "
            f"completes ungated.\nrc={proc.returncode} stderr={proc.stderr}")
        assert "RecursionError" not in proc.stderr, proc.stderr

    def test_the_extractors_form_a_directed_acyclic_graph(self):
        """The STRUCTURAL pin, not another example.

        A test per known-bad input only catches the cycles someone thought of.
        This reads the call graph out of the source: if any extractor ever calls
        another that reaches back, this fails and names the loop.
        """
        import ast
        source = pathlib.Path(gate.__file__).read_text(encoding="utf-8")
        names = {"framed_draft", "_route_draft", "extract_publishable",
                 "_publish_framed", "_setoff_segments", "_strip_lane_trailers",
                 "_after_receipt_block", "extract_setoff_draft"}
        edges = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                edges[node.name] = {
                    call.func.id for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name) and call.func.id in names}
        assert edges, "parsed no extractors; the test, not the gate, is broken"

        def walk(name, stack):
            assert name not in stack, (
                "the extraction pipeline has a cycle, which is a RecursionError "
                "on some input and exit 1 on the hook: "
                + " -> ".join(stack + [name]))
            for target in sorted(edges.get(name, ())):
                walk(target, stack + [name])

        for start in sorted(edges):
            walk(start, [])


class TestAnInternalFaultHoldsTheTurn:
    """The round 1 chokepoint rule, pinned for the WHOLE file.

    `_enforce_route_or_exit` already turned any exception into exit 2 for the
    route lane. Everything main() does before that -- reading the transcript,
    extracting the draft -- had no such guard, and round 9's recursion lived
    exactly there. Exit 1 does not hold the turn.
    """

    def test_a_crash_anywhere_in_main_exits_2_with_the_refusal_envelope(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=False)
        gate_path = root / "q-system" / ".q-system" / "scripts" / "voice-stop-gate.py"
        # Break a function main() calls BEFORE any enforcement, so the fault is
        # outside every existing try block.
        #
        # INSERTED, not appended. Appending put the override AFTER the
        # `if __name__ == "__main__"` block at the end of the file, so main() had
        # already run and exited on the real function and the test read exit 0 as
        # a failure of the guard. The harness was broken, not the gate.
        source = gate_path.read_text(encoding="utf-8")
        entry = 'if __name__ == "__main__":'
        assert entry in source, "gate has no main entry point to inject before"
        gate_path.write_text(
            source.replace(
                entry,
                "def find_final_assistant_text(_path):\n"
                "    raise RuntimeError('BOOM: injected fault')\n\n\n" + entry,
                1),
            encoding="utf-8")
        proc = _run(root, _transcript(tmp_path, "write it", "Here's the post.\n"),
                    tmp_path / "c.json")
        assert proc.returncode == 2, (
            "an internal fault exited %s. Exit 1 reads as 'hook errored, carry "
            "on' and the turn completes ungated.\nstderr=%s"
            % (proc.returncode, proc.stderr))
        assert gate._REFUSAL_MARK in proc.stderr, (
            "the fault did not go through refuse(), so the harness cannot tell "
            f"this refusal from ours on the way back.\n{proc.stderr}")
        assert "BOOM: injected fault" in proc.stderr, proc.stderr


class TestARoutedClarifyingQuestion:
    """Round 10 case 2, INVERTED in round 15. The deadlock is real and is not
    fixed here; it is matched to the installed gate rather than papered over."""

    def test_a_clarifying_question_under_a_routed_request_is_refused(self, tmp_path):
        """INVERTED in round 15. This asserted rc==0 and pinned the relaxation.

        Round 10 called this "the deadlock rounds 5 and 9 kept rebuilding" and
        exempted it. Measured 2026-09-02, consulting's INSTALLED gate refuses this
        shape, and this file syncs over that gate: the exemption was a regression,
        not a port. Separating a question from a draft needs a signal this gate
        does not have (extract_publishable returns "" for both; candidate_draft
        returns content for both), so the route path refuses both, as installed
        does. The producer marker is the accepted fix, sp-6ce17a23.
        """
        root = _instance(tmp_path, with_route_lane=True)
        question = ("Which subreddit is this for? The body band and the rules "
                    "differ enough that I would write it differently.\n")
        proc = _run(root, _transcript(tmp_path, "write me a reddit post", question),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            "a clarifying question completed under a routed request, so the route "
            f"path is relaxed relative to installed.\nrc={proc.returncode} "
            f"stderr={proc.stderr}")
class TestAMarkerInsideAFenceIsAQuote:
    """Codex major, ASK-1197 round 11. Round 10 let the lint key on a bare
    `=== DRAFT ===`, so an engineering message SHOWING that marker inside a code
    fence -- this file and its docs do it constantly -- was read as a delivery,
    voice-linted, and the Stop hook exited 2 where base exited 0."""

    QUOTED = (
        "The route lane recognises three wrappers. The X lane prints this:\n\n"
        "```\n"
        "=== DRAFT ===\n"
        "the post body goes here\n"
        "```\n\n"
        "and the reddit lane prints its own instead.\n")

    def test_a_marker_inside_a_fence_frames_nothing(self):
        assert gate.extract_publishable(self.QUOTED) == "", (
            "a marker quoted inside a fence was treated as framing, so an "
            "engineering answer got voice-linted")
        assert gate._route_draft(self.QUOTED) == "", gate._route_draft(self.QUOTED)

    def test_the_turn_completes(self, tmp_path):
        """End to end, no routed request: base exited 0 here and so must this."""
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "how does the route lane work?",
                                      self.QUOTED), tmp_path / "c.json")
        assert proc.returncode == 0, (
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")

    def test_the_same_marker_outside_a_fence_still_frames(self):
        """THE CONTROL. Masking fences must not stop real handoffs from framing;
        without this, masking everything would pass the test above."""
        real = ("Here's the post for LinkedIn.\n\n=== DRAFT ===\n"
                "The body of a real handoff, long enough to be measured.\n")
        assert gate._route_draft(real) == (
            "The body of a real handoff, long enough to be measured.")

    def test_a_receipt_marker_inside_a_fence_claims_nothing(self):
        quoted = ("The producer emits this shape:\n\n```\n"
                  "=== ROUTE RECEIPT ===\n{\"surface\": \"linkedin\"}\n```\n")
        assert gate._route_draft(quoted) == ""


class TestAPastedTokenCannotDisableTheGate:
    """Codex major, ASK-1197 round 11. `_is_own_refusal_echo` was a substring
    test, so a framed routed draft that ALSO pasted
    `[voice-stop-gate:held-this-turn]` skipped both the voice lint and receipt
    verification and exited 0 with a notice that falsely said no draft was
    present. A token anyone can copy must never switch a gate off."""

    PASTED = ("Here's the post for LinkedIn.\n\n=== DRAFT ===\n"
              "[voice-stop-gate:held-this-turn]\n"
              "The body of the draft, long enough to be measured, pasted next to "
              "the refusal token so the gate would look away.\n")

    def test_a_framed_draft_with_the_token_is_still_a_draft_to_the_ROUTE(self):
        """ASK-1197 round 13 splits what this used to assert as one thing.

        The route path must still see a draft: that is the round 10 bypass and it
        stays closed at any length (ECHO_NEVER_EXEMPTS_ROUTE).

        The LINT half is now deliberately the opposite. The voice lint never
        grades this gate's own refusal, framed or not (ECHO_LINT_EXEMPT), because
        round 12 made the echo test unreachable under framing and the gate started
        voice-linting its own quoted refusal and holding the turn. Here the mark
        sits INSIDE the slab, so the slab is exempt; the residual is sp-98247c8e
        and the route still verifies this turn.
        """
        assert gate._output_carries_draft(self.PASTED), (
            "pasting the refusal token next to a framed draft disabled the route "
            "predicate")
        assert gate.extract_publishable(self.PASTED) == "", (
            "the lint graded a slab that carries this gate's own refusal")

    def test_a_framed_draft_with_the_token_is_still_refused(self, tmp_path):
        """End to end with the lane installed and the request routed: no receipt,
        so the turn must be HELD. Round 10 exited 0 here."""
        root = _instance(tmp_path, with_route_lane=True)
        proc = _run(root, _transcript(tmp_path, "write me a linkedin post",
                                      self.PASTED),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            "a routed draft skipped verification because it pasted the refusal "
            f"token.\nrc={proc.returncode} stdout={proc.stdout}")

    def test_a_pure_refusal_echo_is_also_refused(self, tmp_path):
        """INVERTED in round 15. This was the control for the round 7 deadlock:
        an assistant REPORTING a refusal, with no draft, completing.

        It no longer holds, and that is deliberate. Installed refuses a pure echo
        too (measured 2026-09-02), so the exemption made this file weaker than the
        gate it replaces. The round 10/11 bypass this class exists for -- a pasted
        token beside a framed draft -- stays closed either way, and the two tests
        above are the ones that prove it.
        """
        root = _instance(tmp_path, with_route_lane=True)
        report = ("The gate held the turn. It reported:\n\n"
                  "voice-stop-gate: routed completion has no route receipt\n"
                  + gate._REFUSAL_MARK + "\n\nI have not re-drafted anything.\n")
        proc = _run(root, _transcript(tmp_path, "write me a linkedin post", report),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            "a pure refusal echo completed, so the echo exemption is back. "
            f"rc={proc.returncode} stderr={proc.stderr}")
class TestPublishFramingWinsOverATrailingMarker:
    """Codex minor, ASK-1197 round 11. `framed_draft` preferred `_route_draft`,
    so a trailing bare `=== DRAFT ===` line truncated a slab the publish sentence
    had already claimed, and content the base version blocked started passing."""

    #: THE TAIL AFTER THE MARKER IS LOAD-BEARING, and the first version of this
    #: fixture omitted it and proved nothing: with nothing after the marker
    #: `_route_draft` returns "" and the `or` falls through to publish framing on
    #: BOTH versions, so the test passed against unfixed code. The M3 mutant
    #: survived and said so. Measured against f7bb54d0: with the tail, base
    #: returns "See above." and the announced slab is never graded.
    TRAILING = ("Here's the post for LinkedIn.\n\n"
                "```\n"
                "the gate said nothing at all and the draft shipped anyway, "
                "which is how the whole class of silent-pass defects begins.\n"
                "```\n\n"
                "=== DRAFT ===\n"
                "See above.\n")

    def test_the_announced_slab_is_not_truncated(self):
        draft = gate.extract_publishable(self.TRAILING)
        assert draft != "See above.", (
            "the trailing marker won and the announced slab was discarded; that "
            "is the base behaviour this fixture must distinguish")
        assert "the gate said nothing at all" in draft, (
            "a trailing marker shrank the slab the publish sentence claimed, so "
            f"the announced content was never graded. got {draft!r}")

    def test_the_content_is_still_blocked(self, tmp_path):
        """End to end: this body has a lowercase sentence start, which base
        blocked. It must still be blocked."""
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "write it", self.TRAILING),
                    tmp_path / "c.json")
        assert proc.returncode == 2, (
            "content the base version blocked now passes because a trailing "
            f"marker truncated the slab.\nrc={proc.returncode} stdout={proc.stdout}")


class TestAShortDraftBesideAPastedToken:
    """Codex major, ASK-1197 round 12. The echo test used to run BESIDE a draft
    and compare sizes, so a framed draft SHORTER than the quoted refusal envelope
    disabled both the voice lint and receipt verification. Length is not a
    licence. Framing is decided first now and the echo question is only asked when
    nothing was framed, so there is no size left to game."""

    #: 30 bytes of real draft, deliberately far shorter than the envelope pasted
    #: under it. Under the round 11 dominance rule this classified as an echo.
    SHORT = 30

    def _message(self, mark):
        body = "The gate stayed silent again."
        assert len(body.encode("utf-8")) < 40, len(body.encode("utf-8"))
        return ("Here's the post for LinkedIn.\n\n"
                "```\n" + body + "\n```\n\n"
                "voice-stop-gate: routed completion has no route receipt\n"
                + mark + "\n")

    def test_a_short_framed_draft_is_still_a_draft(self):
        assert gate.classify_output(self._message(gate._REFUSAL_MARK)) == (
            gate.OUTPUT_DRAFT), (
            "a framed draft shorter than the pasted envelope was classified as "
            "an echo, which switches off the lint and receipt verification")

    def test_it_is_still_refused_without_a_receipt(self, tmp_path):
        """End to end, lane installed, request routed. rc 2 on f7bb54d0's
        successor was rc 0."""
        root = _instance(tmp_path, with_route_lane=True)
        proc = _run(root, _transcript(tmp_path, "write me a linkedin post",
                                      self._message(gate._REFUSAL_MARK)),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            "a routed draft skipped verification because a refusal token was "
            f"pasted under it.\nrc={proc.returncode} stdout={proc.stdout}")

    def test_the_same_message_without_the_token_behaves_identically(self, tmp_path):
        """THE CONTROL. The token must make NO difference at all now; if removing
        it changed the outcome, the token would still be doing something."""
        root = _instance(tmp_path, with_route_lane=True)
        without = self._message("").replace(
            "voice-stop-gate: routed completion has no route receipt\n", "")
        proc = _run(root, _transcript(tmp_path, "write me a linkedin post", without),
                    tmp_path / "c.json", classify="route")
        assert proc.returncode == 2, (
            f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")


class TestEachPathNamesWhatItSaw:
    """Round 12 split the echo notice from the no-draft notice so neither could
    misstate what the gate saw. Round 15 removed BOTH: the route path no longer
    emits a notice for an unframed completion, it refuses. Those two tests went
    with the notices they asserted.

    The lane-absent NOT CHECKED notice is untouched and is the only one left, so
    it keeps its test -- and that test now also proves the removal did not take
    the surviving notice with it."""

    def test_the_lane_absent_path_still_says_not_checked(self, tmp_path):
        """The third notice, unchanged, asserted here so the split did not
        quietly collapse it into one of the other two."""
        root = _instance(tmp_path, with_route_lane=False)
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        proc = _run(root, _transcript(tmp_path, "write it",
                                      _producer_message(receipt, "The body")),
                    tmp_path / "c.json")
        assert proc.returncode == 0, proc.stderr
        message = _system_message(proc)
        assert "NOT CHECKED" in message, message
        assert "refusal echo" not in message and "no draft found" not in message


class TestThePublishMarkerWordBoundary:
    """ASK-1197 round 12, a latent false positive older than this PR.

    `\\bdraft(ed|ing)?\\s+(the|a|your|my|for|below|:)` had no boundary after the
    article, so it matched "drafted a" inside "I have not re-drafted ANYthing
    yet" -- an assistant REPORTING a refusal read as announcing a delivery. That
    false framing is what made the echo test look like it had to run beside a
    draft, which is the hole this round closes.
    """

    def test_re_drafted_anything_is_not_publish_framing(self):
        assert not gate._PUBLISH_MARKER_RE.search(
            "I have not re-drafted anything yet."), (
            "the article alternation matched mid-word")

    def test_a_real_announcement_still_matches(self):
        """THE CONTROL. Adding the boundary must not stop real framing; without
        this, deleting the whole alternative would pass the test above.

        `"drafted: see below"` is deliberately NOT in this list: the pattern
        requires whitespace before the colon, so neither the old nor the new
        regex ever matched it. I had it here first and the control went red
        against correct code, which is the useful kind of red. Captured as
        sp-c439a470 rather than widened here.
        """
        for announced in ("I drafted a post for you.",
                          "I drafted the reply below.",
                          "I am drafting your LinkedIn post now."):
            assert gate._PUBLISH_MARKER_RE.search(announced), announced

    def test_the_boundary_changes_exactly_one_thing(self):
        """MINIMALITY, asserted rather than asserted-to. A regex edit is easy to
        over-shoot, so this pins the old pattern beside the new one and requires
        the ONLY divergence to be the false positive under repair."""
        import re
        old = re.compile(r"(?im)\bdraft(ed|ing)?\s+(the|a|your|my|for|below|:)")
        corpus = [
            "I drafted a post for you.",
            "I drafted the reply below.",
            "drafting my LinkedIn post",
            "drafted for reddit",
            "drafted : see below",
            "drafted: see below",
            "nothing about drafts here",
            "I have not re-drafted anything yet.",     # the false positive
        ]
        diverged = [t for t in corpus
                    if bool(old.search(t))
                    != bool(gate._PUBLISH_MARKER_RE.search(t))]
        assert diverged == ["I have not re-drafted anything yet."], diverged


class TestLaneMarkersAreRouteFramingNotPublishFraming:
    """Codex major, ASK-1197 round 13. Round 12 let `extract_publishable` read
    LANE markers, so on the 24 registered instances with no `q-consult` pipeline,
    pasting a producer's output got voice-linted and BLOCKED the turn where main
    exits 0. Lane markers mean "a producer emitted this", which is the route
    path's question."""

    #: A producer handoff: receipt block plus the reddit wrapper, no publish
    #: sentence and no `=== DRAFT ===`. Shaped like the captured fixture above.
    PASTED_PRODUCER = (
        "=== ROUTE RECEIPT ===\n"
        '{"surface": "reddit-post", "channel": "reddit", "attempt_id": "a1"}\n\n'
        "=== REDDIT DRAFT (ATTENDED, PUBLISHES NOTHING) ===\n"
        "TITLE: the gate that passed because it had nothing to look at\n\n"
        "we shipped a check that inspected zero files and went green anyway.\n\n"
        "FOUNDER REVIEW REQUIRED: subreddit rules, and the six checks above are "
        "flags, not passes.\n")

    def test_a_pasted_producer_output_is_not_publishable(self):
        assert gate.extract_publishable(self.PASTED_PRODUCER) == "", (
            "a lane marker was read as publish framing, so pasting producer "
            "output gets voice-linted on instances that have no route lane")

    def test_a_lane_less_instance_does_not_block_on_it(self, tmp_path):
        """The 24-instance regression, end to end. The body is deliberately
        lowercase, so a lint that ran at all would refuse it."""
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "what does the producer emit?",
                                      self.PASTED_PRODUCER), tmp_path / "c.json")
        assert proc.returncode == 0, (
            "a lane-less instance blocked the turn on pasted producer output; "
            f"main exits 0 here.\nrc={proc.returncode} stderr={proc.stderr}")

    def test_the_route_path_still_reads_lane_markers(self):
        """THE CONTROL. Narrowing the LINT must not narrow the ROUTE; without
        this, dropping lane markers everywhere would pass the tests above and
        silently stop verifying every producer handoff."""
        assert gate.classify_output(self.PASTED_PRODUCER) == gate.OUTPUT_DRAFT
        assert gate._route_draft(self.PASTED_PRODUCER), "the lane slab vanished"

    def test_a_draft_marker_is_still_publish_framing(self):
        """`=== DRAFT ===` is the separator the ASSISTANT writes, not a producer
        artifact, so the lint still reads it."""
        assert gate.extract_publishable(
            "=== DRAFT ===\nThe body of a draft, long enough to be measured.\n")


class TestTheLintNeverGradesItsOwnRefusal:
    """Codex minor, ASK-1197 round 13. Round 12 made the echo test unreachable
    whenever framing was present, so an assistant quoting the gate's refusal
    inside a framed message got that refusal VOICE-LINTED and the turn was held
    again -- the deadlock, arriving through the lint instead of the route lane."""

    FRAMED_ECHO = (
        "Here's the post for LinkedIn, or rather here is why there isn't one.\n\n"
        "voice-stop-gate: routed completion has no route receipt\n"
        + "[voice-stop-gate:held-this-turn]" + "\n")

    def test_a_framed_quoted_refusal_is_not_linted(self):
        assert gate.extract_publishable(self.FRAMED_ECHO) == "", (
            "the lint graded this gate's own refusal because the message "
            "happened to carry publish framing")

    def test_the_turn_completes(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "what happened?", self.FRAMED_ECHO),
                    tmp_path / "c.json")
        assert proc.returncode == 0, (
            f"rc={proc.returncode} stderr={proc.stderr}")

    def test_a_token_in_surrounding_chat_does_not_exempt_a_fenced_draft(self):
        """The narrowing, asserted. Evaluating the echo on the SLAB rather than
        the whole message means a real fenced draft is still graded even when the
        token appears in the chat around it."""
        message = ("Here's the post for LinkedIn. The gate said "
                   "[voice-stop-gate:held-this-turn] last time.\n\n"
                   "```\nthe body of a real draft that must still be graded.\n```\n")
        draft = gate.extract_publishable(message)
        assert draft and "voice-stop-gate" not in draft, draft


class TestAFencedFormatExampleIsNotAClaimedReceipt:
    """Codex minor, ASK-1197 round 13. The uninstalled-lane receipt-claim check
    was the one marker read still scanning raw text, so an assistant SHOWING what
    a receipt block looks like emitted a false NOT CHECKED on the 24 lane-less
    instances -- a per-turn line on instances that were never asked to check
    anything, which is how a gate gets switched off."""

    FENCED_EXAMPLE = (
        "The producer emits this before the draft:\n\n"
        "```\n"
        "=== ROUTE RECEIPT ===\n"
        '{"attempt_id": "...", "surface": "linkedin", "channel": "assaf"}\n'
        "```\n\n"
        "and the gate consumes it once.\n")

    def test_no_false_not_checked_on_a_lane_less_instance(self, tmp_path):
        root = _instance(tmp_path, with_route_lane=False)
        proc = _run(root, _transcript(tmp_path, "explain the receipt block",
                                      self.FENCED_EXAMPLE), tmp_path / "c.json")
        assert proc.returncode == 0, proc.stderr
        assert "NOT CHECKED" not in proc.stdout + proc.stderr, (
            "a fenced format example was read as a claimed receipt.\n"
            f"stdout={proc.stdout!r}")

    def test_a_real_receipt_block_still_reports_not_checked(self, tmp_path):
        """THE CONTROL. Masking must not silence the warning this branch exists
        to print; without this, masking everything would pass the test above."""
        root = _instance(tmp_path, with_route_lane=False)
        receipt = {name: "x" for name in STUB_MATCH_FIELDS}
        proc = _run(root, _transcript(tmp_path, "write it",
                                      _producer_message(receipt, "The body")),
                    tmp_path / "c.json")
        assert proc.returncode == 0, proc.stderr
        assert "NOT CHECKED" in _system_message(proc)


def test_every_marker_read_is_fence_masked():
    """One masking helper, every marker read, no exceptions (round 13, finding 2).

    DERIVED, NOT TYPED. The framing regexes are found by asking each compiled
    pattern in the module whether it matches a real marker or a real publish
    sentence, and the call sites are found by walking the AST. A new marker regex
    or a new call site is covered the day it is written, which a hand-kept list
    would not be -- and a hand-kept list is how the receipt-claim check sat
    unmasked through three rounds.
    """
    import ast
    import re as _re

    probes = [gate.ROUTE_RECEIPT_MARKER, gate.ROUTE_REDDIT_DRAFT_MARKER,
              gate.ROUTE_DRAFT_MARKER, "Here's the post."]
    framing = {name for name, value in vars(gate).items()
               if isinstance(value, _re.Pattern)
               and any(value.search(probe) for probe in probes)}
    assert len(framing) >= 4, (
        f"derived only {sorted(framing)}; the probe set no longer finds the "
        "framing regexes, so this test is measuring nothing")

    source = pathlib.Path(gate.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = {a.arg for a in func.args.args}
        # A function handed an already-extracted slab has no full message to mask;
        # fences upstream were resolved before it was called.
        if "slab" in params:
            continue
        # TRANSITIVE, because masked text does not stay in the variable it was
        # first bound to. `markers = _PUBLISH_MARKER_RE.finditer(masked)` then
        # `marker.group(0)`, or `chunk = _sentence_at(masked, ...)`, are both
        # reading masked bytes. The first version of this check accepted only a
        # literal `_mask_fences(...)` argument and flagged those two as
        # offenders -- a false positive against correct code, which is the kind
        # of red that makes a gate get switched off.
        masked_locals = set()
        for _ in range(6):          # fixpoint; the chains here are 2-3 deep
            before = len(masked_locals)
            for stmt in ast.walk(func):
                targets = []
                if isinstance(stmt, ast.Assign):
                    targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
                    value = stmt.value
                elif isinstance(stmt, ast.For) and isinstance(stmt.target, ast.Name):
                    targets, value = [stmt.target], stmt.iter
                else:
                    continue
                if not targets:
                    continue
                derived = any(
                    (isinstance(n, ast.Name)
                     and (n.id in masked_locals or n.id == "_mask_fences"))
                    or (isinstance(n, ast.Attribute) and n.attr == "_mask_fences")
                    for n in ast.walk(value))
                if derived:
                    masked_locals.update(t.id for t in targets)
            if len(masked_locals) == before:
                break

        for call in ast.walk(func):
            if not (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"search", "match", "finditer", "findall"}
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in framing
                    and call.args):
                continue
            arg = call.args[0]
            ok = ((isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                   and arg.func.id == "_mask_fences")
                  or (isinstance(arg, ast.Name) and arg.id in masked_locals)
                  # `marker.group(0)` where `marker` came from a masked scan
                  or (isinstance(arg, ast.Call)
                      and isinstance(arg.func, ast.Attribute)
                      and arg.func.attr in {"group", "groups"}
                      and isinstance(arg.func.value, ast.Name)
                      and arg.func.value.id in masked_locals))
            if not ok:
                offenders.append(f"{func.name}: {call.func.value.id}."
                                 f"{call.func.attr}(...) reads unmasked text")
    assert not offenders, (
        "a marker regex read text that was not fence-masked, so a fenced example "
        "of that marker frames a delivery:\n  " + "\n  ".join(offenders))


class TestASystemExitInsideTheVerifierCannotClearTheTurn:
    """Codex minor, ASK-1197 round 3.

    `_enforce_route_or_exit` caught `Exception`. `SystemExit` inherits
    `BaseException`, so that arm could not see it. A SystemExit raised inside
    `enforce_route_receipt` went straight through the fail-closed handler to
    the top-level `except SystemExit: raise` and exited carrying its own code.
    A SystemExit(0) there exits the hook 0 with a routed draft nothing verified.

    Both directions are pinned here because only one of them can regress
    silently: the code-2 case looks identical whether or not the arm exists, so
    the test that catches a bad fix is the code-0 one, and the test that catches
    an OVER-broad fix (swallowing a real refusal) is the code-2 one.
    """

    def _classifier_raising(self, root, code):
        classifier = root / "q-consult" / "pipeline" / "route_classifier.py"
        classifier.write_text(
            "NOT_ROUTED = 'not_routed'\nROUTE = 'route'\n"
            "def classify(request):\n"
            "    raise SystemExit(%s)\n" % (code,),
            encoding="utf-8")

    def test_a_systemexit_0_inside_the_verifier_becomes_a_refusal(self, tmp_path):
        """The fail-OPEN this arm exists to close. Without it the gate exits 0
        and the routed draft ships unverified."""
        root = _instance(tmp_path, with_route_lane=True)
        self._classifier_raising(root, 0)
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log)
        assert proc.returncode == 2, (
            "a verifier that exited 0 without rendering a verdict has not cleared "
            "this draft, so the turn must be HELD. Exit 0 here is the gate failing "
            f"open. rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}")
        assert "exited unexpectedly with code 0" in proc.stderr, (
            "the turn was held but the reason was swallowed; a fail-closed with no "
            "diagnosis is unfixable.\n" + proc.stderr)

    def test_a_systemexit_2_inside_the_verifier_propagates_unchanged(self, tmp_path):
        """Code 2 is `refuse()` doing its job. Re-wrapping it would replace a real
        refusal's message with the generic one, so the operator reads the wrong
        reason for the hold."""
        root = _instance(tmp_path, with_route_lane=True)
        self._classifier_raising(root, 2)
        log = tmp_path / "calls.json"
        assistant = "Here's the post for LinkedIn.\n\n" + DRAFT_MARKER + "\nbody\n"
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log)
        assert proc.returncode == 2, (
            f"a refusal must stay a refusal. rc={proc.returncode} "
            f"stdout={proc.stdout} stderr={proc.stderr}")
        assert "exited unexpectedly" not in proc.stderr, (
            "an exit-2 refusal was re-wrapped by the SystemExit arm, so the real "
            "refusal message was replaced by the generic one.\n" + proc.stderr)
