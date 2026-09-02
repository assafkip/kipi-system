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
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

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
                        "output_hash": _stub_hash("oh:", "the body of the draft")})
        assistant = _producer_message(receipt, "the body of the draft")
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
        assert calls[0]["draft"] == "the body of the draft", (
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
        assistant = "Here's the post for LinkedIn.\n\nfine ordinary prose.\n"
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
        assistant = _producer_message(receipt, "the body of the draft")
        proc = _run(root, _transcript(tmp_path, "write it", assistant), log)
        assert proc.returncode == 0, (
            "an instance with no route lane must not block on a receipt it cannot "
            f"verify. rc={proc.returncode} stderr={proc.stderr}")
        assert "NOT CHECKED" in proc.stdout, (
            "a turn carrying a route receipt on an instance with no verifier "
            "passed with no NOT CHECKED line. That is indistinguishable from a "
            "verified receipt, which is the whole defect.\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")


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

    def test_a_meta_flagged_record_is_skipped_by_the_walker(self, tmp_path):
        """The label, not the prose. Enumerating carriers in a regex is the shape
        that failed twice; `isMeta` is what the harness already tells us."""
        path = tmp_path / "t.jsonl"
        path.write_text("\n".join([
            json.dumps({"message": {"role": "user", "content": [
                {"type": "text", "text": "the real request"}]}}),
            json.dumps({"isMeta": True, "turnCompanion": True,
                        "message": {"role": "user", "content": [
                            {"type": "text", "text": "a skill body with no tags at all"}]}}),
        ]) + "\n", encoding="utf-8")
        assert gate.find_final_user_text(str(path)) == "the real request", (
            "the newest `user` record won even though the harness flagged it as its "
            "own injection. That is the third-occurrence deadlock.")
