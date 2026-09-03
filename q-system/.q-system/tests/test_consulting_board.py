"""The consulting morning board: mirror, never a second derivation (2026-09-03).

The load-bearing classes are TestAStaleCardIsAnError and TestTheDryRunWritesNothing.
Both pin defects this work actually hit, not defects imagined for it.
"""
import datetime as dt
import io
import json
import pathlib
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import board_rows  # noqa: E402
import consulting_board as cb  # noqa: E402
import groupme_inbox as gm  # noqa: E402

NOW = dt.datetime(2026, 9, 3, 14, 45, tzinfo=dt.timezone.utc)   # 07:45 PT
TODAY = "2026-09-03"

# INVENTED NAMES, and that is a rule rather than a style choice. kipi-system is a
# PUBLIC repo; `client-name-guard.py` blocks a real client name in staged content and it
# caught the first version of this fixture, which used three of them. A fixture only
# needs the card's SHAPE, and the shape is what these tests are about.
CARD = """# TODAY CARD
*Your book today* - 4 active
*THE MOVE* 🔴 *Northwind Design* · you said "add a renewal date" — not sent
🔴 *Harbor Labs* · you said "build the records" — not sent
⚪ *Kestrel Group* · their move
📞 *2 to reach out* — 🔥 Kestrel Group (fire)
"""


def _tree(tmp_path, card=CARD, date=TODAY, crash=None, gtm=None):
    q = tmp_path / "q-consult"
    # exist_ok: a test may build the tree twice in one tmp_path to compare two runs.
    (q / "output").mkdir(parents=True, exist_ok=True)
    (q / "my-project").mkdir(parents=True, exist_ok=True)
    (q / "output" / "today-card.md").write_text(card, encoding="utf-8")
    (q / "output" / "ask-crm-state-card-heartbeat.json").write_text(
        json.dumps({"at": "x", "card": {"date": date, "counts": {"red": 2, "reach": 1}},
                    "crash": crash}), encoding="utf-8")
    (q / "my-project" / "gtm-queue.json").write_text(
        json.dumps(gtm if gtm is not None else
                   {"rows": {"1.1": {"id": "1.1", "action": "Run the audit week",
                                     "performer": "founder", "state": "ready", "rank": 1},
                             "1.2": {"id": "1.2", "action": "machine thing",
                                     "performer": "mechanism", "state": "ready", "rank": 0}}}),
        encoding="utf-8")
    return cb._paths(tmp_path)


class TestItMirrorsTheCardAndNeverRederivesIt:
    def test_the_registry_is_never_opened(self, tmp_path):
        """No clients.json in the tree at all, and the section still delivers.

        This is the whole design in one assertion. `clients.json` is 162 rows of which
        ~150 are cold prospects; a collector that read it would put them on his board.
        """
        rows, err = cb.collect(NOW, {}, _tree(tmp_path))
        assert err is None
        assert any("Northwind Design" in r for r in rows)

    def test_the_THE_MOVE_prefix_still_parses(self, tmp_path):
        """The rank-1 row carries a `*THE MOVE*` prefix. The first parser anchored the
        health emoji to line start, so it dropped the rank-1 row, the most important one,
        while every lesser row parsed. A parser that drops the FIRST row hides its own gap."""
        card_rows, err = cb.read_card(_tree(tmp_path))
        assert err is None
        assert card_rows[0]["name"] == "Northwind Design"
        assert card_rows[0]["health"] == "🔴"

    def test_the_health_verdict_is_the_cards_not_recomputed(self, tmp_path):
        rows, _ = cb.read_card(_tree(tmp_path))
        # Scoped to CLIENT rows: since Codex round 2 a reach-out row is named for the
        # PERSON too, so the same name legitimately appears twice with two verdicts.
        clients = {r["name"]: r["health"] for r in rows if r["kind"] == "client"}
        assert clients["Kestrel Group"] == "⚪"


class TestIdentityIsTheTHING_NotItsRendering:
    """Codex round 2. Round 1 fixed the health dot in ONE producer; the same defect
    class sat untouched at two other call sites. A fix whose blast radius is one call
    site cannot fix a defect whose blast radius is a category."""

    def test_a_reach_out_row_is_named_for_the_PERSON_not_the_count(self, tmp_path):
        rows, _ = cb.read_card(_tree(tmp_path))
        reach = [r["name"] for r in rows if r["kind"] == "reach"]
        assert "Kestrel Group" in reach
        assert not any("to reach out" in n for n in reach), (
            "keying on the tally makes different people share one row, its status "
            "and the bucket he dragged it to")

    def test_an_inbox_id_survives_the_age_changing(self, tmp_path):
        """Same intent as the round-2 test this replaces, on the real seam. The id is
        the thread's, so ANY rendering change is now irrelevant by construction rather
        than by a regex that has to have anticipated it."""
        brief = _brief()
        a = cb.buckets(NOW, {"mail": ([brief.Row("Portant: 2h ago", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": ([brief.Row("Portant: 5h ago", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a == b, "an age change minted a new id and would orphan his row"

    def test_but_a_different_thread_is_a_different_row(self, tmp_path):
        brief = _brief()
        a = cb.buckets(NOW, {"mail": ([brief.Row("Portant: docs", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": ([brief.Row("Harbor: invoice", "mail:t2")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a != b, "two threads must never share one row"

    def test_an_inbox_row_with_NO_key_is_REFUSED(self, tmp_path):
        """The fallback is the defect. A producer that forgets must fail loudly, not
        quietly regress to keying on its own rendered text -- which is precisely how
        this survived three fixes."""
        with pytest.raises(TypeError, match="no stable key"):
            cb.buckets(NOW, {"mail": (["a bare string"], None)}, _tree(tmp_path))

    def test_no_identity_is_derived_from_rendered_text(self):
        """The regex is deleted and must stay deleted. Rounds 1-4 were four patches to
        it; a fifth surface form was guaranteed while it existed."""
        src = pathlib.Path(cb.__file__).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                          if not l.lstrip().startswith("#"))
        assert "_VOLATILE" not in code and "_stable" not in code, (
            "consulting_board grew a text-scrubbing identity again")


class TestRound3:
    """Every finding here was CAUSED by a round-2 fix. Pinned so the repair does not
    have to be rediscovered by a fourth review."""

    def test_a_client_row_and_a_reach_out_row_for_one_person_are_two_rows(self, tmp_path):
        """Both are named for the person, so keying on the name alone collapsed them:
        the reach-out action was dropped and read-back still said ok, because `wanted`
        had already merged them before the count was taken."""
        b = cb.buckets(NOW, {}, _tree(tmp_path))
        keys = [i["key"] for i in b["top_of_mind"] + b["this_week"]]
        assert len(keys) == len(set(keys)), f"two rows collapsed onto one key: {keys}"
        assert any(k.startswith("reach:") for k in keys)
        assert any(k.startswith("client:") for k in keys)

    def test_an_unreadable_gtm_queue_does_NOT_authorise_archiving_its_scope(self, tmp_path):
        """It was unconditionally healthy, so a broken queue let the painter delete the
        GTM row he had positioned and recreate it in a computed bucket."""
        paths = _tree(tmp_path)
        paths["gtm"].write_text("{ not json", encoding="utf-8")
        assert "gtm" not in cb.buckets(NOW, {}, paths)["healthy_scopes"]

    def test_a_readable_gtm_queue_DOES(self, tmp_path):
        assert "gtm" in cb.buckets(NOW, {}, _tree(tmp_path))["healthy_scopes"]

    def test_two_threads_differing_only_by_a_number_stay_two_rows(self, tmp_path):
        """Round 3's finding is now unreachable: nothing reads the digits at all.
        Kept, driving the real key, because the BEHAVIOUR it protects is the point.
        The volatile-token strip removed EVERY digit run, so "invoice 4021" and
        "invoice 4022" became one board row."""
        brief = _brief()
        a = cb.buckets(NOW, {"mail": ([brief.Row("invoice 4021 from them", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": ([brief.Row("invoice 4022 from them", "mail:t2")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a != b

    def test_but_an_age_is_still_volatile(self, tmp_path):
        """One thread, two renderings, one row. Under the regex this held only for the
        age forms somebody had thought of; under a thread id it holds for all of them."""
        brief = _brief()
        a = cb.buckets(NOW, {"mail": ([brief.Row("invoice 4021, 2 hours ago", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": ([brief.Row("invoice 4021, 5 hours ago", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a == b

    def test_kept_rows_do_not_fake_a_read_back_mismatch(self):
        """`kept` rows are on the board and deliberately not in `wanted`. Comparing
        `seen` to `wanted` alone made every quiet source report a mismatch and mark the
        brief degraded, which trains him to ignore the word."""
        src = (SCRIPTS / "board_rows.py").read_text(encoding="utf-8")
        assert 'expected = counts["wanted"] + counts["kept"]' in src
        assert "if seen != expected:" in src


class TestAQuietSourceNeverArchivesHisRows:
    """Codex round 2 (major): a transient Gmail error replaced that source's rows with
    a single error row, so every inbox row he had positioned fell out of `wanted` and
    the painter archived the lot. A source that could not answer has said nothing, and
    nothing is not "they are gone"."""

    def test_a_failed_source_is_not_a_healthy_scope(self, tmp_path):
        b = cb.buckets(NOW, {"mail": ([], "gmail down")}, _tree(tmp_path))
        assert "inbox:Gmail" not in b["healthy_scopes"]
        assert any("COULD NOT READ" in i["title"] for i in b["inbox"])

    def test_a_healthy_source_IS_one(self, tmp_path):
        b = cb.buckets(NOW, {"mail": ([_brief().Row("a thread", "mail:t1")], None)},
                       _tree(tmp_path))
        assert "inbox:Gmail" in b["healthy_scopes"]

    def test_the_painter_REFUSES_buckets_with_no_scope_information(self):
        """Archiving without it would delete rows on any transient failure, so an
        absent field is a refusal rather than a permissive default."""
        with pytest.raises(ValueError):
            board_rows.paint({"top_of_mind": [], "this_week": [], "inbox": []},
                             "t", "db", opener=lambda *a, **k: None)

    def test_an_unknown_scope_on_an_existing_row_is_KEPT(self):
        """Fails safe: a row this module cannot classify is never archived."""
        assert board_rows._scope_of({"properties": {}}) == ""


class TestOnlyOnePainterAtATime:
    """Codex round 2 (major): paint() queries then creates, so two simultaneous runs
    both saw "absent" and both created. Round 1 only DETECTED the duplicates after the
    fact, which reports a mess instead of preventing one."""

    def test_a_second_painter_is_refused_immediately(self, tmp_path):
        lock = tmp_path / "board.lock"
        with board_rows.exclusive(lock):
            with pytest.raises(board_rows.BoardBusy):
                with board_rows.exclusive(lock):
                    pass

    def test_and_the_lock_is_released_afterwards(self, tmp_path):
        lock = tmp_path / "board.lock"
        with board_rows.exclusive(lock):
            pass
        with board_rows.exclusive(lock):
            pass                                   # no raise means it was released


class TestAStaleCardIsAnError:
    """Never a quiet mirror. He would act on it."""

    def test_yesterdays_card_is_withheld_and_named(self, tmp_path):
        rows, err = cb.collect(NOW, {}, _tree(tmp_path, date="2026-09-02"))
        assert rows == []
        assert "2026-09-02" in err and "2026-09-03" in err

    def test_a_crashed_card_job_is_an_error(self, tmp_path):
        _, err = cb.collect(NOW, {}, _tree(tmp_path, crash="boom"))
        assert "crashed" in err

    def test_a_card_that_parses_to_nothing_is_a_format_change_not_a_quiet_morning(self, tmp_path):
        _, err = cb.collect(NOW, {}, _tree(tmp_path, card="# TODAY CARD\nno rows here\n"))
        assert "format changed" in err

    def test_and_a_stale_card_writes_no_rows_at_all(self, tmp_path):
        b = cb.buckets(NOW, {}, _tree(tmp_path, date="2026-09-02"))
        assert b["error"] and b["top_of_mind"] == [] and b["this_week"] == []


class TestTheGtmMoveIsOnlyWhatNeedsHim:
    def test_rows_is_a_dict_not_a_list(self, tmp_path):
        """Measured: the first reader typed isinstance(rows, list) and reported
        COULD NOT READ against a perfectly good queue."""
        move, err = cb.read_gtm(_tree(tmp_path))
        assert err is None and move["action"] == "Run the audit week"

    def test_a_mechanism_row_never_reaches_his_board(self, tmp_path):
        move, _ = cb.read_gtm(_tree(tmp_path))
        assert move["performer"] == "founder"      # rank 0 mechanism row outranked it

    def test_nothing_waiting_on_him_is_not_an_error(self, tmp_path):
        paths = _tree(tmp_path, gtm={"rows": {}})
        move, err = cb.read_gtm(paths)
        assert move is None and err is None


class TestTheDryRunWritesNothing:
    """The defect this work shipped and caught: `--dry-run` printed "nothing sent" and
    had already created 12 rows on the live board. The send flag only ever covered the
    Slack send, because until board_rows no section could write."""

    def _token(self, tmp_path):
        """A credential the guard can get PAST.

        Both tests below passed on the author's machine and failed in CI with
        `cannot unpack non-iterable NoneType`, because CI has no
        ~/.config/kipi/notion-token: the OFF switch fired first and returned None, so
        the guard under test was never reached. The ordering is correct behaviour and
        the tests were wrong to depend on the developer's own credentials. Supplying a
        fake token is what makes these assert the guard rather than the environment.
        """
        tf = tmp_path / "notion-token"
        tf.write_text("t", encoding="utf-8")
        return str(tf)

    def test_the_flag_stops_the_board_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIPI_BRIEF_DRY_RUN", "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        rows, err = board_rows.collect(NOW, {}, token_file=self._token(tmp_path))
        assert rows == [] and "dry-run" in err

    def test_pytest_alone_also_stops_it(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        rows, err = board_rows.collect(NOW, {}, token_file=self._token(tmp_path))
        assert rows == [] and "pytest" in err

    def test_and_with_NO_credential_it_is_OFF_before_either_guard(self, tmp_path):
        """The negative control the two above were accidentally exercising in CI.
        Pinned deliberately so the ordering is a decision, not a coincidence."""
        assert board_rows.collect(NOW, {}, token_file=str(tmp_path / "absent")) is None


class TestHisDragAlwaysWins:
    def test_an_existing_row_is_never_given_a_bucket(self):
        props = board_rows._properties({"title": "t", "detail": "d"}, "Top of Mind",
                                       "cb:abc", include_bucket=False)
        assert "Bucket" not in props and "Status" not in props

    def test_a_new_row_is(self):
        props = board_rows._properties({"title": "t"}, "Inbox", "cb:abc",
                                       include_bucket=True)
        assert props["Bucket"]["select"]["name"] == "Inbox"

    def test_the_id_is_stable_across_mornings(self):
        """Hashed from `key` alone. The detail moves daily (due dates, reply counts)."""
        a = board_rows.item_id("top_of_mind", {"key": "Northwind", "title": "🔴 Northwind",
                                               "detail": "due Mon"})
        b = board_rows.item_id("top_of_mind", {"key": "Northwind", "title": "🔴 Northwind",
                                               "detail": "due Tue"})
        assert a == b and a.startswith(board_rows.OWNED_PREFIX)

    def test_the_id_SURVIVES_a_health_change(self):
        """The Codex finding, pinned. The id used to be hashed from the title, which
        embeds the health dot, so red -> green minted a new id: the next paint archived
        the row he had DRAGGED and created a replacement in a computed bucket. The
        promise this class is named for depended on an id that does not move."""
        red = board_rows.item_id("top_of_mind", {"key": "Northwind", "title": "🔴 Northwind"})
        green = board_rows.item_id("this_week", {"key": "Northwind", "title": "🟢 Northwind"})
        assert red == green, "a health change minted a new id and would orphan his row"

    def test_an_item_with_no_key_is_REFUSED_never_fallen_back(self):
        """A title fallback would work quietly, with the unstable id, which is exactly
        how the defect returns."""
        with pytest.raises(ValueError):
            board_rows.item_id("top_of_mind", {"title": "🔴 Northwind"})

    def test_every_producer_supplies_a_key(self, tmp_path):
        """Drives the real buckets() rather than asserting the contract in prose."""
        b = cb.buckets(NOW, {}, _tree(tmp_path))
        items = b["top_of_mind"] + b["this_week"] + b["inbox"]
        assert items
        for item in items:
            assert item.get("key"), item

    def test_a_health_dot_never_reaches_a_key(self, tmp_path):
        b = cb.buckets(NOW, {}, _tree(tmp_path))
        for item in b["top_of_mind"] + b["this_week"]:
            assert not any(d in item["key"] for d in "🔴🟡🟢⚪🟠📞"), item["key"]

    def test_a_hand_made_row_is_not_owned(self):
        assert not "some-hand-id".startswith(board_rows.OWNED_PREFIX)


class TestGroupMeNeverReportsASilentZero:
    def test_an_outage_is_an_error_not_an_empty_inbox(self, monkeypatch):
        monkeypatch.setattr(gm, "load_token", lambda: "t")
        def boom(*a, **k):
            raise OSError("down")
        monkeypatch.setattr(gm, "waiting", boom)
        rows, err = gm.collect(NOW, {})
        assert rows == [] and "unreachable" in err

    def test_no_token_is_OFF_not_broken(self, monkeypatch):
        monkeypatch.setattr(gm, "load_token", lambda: None)
        assert gm.collect(NOW, {}) is None

    def test_the_group_author_is_read_from_the_message_not_the_preview(self):
        """The preview has no user_id. Reading it there returned "" for every group and
        the "is it his?" test dropped all four, on a morning three were live."""
        src = (SCRIPTS / "groupme_inbox.py").read_text(encoding="utf-8")
        assert "/groups/{g.get('id')}/messages" in src


class TestEngineeringLeavesHisBrief:
    def _brief(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "morning_brief", SCRIPTS / "morning-brief.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_owed_and_overnight_are_not_founder_sections(self):
        mb = self._brief()
        keys = {k for k, _ in mb.SECTIONS}
        assert "owed" not in keys and "overnight" not in keys

    def test_they_are_still_collected_and_routed(self):
        mb = self._brief()
        assert {k for k, _ in mb.ENGINEERING_SECTIONS} == {"owed", "overnight"}
        sent = []
        filed, failed = mb.route_engineering(
            {"owed": ([], "linear down"), "overnight": (["fine"], None)},
            notify=sent.append)
        assert len(sent) == 1 and "linear down" in sent[0]
        assert filed == sent and failed == []

    def test_a_notifier_that_FAILS_is_reported_not_counted_as_filed(self):
        """Codex finding (major), 2026-09-03: route returned every attempted line as
        routed, whether or not slack-notify.sh actually filed. A detected engineering
        problem that is then lost on the way to the queue looks handled, which is worse
        than one never detected."""
        mb = self._brief()

        def broken(_message):
            raise RuntimeError("notifier down")

        filed, failed = mb.route_engineering(
            {"owed": ([], "linear down"), "overnight": ([], "launchd down")},
            notify=broken)
        assert filed == []
        assert len(failed) == 2 and all("notifier down" in why for _l, why in failed)

    def test_a_healthy_section_pages_nobody(self):
        """A ticket every morning is how an alert channel gets muted."""
        mb = self._brief()
        sent = []
        filed, failed = mb.route_engineering(
            {"owed": (["x"], None), "overnight": ([], None)}, notify=sent.append)
        assert sent == [] and filed == [] and failed == []

    def test_only_one_module_writes_the_board(self):
        mb = self._brief()
        stems = {s for s, _, _ in mb.OPTIONAL_SECTIONS}
        assert "board_rows.py" in stems
        assert "notion_board.py" not in stems, (
            "notion_board.py writes bullets to the same page board_rows writes rows to; "
            "the first live dry-run rendered both")


def _brief():
    import importlib.util
    spec = importlib.util.spec_from_file_location("morning_brief", SCRIPTS / "morning-brief.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRound4:
    """The first real Codex read after rounds 2 and 3 ran on the Opus fallback. Both
    findings are the same shape: a fix that held for the fixture and not for the
    producer. So these tests drive the PRODUCER (collect_mail, collect) and not a
    hand-typed row."""

    def test_the_real_mail_producers_age_form_is_volatile(self, tmp_path):
        """collect_mail renders `[2h]`, not "2h ago". Round 2's regex never matched it,
        so every age change replaced the Notion row and lost his drag."""
        brief = _brief()

        def runner(age):
            return lambda p, t: (json.dumps({"threads": [
                {"from": "Alice", "subject": "Docs", "age_hours": age}]}), None)

        a_rows, _ = brief.collect_mail(None, runner(2))
        b_rows, _ = brief.collect_mail(None, runner(3))
        assert a_rows != b_rows, "the producer must actually render the age, or this proves nothing"
        a = cb.buckets(NOW, {"mail": (a_rows, None)}, _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": (b_rows, None)}, _tree(tmp_path))["inbox"][0]["key"]
        assert a == b, f"an age change minted a new id: {a!r} != {b!r}"

    def test_but_a_bracketed_number_that_is_not_an_age_stays(self, tmp_path):
        brief = _brief()
        a = cb.buckets(NOW, {"mail": ([brief.Row("Alice ticket [4021]", "mail:t1")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": ([brief.Row("Alice ticket [4022]", "mail:t2")], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a != b

    @staticmethod
    def _fake_db(slow_first_query_s: float):
        """The database API, just enough of it. Records every call; the first query
        sleeps past the budget so the worker is abandoned mid-paint."""
        class Fake:
            def __init__(self):
                self.calls = []

            def __call__(self, req, timeout):
                method, url = req.get_method(), req.full_url
                if "/databases/" in url and not self.calls:
                    self.calls.append(("query-slow", timeout))
                    time.sleep(slow_first_query_s)
                    return io.BytesIO(b'{"results": [], "has_more": false}')
                self.calls.append((method, url))
                if "/databases/" in url:
                    return io.BytesIO(b'{"results": [], "has_more": false}')
                return io.BytesIO(b'{"id": "p1"}')
        return Fake()

    def test_no_write_lands_after_the_timeout_was_reported(self, tmp_path, monkeypatch):
        """Codex round 4 (major): the guard abandoned the worker and it kept writing.
        Now the budget is cancelled before the timeout is reported, so the worker's
        next request refuses and the paint stops where it stood."""
        (tmp_path / "tok").write_text("t")
        (tmp_path / "db").write_text("db1")
        monkeypatch.setattr(board_rows, "LOCK_FILE", tmp_path / "board.lock")
        buckets = {"top_of_mind": [{"key": "k1", "title": "t", "detail": "d", "scope": "card"}],
                   "this_week": [], "inbox": [], "healthy_scopes": {"card"}}
        monkeypatch.setattr(board_rows.consulting_board, "buckets", lambda *a, **k: buckets)
        fake = self._fake_db(slow_first_query_s=0.15)
        rows, error = board_rows.collect(NOW, {}, opener=fake, token_file=tmp_path / "tok",
                                         db_file=tmp_path / "db", budget_s=0.05)
        assert rows == [] and "timed out" in error and "no further write" in error
        time.sleep(0.4)                      # let the abandoned worker run on and try
        writes = [c for c in fake.calls if c[0] in ("POST", "PATCH") and "/pages" in c[1]]
        assert writes == [], f"writes landed after the timeout: {writes}"

    def test_and_the_in_flight_call_is_capped_to_what_is_left(self, tmp_path, monkeypatch):
        """A 10s HTTP timeout on a request that starts with 0.02s left would outlive
        the budget. The request's own timeout is clipped to the remainder."""
        seen = []

        def opener(req, timeout):
            seen.append(timeout)
            return io.BytesIO(b'{"results": [], "has_more": false}')
        budget = board_rows._Budget(0.05)
        board_rows.existing_rows("t", "db", opener, budget=budget)
        assert seen and seen[0] <= 0.05 < board_rows.TIMEOUT_S

    def test_the_boards_own_budget_fires_before_the_briefs_guard(self):
        """Two bounds, one ordering. If the brief's guard fired first the worker would
        be abandoned with a live budget, which is exactly the round-4 defect."""
        assert board_rows.BUDGET_S < _brief().COLLECT_BUDGET_S

    def test_a_worker_that_ran_out_of_time_also_let_go_of_the_lock(self, tmp_path, monkeypatch):
        (tmp_path / "tok").write_text("t")
        (tmp_path / "db").write_text("db1")
        monkeypatch.setattr(board_rows, "LOCK_FILE", tmp_path / "board.lock")
        buckets = {"top_of_mind": [], "this_week": [], "inbox": [], "healthy_scopes": {"card"}}
        monkeypatch.setattr(board_rows.consulting_board, "buckets", lambda *a, **k: buckets)
        fake = self._fake_db(slow_first_query_s=0.15)
        board_rows.collect(NOW, {}, opener=fake, token_file=tmp_path / "tok",
                           db_file=tmp_path / "db", budget_s=0.05)
        time.sleep(0.3)
        with board_rows.exclusive(tmp_path / "board.lock"):
            pass                                        # no BoardBusy: it was released


class TestTheBoardLooksLikeTheOneHeAsked_For:
    """Founder, 2026-09-03, with two screenshots of Bloom's board: *"This is what I
    wanted my board to look like."* The schema already matched. Three things his
    screenshots carry that this writer did not fill."""

    def test_every_row_carries_a_priority(self, tmp_path):
        """Bloom's board is scanned by P0-P3. A board that writes no Priority renders
        an empty column, which is worse than no column: it looks like a field he
        forgot to fill."""
        b = cb.buckets(NOW, {"mail": ([_brief().Row("Portant: docs", "mail:t1")], None)},
                       _tree(tmp_path))
        rows = b["top_of_mind"] + b["this_week"] + b["inbox"]
        assert rows, "fixture produced no rows, so this proves nothing"
        missing = [r["title"] for r in rows if not r.get("priority")]
        assert not missing, f"rows with no priority: {missing}"
        assert all(r["priority"] in ("P0", "P1", "P2", "P3") for r in rows)

    def test_priority_is_the_cards_verdict_translated_not_a_second_judgement(self):
        """The mirror rule: one thing computes urgency. This table only renames it."""
        assert cb.PRIORITY_BY_HEALTH["🔴"] == "P0"
        assert cb.PRIORITY_BY_HEALTH["⚪"] == "P3"
        src = pathlib.Path(cb.__file__).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for invented in ("days_overdue", "score", "urgency"):
            assert invented not in code, (
                f"{invented!r} suggests this module started computing urgency itself; "
                "the state card owns that verdict")

    def test_every_row_carries_a_done_signal(self, tmp_path):
        b = cb.buckets(NOW, {"mail": ([_brief().Row("Portant: docs", "mail:t1")], None)},
                       _tree(tmp_path))
        rows = b["top_of_mind"] + b["this_week"] + b["inbox"]
        missing = [r["title"] for r in rows if not (r.get("done") or "").strip()]
        assert not missing, f"rows with no done signal: {missing}"

    def test_the_done_signal_reaches_notion_and_leads_the_note(self):
        props = board_rows._properties(
            {"title": "t", "scope": "card", "detail": "d", "done": "you sent it"},
            "Top of Mind", "kipi-abc", True)
        note = props["Notes"]["rich_text"][0]["text"]["content"]
        assert note.startswith("Done signal: you sent it"), note
        assert "scope=card" in note, "the painter still has to read its scope back"

    def test_domain_is_the_producers_not_a_hardcoded_Consulting(self):
        gtm = board_rows._properties({"title": "t", "domain": "GTM"}, "Top of Mind", "i", True)
        assert gtm["Domain"]["multi_select"][0]["name"] == "GTM"
        bare = board_rows._properties({"title": "t"}, "Top of Mind", "i", True)
        assert bare["Domain"]["multi_select"][0]["name"] == "Consulting", "safe default"

    def test_size_is_never_invented(self):
        """Bloom's board has XS/S/M. Nothing here knows effort, so the column stays
        empty rather than carrying a number that looks measured and is not."""
        props = board_rows._properties({"title": "t", "priority": "P0"}, "Inbox", "i", True)
        assert "Size" not in props


class TestTwoThreadsAreNeverOneRow:
    """Codex, 2026-09-03, on the fix for rounds 1-4: the `sender|subject` fallback
    (used when the model returns no thread id) collapsed two distinct threads into one
    Notion row. Read-back still passed, because `wanted` had already lost the second
    one -- the same shape as the round-3 defect, one layer up."""

    def test_two_threads_from_one_person_with_one_subject_stay_two_rows(self):
        brief = _brief()
        runner = lambda p, t: (json.dumps({"threads": [
            {"from": "Alice", "subject": "Re: invoice", "age_hours": 2},
            {"from": "Alice", "subject": "Re: invoice", "age_hours": 9}]}), None)
        rows, err = brief.collect_mail(None, runner)
        assert err is None
        assert len(rows) == 2, "the producer must emit both threads"
        assert rows[0].key != rows[1].key, (
            f"both threads share the key {rows[0].key!r}; the board writes one row and "
            "the second task is silently gone")

    def test_a_real_thread_id_still_wins_and_stays_stable(self):
        """The suffix is only for the id-less case. A thread WITH an id must not pick
        one up, or the age-stability the whole change exists for is undone."""
        brief = _brief()
        runner = lambda p, t: (json.dumps({"threads": [
            {"id": "t1", "from": "Alice", "subject": "Re: invoice", "age_hours": 2},
            {"id": "t2", "from": "Alice", "subject": "Re: invoice", "age_hours": 9}]}), None)
        rows, _ = brief.collect_mail(None, runner)
        assert [r.key for r in rows] == ["mail:t1", "mail:t2"]

    def test_both_rows_reach_the_board(self, tmp_path):
        brief = _brief()
        runner = lambda p, t: (json.dumps({"threads": [
            {"from": "Alice", "subject": "Re: invoice", "age_hours": 2},
            {"from": "Alice", "subject": "Re: invoice", "age_hours": 9}]}), None)
        rows, _ = brief.collect_mail(None, runner)
        inbox = cb.buckets(NOW, {"mail": (rows, None)}, _tree(tmp_path))["inbox"]
        assert len({i["key"] for i in inbox}) == 2, "one task never reached the board"
