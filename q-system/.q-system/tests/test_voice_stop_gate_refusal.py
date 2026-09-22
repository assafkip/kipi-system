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

    def test_an_inline_unfenced_body_is_NOT_caught_and_that_is_measured(self):
        """THE KNOWN LIMIT, written down rather than left as a surprise.

        An inline draft with no fence and no blockquote passes. This test asserted the
        opposite until PR #375 review, when the guard stopped using
        `extract_publishable`: that function falls back to the whole message once any
        publish framing appears, and a refusal reason naming a platform IS framing, so
        it held 4 of 6 real refusal wordings. Catching this shape again means bringing
        that fallback back, which re-creates the deadlock the file exists to end.

        This is not a carve-out invented here. `reply_carries_a_draft`, which `main()`
        asks the same question, does not treat an inline sentence as a draft either, so
        the refusal path is exactly as strong as the path beside it and no weaker.
        Captured as sp-5262a341 / ASK-1889; the fix is a set-off-independent draft
        detector shared with `reply_carries_a_draft`, which is its own piece of work
        and not a side effect of this port.
        """
        inline = "Here's the LinkedIn post: nobody reads the dashboard."
        assert bool(gate.extract_setoff_draft(inline)) is False
        assert gate.reply_carries_a_draft(inline) is False, (
            "if this flips, main()'s own detector caught it and this guard should too")
        row = _receipt("refused", REASON)
        spent = gate._consume_refusal(_Contract(), row, _identity(row),
                                      _turn(extra=inline), _Result())
        assert spent["status"] == "refusal-consumed"

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

#: The six plausible refusal wordings the PR #375 reviewer measured. Four of them
#: named a platform, tripped `extract_publishable`'s whole-message fallback, and were
#: held as carrying a draft they did not carry, which is the deadlock this whole file
#: exists to end. These are NEGATIVE CONTROLS: every one must PASS.
PLATFORM_REASONS = [
    "300 words, above the 200-word ceiling",
    "the draft for this reply ran 300 words, over the ceiling",
    "drafting the comment hit the corpus-similarity floor",
    "no source in the corpus supports the claim, so there is no reply to X",
    "the reply ran long for LinkedIn",
    "the poster's claims were not extracted, so I am not writing the comment",
]


class TestARefusalIsNotADraft:
    """The over-fire controls. Every test in `TestWhatARefusalMayNotDo` proves the
    guard FIRES; without these, nothing proves it stays quiet on a real refusal, and a
    guard that holds every refusal looks identical to one that works (PR #375 major 1).
    """

    @pytest.mark.parametrize("reason", PLATFORM_REASONS)
    def test_a_refusal_reason_that_names_a_platform_still_passes(self, reason):
        contract = _Contract()
        row = _receipt("refused", reason)
        spent = gate._verify_route_receipt(_context(contract), REQUEST,
                                           _turn(reason=reason, receipt=row))
        assert spent["status"] == "refusal-consumed"

    def test_a_reason_that_QUOTES_the_draft_it_rejected_still_passes(self):
        """A refusal that shows its work. The quoted text is inside the BOUND reason,
        so it is already graded by the hash and must not be re-read as a draft the
        turn is delivering. This is what makes `_unbound_text` load-bearing rather
        than decorative: scan the whole turn instead and this refusal is held."""
        contract = _Contract()
        reason = ("it ran 300 words, over the ceiling:\n"
                  "> nobody reads the dashboard, they read the alert")
        row = _receipt("refused", reason)
        assert gate._verify_route_receipt(_context(contract), REQUEST,
                                          _turn(reason=reason, receipt=row))[
                                              "status"] == "refusal-consumed"

    def test_prose_around_the_reason_that_names_a_platform_still_passes(self):
        """The platform word in the turn's own chat, not in the bound reason."""
        contract = _Contract()
        row = _receipt("refused", REASON)
        turn = ("I could not write the LinkedIn reply for you.\n\n"
                f"=== WHY THERE IS NO DRAFT ===\n{REASON}\n"
                f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}")
        assert gate._verify_route_receipt(_context(contract), REQUEST,
                                          turn)["status"] == "refusal-consumed"


class TestAFencedDraftUnderARefusalIsStillADraft:
    """PR #375 major 2. `extract_publishable` returns '' with no framing sentence, and
    this file's own `main()` says a fenced post with no "here's the post" line is the
    founder's MOST COMMON turn shape. So a fenced draft rode through under a no-draft
    receipt and nothing graded it. The complete path binds its draft by `output_hash`;
    the refusal path has to be no weaker."""

    def test_a_fenced_draft_above_the_refusal_block_is_held(self):
        row = _receipt("refused", REASON)
        turn = ("```\nnobody reads the dashboard, they read the alert\n```\n\n"
                f"=== WHY THERE IS NO DRAFT ===\n{REASON}\n"
                f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}")
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._verify_route_receipt(_context(_Contract()), REQUEST, turn)

    def test_a_blockquoted_draft_above_the_refusal_block_is_held(self):
        row = _receipt("refused", REASON)
        turn = ("> nobody reads the dashboard, they read the alert\n\n"
                f"=== WHY THERE IS NO DRAFT ===\n{REASON}\n"
                f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}")
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._verify_route_receipt(_context(_Contract()), REQUEST, turn)

    def test_a_fenced_draft_BELOW_the_receipt_block_is_held(self):
        """PR #375 round 2, major. The first fix removed the receipt by TRUNCATING at
        its marker, so the guard saw only what was above it and a fence one line lower
        rode through and spent the refusal. The reason and the receipt have to come out
        as SPANS, leaving everything else, above and below, to be graded."""
        row = _receipt("refused", REASON)
        turn = (f"=== WHY THERE IS NO DRAFT ===\n{REASON}\n"
                f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}\n"
                "\n```\nnobody reads the dashboard, they read the alert\n```\n")
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._verify_route_receipt(_context(_Contract()), REQUEST, turn)

    def test_a_blockquoted_draft_BELOW_the_receipt_block_is_held(self):
        row = _receipt("refused", REASON)
        turn = (f"=== WHY THERE IS NO DRAFT ===\n{REASON}\n"
                f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}\n"
                "\n> nobody reads the dashboard, they read the alert\n")
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._verify_route_receipt(_context(_Contract()), REQUEST, turn)

    def test_ordinary_prose_below_the_receipt_still_passes(self):
        """The negative control on the fix above. Trailing chat is the common shape;
        only DRAFT-shaped trailing content may hold the turn."""
        contract = _Contract()
        row = _receipt("refused", REASON)
        turn = (f"=== WHY THERE IS NO DRAFT ===\n{REASON}\n"
                f"\n=== ROUTE RECEIPT ===\n{json.dumps(row, sort_keys=True)}\n"
                "\nTell me if you want me to retry with a lower word target.\n")
        assert gate._verify_route_receipt(_context(contract), REQUEST,
                                          turn)["status"] == "refusal-consumed"

    def test_the_detector_is_the_one_main_trusts(self):
        """Not a third detector. `reply_carries_a_draft` is what `main()` asks, and its
        draft test is `=== DRAFT ===` or `extract_setoff_draft`; its third clause is
        the route receipt, which every refusal turn carries by construction and so
        cannot be reused here. Pinned so a later edit cannot quietly swap in a
        looser or stricter rule."""
        fenced = "```\nnobody reads the dashboard\n```"
        assert gate.reply_carries_a_draft(fenced) is True
        assert bool(gate.extract_setoff_draft(fenced)) is True
        # the shape that must NOT read as a draft: plain refusal prose naming a platform
        plain = "I could not write the LinkedIn reply for you."
        assert bool(gate.extract_setoff_draft(plain)) is False
        assert bool(gate.extract_publishable(plain)) is True, (
            "extract_publishable is the loose one; this is why the guard stopped using it")


class TestAnAddedSentenceIsNotAForgedReason:
    """PR #375 minor 3. The producer's contract is that everything between the marker
    and the receipt is the bound reason, and that stays true. But the model writes the
    turn, and a closing line after the reason joined the hash, holding the turn with
    "does not match the stated reason", which reads as tampering rather than as an
    extra sentence."""

    def test_a_follow_up_line_after_the_reason_does_not_break_the_hash(self):
        contract = _Contract()
        row = _receipt("refused", REASON)
        turn = _turn(reason=f"{REASON}\n\nWant me to try a shorter one?", receipt=row)
        assert gate._verify_route_receipt(_context(contract), REQUEST,
                                          turn)["status"] == "refusal-consumed"

    def test_the_whole_region_still_binds_when_it_matches(self):
        """The producer's own contract, unchanged: a multi-line reason is hashed
        whole. Tried FIRST, so this keeps working exactly as it did."""
        contract = _Contract()
        multi = "300 words, above the ceiling\n\nand the corpus floor was missed too"
        row = _receipt("refused", multi)
        assert gate._verify_route_receipt(_context(contract), REQUEST,
                                          _turn(reason=multi, receipt=row))[
                                              "status"] == "refusal-consumed"

    def test_a_follow_up_line_cannot_smuggle_a_draft(self):
        """The trailing line is UNBOUND text, so it gets the draft check the reason
        does not need. Otherwise this fix would open the hole major 2 just closed."""
        row = _receipt("refused", REASON)
        turn = _turn(reason=f"{REASON}\n\n```\nnobody reads the dashboard\n```",
                     receipt=row)
        with pytest.raises(gate.RouteBoundaryError, match="may not deliver a draft"):
            gate._verify_route_receipt(_context(_Contract()), REQUEST, turn)

    def test_a_wholly_different_reason_is_still_refused(self):
        """The control on the control. Relaxing the trailing-line case must not let a
        turn report a friendlier verdict than the one the receipt bound."""
        row = _receipt("refused", REASON)
        with pytest.raises(gate.RouteBoundaryError, match="stated reason"):
            gate._verify_route_receipt(
                _context(_Contract()), REQUEST,
                _turn(reason="it just needed a tweak", receipt=row))


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
