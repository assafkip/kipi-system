"""The skeleton Stop-gate lets a routed turn REPORT a refusal (ASK-1744, ASK-1865).

THE DEADLOCK, measured 2026-09-15 in the one instance that runs a route lane. The
producer refused three LinkedIn reply runs at reply-length and printed its reason plus
a `refused` route receipt. `_verify_route_receipt` understood ONE status, `complete`,
so it hashed the turn as if it carried a draft, found no draft, and held the turn with
"route receipt does not match the assistant output". The session could not deliver the
verdict it had just produced, and every following turn hit the same wall.

WHY THIS LIVES IN THE SKELETON. The instance fixed it in its own `q-system/` subtree
copy, which is a `kipi update` rsync destination with a delete flag: the next fleet
fan-out would have deleted both functions off the founder's machine. This is the same
regression loop the route-receipt family already went through twice in one afternoon
(sp-745f5962, sp-1ad08728). Port the missing side, never exempt it.

THE 24-INSTANCE CLAIM, which outranks the feature. An instance whose lane never mints
a `refused` receipt must behave exactly as it did before this branch existed, and an
instance whose lane is OLDER than the contract method must HOLD the turn rather than
crash the hook open. Both are pinned below, because a skeleton change that breaks 24
instances to serve one is not a feature.

The contract is duck-typed here on purpose: the gate receives the instance's
`route_contract` module as a parameter and the skeleton has no route lane of its own,
so a stub is the only honest stand-in. It loads the RUNNING gate by path rather than a
vendored duplicate (wiring-check.md, load-path proof).
"""

import hashlib
import importlib.util
import json
import os

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GATE = os.path.join(REPO, "q-system", ".q-system", "scripts", "voice-stop-gate.py")

SURFACE, CHANNEL = "social-reply", "linkedin"
REQUEST = "reply to that dashboard post"
REASON = "300 words, above the 200-word ceiling"
MATCH_FIELDS = ("surface", "channel", "session_id", "request_hash", "output_hash")


def _load():
    spec = importlib.util.spec_from_file_location("voice_stop_gate_refusal", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load()


def _hash(value, surface, channel):
    return hashlib.sha256(f"{surface}\x1f{channel}\x1f{value}".encode()).hexdigest()


class _Receipts:
    MATCH_FIELDS = MATCH_FIELDS


class _Contract:
    """The slice of an instance `route_contract` module this gate path touches."""

    route_receipts = _Receipts()

    def __init__(self):
        self.consumed = []
        self.refusals = []

    request_hash = staticmethod(_hash)
    output_hash = staticmethod(_hash)

    def verify_and_consume(self, identity, draft=None):
        self.consumed.append(identity)
        return {"status": "consumed"}

    def verify_and_consume_refusal(self, identity):
        self.refusals.append(identity)
        return {"status": "refusal-consumed"}


class _ContractWithoutRefusal:
    """Same, minus the method a pre-ASK-1744 lane never had."""

    route_receipts = _Receipts()
    request_hash = staticmethod(_hash)
    output_hash = staticmethod(_hash)

    def verify_and_consume(self, identity, draft=None):
        return {"status": "consumed"}


class _Result:
    status = "ROUTE"
    surface, channel = SURFACE, CHANNEL
    reason = ""


class _Classifier:
    NOT_ROUTED = "NOT_ROUTED"
    ROUTE = "ROUTE"

    @staticmethod
    def classify(request):
        return _Result()


class _RegistryError(Exception):
    pass


class _Registry:
    RouteRegistryError = _RegistryError

    @staticmethod
    def resolve(surface, channel):
        return {"owner": "amber"}


class _AuditOnly:
    class AuditOnlyRouteError(Exception):
        pass

    @staticmethod
    def routes():
        return []


def _receipt(status, body, *, request=REQUEST):
    row = {
        "surface": SURFACE,
        "channel": CHANNEL,
        "session_id": "s1",
        "request_hash": _hash(request, SURFACE, CHANNEL),
        "output_hash": _hash(body, SURFACE, CHANNEL),
    }
    if status is not None:
        row["status"] = status
    return row


def _turn(reason=REASON, receipt=None, extra=""):
    body = f"I got no draft.\n\n=== WHY THERE IS NO DRAFT ===\n{reason}\n"
    if extra:
        body += "\n" + extra + "\n"
    if receipt is not None:
        body += "\n=== ROUTE RECEIPT ===\n" + json.dumps(receipt, sort_keys=True)
    return body


#: A COMPLETE turn, drafted inside a prose fence rather than under a `=== DRAFT ===`
#: marker. Both shapes are real and the gate reads both, but the marker form makes a
#: fixture circular: `_route_draft` returns everything after the marker, which includes
#: the receipt block, whose own `output_hash` field is the thing being computed. The
#: fence form is extracted by `extract_publishable`, which takes the fence body only.
def _complete_turn(draft, row):
    return (f"Here's the LinkedIn post.\n\n```\n{draft}\n```\n"
            f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}")


def _identity(row):
    return {key: row[key] for key in MATCH_FIELDS}


def _context(contract):
    return (_Classifier(), contract, _AuditOnly(), _Registry())


# --------------------------------------------------- the reason comes out of the turn ----

class TestTheRefusalTurnCompletes:
    def test_the_reason_is_read_back_out_of_the_turn(self):
        assert gate._refusal_text(_turn()) == REASON

    def test_a_turn_with_no_refusal_marker_has_no_reason(self):
        assert gate._refusal_text("just chatting about the weather") is None

    def test_the_receipt_block_is_not_part_of_the_reason(self):
        """The receipt is printed AFTER the reason, so a naive split would hash the
        JSON into it and every refusal would mismatch."""
        assert gate._refusal_text(_turn(receipt=_receipt("refused", REASON))) == REASON

    def test_a_matching_refusal_receipt_is_spent(self):
        contract = _Contract()
        row = _receipt("refused", REASON)
        spent = gate._consume_refusal(contract, row, _identity(row), _turn(), _Result())
        assert spent["status"] == "refusal-consumed"
        assert contract.refusals == [_identity(row)]


# ----------------------------------------------------------------- the controls ----

class TestWhatARefusalMayNotDo:
    """A refusal receipt is cheaper to mint than a complete one, so the gate has to
    make sure it can never be used to ship anything."""

    def test_a_turn_carrying_a_draft_is_refused(self):
        row = _receipt("refused", REASON)
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._consume_refusal(_Contract(), row, _identity(row),
                                  _turn(extra="=== DRAFT ===\nhere is the post"),
                                  _Result())

    def test_a_turn_with_an_inline_publishable_body_is_refused(self):
        row = _receipt("refused", REASON)
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._consume_refusal(
                _Contract(), row, _identity(row),
                _turn(extra="Here's the LinkedIn post: nobody reads the dashboard."),
                _Result())

    def test_a_reason_that_does_not_match_the_receipt_is_refused(self):
        """The mutation that matters: the receipt binds ONE reason, so a turn cannot
        mint a refusal for a hard verdict and report a friendlier one."""
        row = _receipt("refused", REASON)
        with pytest.raises(gate.RouteBoundaryError, match="stated reason"):
            gate._consume_refusal(_Contract(), row, _identity(row),
                                  _turn(reason="it just needed a tweak"), _Result())

    def test_a_turn_with_no_refusal_text_is_refused(self):
        row = _receipt("refused", REASON)
        with pytest.raises(gate.RouteBoundaryError, match="refusal text"):
            gate._consume_refusal(_Contract(), row, _identity(row),
                                  "no draft survived", _Result())


# ------------------------------------------------------------ the wiring, end to end ----

class TestTheRefusedBranchIsReached:
    """Delete the call site in `_verify_route_receipt` and these go red. The unit
    tests above pass against two functions nothing calls, which reads exactly like a
    working feature."""

    def test_a_refused_receipt_routes_to_the_refusal_path(self):
        contract = _Contract()
        row = _receipt("refused", REASON)
        spent = gate._verify_route_receipt(_context(contract), REQUEST,
                                           _turn(receipt=row))
        assert spent["status"] == "refusal-consumed"
        assert contract.consumed == [], "a refusal must not spend a complete receipt"

    def test_a_refused_receipt_carrying_a_draft_still_holds_the_turn(self):
        row = _receipt("refused", REASON)
        turn = _turn(receipt=row, extra="=== DRAFT ===\nhere is the post")
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._verify_route_receipt(_context(_Contract()), REQUEST, turn)


class TestTheLanesThatDoNotUseThis:
    """24 of 26 instances have no route lane at all and never reach this file. Of the
    rest, a lane that never mints a refusal must be untouched, and a lane older than
    the contract method must HOLD rather than fail the hook open."""

    def test_a_complete_receipt_is_unchanged(self):
        contract = _Contract()
        draft = "nobody reads the dashboard"
        row = _receipt("complete", draft)
        spent = gate._verify_route_receipt(_context(contract), REQUEST,
                                           _complete_turn(draft, row))
        assert spent["status"] == "consumed"
        assert contract.refusals == [], "a complete receipt must not spend a refusal"

    def test_a_receipt_with_no_status_field_is_unchanged(self):
        """The pre-ASK-1744 receipt shape carries no `status` key at all."""
        contract = _Contract()
        draft = "nobody reads the dashboard"
        row = _receipt(None, draft)
        assert gate._verify_route_receipt(_context(contract), REQUEST,
                                          _complete_turn(draft, row))[
                                              "status"] == "consumed"

    def test_a_lane_without_the_contract_method_holds_the_turn(self):
        """Fail CLOSED. An AttributeError escaping here would exit the Stop hook 1,
        which Claude Code treats as non-blocking, so the routed turn would complete
        with no receipt spent at all."""
        row = _receipt("refused", REASON)
        with pytest.raises(gate.RouteBoundaryError, match="was not accepted"):
            gate._verify_route_receipt(_context(_ContractWithoutRefusal()), REQUEST,
                                       _turn(receipt=row))
