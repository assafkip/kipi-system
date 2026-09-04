"""The consulting morning board: mirror, never a second derivation (2026-09-03).

The load-bearing classes are TestAStaleCardIsAnError and TestTheDryRunWritesNothing.
Both pin defects this work actually hit, not defects imagined for it.
"""
import datetime as dt
import io
import json
import re
import pathlib
import os
import sys
import time
from pathlib import Path

import urllib.error
import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import board_rows  # noqa: E402


def _load_engineering_route():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "engineering_route", SCRIPTS / "engineering_route.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
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


def _tree(tmp_path, card=CARD, date=TODAY, crash=None, gtm=None,
          commitments=None, clients=None):
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
    # Written ONLY when a test asks for them. The default tree deliberately has
    # neither, because test_the_registry_is_never_opened proves this module delivers
    # without the registry and that must keep being true.
    if commitments is not None:
        (q / "my-project" / "commitments.jsonl").write_text(commitments, encoding="utf-8")
    if clients is not None:
        (q / "my-project" / "clients.json").write_text(json.dumps(clients), encoding="utf-8")
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

    def test_a_stale_card_writes_no_CLIENT_rows(self, tmp_path):
        """The round-2 rule, unchanged: a source that could not answer writes nothing,
        and its rows are neither refreshed nor archived. What changed in round 9 is the
        RADIUS, not this."""
        b = cb.buckets(NOW, {}, _tree(tmp_path, date="2026-09-02"))
        assert not any(r["scope"] == "card" for r in b["top_of_mind"] + b["this_week"])
        assert not any(r["scope"] == "myside" for r in b["top_of_mind"])
        assert "card" not in b["healthy_scopes"], "a stale card must not authorise archiving"
        # The GTM queue is its OWN file and answered. Silencing it because a different
        # producer is late is the radius mistake this change exists to remove, so this
        # asserts it keeps working rather than leaving it to chance.
        assert any(r["scope"] == "gtm" for r in b["top_of_mind"])

    def test_but_it_no_longer_silences_the_inbox(self, tmp_path):
        """Founder-facing reason this changed: a late 07:30 job used to mean no mail on
        the board either, from a source that answered perfectly well. The abort was not
        even protecting him from stale client rows, since nothing archives or
        overwrites them either way. It cost him today's mail to keep yesterday's
        clients he was going to see regardless."""
        b = cb.buckets(NOW, {"mail": ([_brief().Row("a thread", "mail:t1")], None)},
                       _tree(tmp_path, date="2026-09-02"))
        assert [r["key"] for r in b["inbox"]] == ["mail:t1"]
        assert "inbox:Gmail" in b["healthy_scopes"]

    def test_and_the_board_carries_an_alarm_row_that_can_be_cleared(self, tmp_path):
        """A partial board must never be a silent one. The alarm sits in its own scope
        which is ALWAYS healthy, so the morning the card comes back the row is archived
        rather than becoming permanent furniture."""
        stale = cb.buckets(NOW, {}, _tree(tmp_path, date="2026-09-02"))
        alarm = [r for r in stale["top_of_mind"] if r["scope"] == cb.CARD_ALARM]
        assert len(alarm) == 1 and "2026-09-02" in alarm[0]["detail"]
        assert cb.CARD_ALARM in stale["healthy_scopes"]

        fresh = cb.buckets(NOW, {}, _tree(tmp_path))
        assert not any(r["scope"] == cb.CARD_ALARM for r in fresh["top_of_mind"])
        assert cb.CARD_ALARM in fresh["healthy_scopes"]

    def test_the_painter_still_writes_nothing_on_a_real_error(self):
        """`error` keeps its old meaning and its old teeth. A card problem is not one."""
        with pytest.raises(ValueError):
            board_rows.paint({"error": "everything is broken", "top_of_mind": [],
                              "this_week": [], "inbox": [], "healthy_scopes": set()},
                             "t", "db", opener=lambda *a, **k: None)


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
    def test_declining_to_move_a_row_writes_neither_Bucket_nor_Status(self):
        """The narrow half of the promise. WHEN this module declines is
        `_bucket_decision`'s call and is pinned by
        TestARowHeNeverTouchedFollowsItsHealth; this holds that a decline really does
        leave both columns alone. The old name said "an existing row is NEVER given a
        bucket", which is the over-wide rule Codex round 6 charged for: a row nobody
        touched was frozen in its first morning's bucket forever."""
        props = board_rows._properties({"title": "t", "detail": "d"}, "Top of Mind",
                                       "cb:abc", include_bucket=False)
        assert "Bucket" not in props and "Status" not in props

    def test_a_new_row_is(self):
        props = board_rows._properties({"title": "t"}, "Inbox", "cb:abc",
                                       include_bucket=True, status="Not started")
        assert props["Bucket"]["select"]["name"] == "Inbox"
        assert props["Status"]["select"]["name"] == "Not started"

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

    def test_the_done_line_reaches_notion_and_leads_the_note(self):
        props = board_rows._properties(
            {"title": "t", "scope": "card", "detail": "d", "done": "you send it"},
            "Top of Mind", "kipi-abc", True)
        note = props["Notes"]["rich_text"][0]["text"]["content"]
        assert note.startswith("Done when: you send it"), note
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

    def test_two_indistinguishable_threads_become_one_row_that_SAYS_two(self):
        brief = _brief()
        runner = lambda p, t: (json.dumps({"threads": [
            {"from": "Alice", "subject": "Re: invoice", "age_hours": 2},
            {"from": "Alice", "subject": "Re: invoice", "age_hours": 9}]}), None)
        rows, err = brief.collect_mail(None, runner)
        assert err is None
        # ROUND 10 REVERSED THE SHAPE OF THIS FIX, and the harm it was written against
        # still governs. The first fix numbered duplicates by POSITION, so answering
        # the first thread renumbered the second onto its key and handed it that row's
        # Status and the bucket he had dragged it to. A thread wearing another
        # thread's identity is worse than either outcome the original note weighed.
        #
        # With no thread id nothing tells these two apart, so the group is ONE row
        # that says how many it stands for. The task is not silently gone, which is
        # what this class exists to prevent: he can see there are two and open both.
        assert len(rows) == 1
        assert "2 threads" in str(rows[0]), str(rows[0])

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
        assert len(inbox) == 1 and "2 threads" in inbox[0]["title"], inbox
        # And the id-LESS case is the only one that collapses: with real ids the board
        # still gets two rows. That is the normal path and it must not regress.
        keyed = lambda p, t: (json.dumps({"threads": [
            {"id": "t1", "from": "Alice", "subject": "Re: invoice", "age_hours": 2},
            {"id": "t2", "from": "Alice", "subject": "Re: invoice", "age_hours": 9}]}),
            None)
        rows2, _ = brief.collect_mail(None, keyed)
        inbox2 = cb.buckets(NOW, {"mail": (rows2, None)}, _tree(tmp_path))["inbox"]
        assert len({i["key"] for i in inbox2}) == 2, "a real thread id stopped working"


class TestHisSideCarriesItsDates:
    """Founder, 2026-09-03: *"a learning from the [a retainer client] fiasco -- they said I
    wasn't doing things and I've actually been waiting on deliverables for weeks."*
    A row that renders a promise with no date cannot tell a promise made yesterday
    from one made in July, so it cannot settle that argument. Scoped by him to HIS
    side only one message later; there is deliberately no reader for their promises."""

    def test_the_phrase_carries_when_he_said_it_and_how_long_ago(self):
        now = dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc)
        phrase = cb.my_side_phrase(
            {"said_on": "2026-08-18T21:47:47+00:00", "due": "2026-08-31",
             "last_touch": "2026-09-02"}, now)
        assert "said 2026-08-18" in phrase
        assert "(16d ago)" in phrase
        assert "due 2026-08-31" in phrase
        assert "last touch 2026-09-02" in phrase

    def test_a_missing_date_is_omitted_never_rendered_as_unknown(self):
        now = dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc)
        phrase = cb.my_side_phrase({"said_on": "2026-08-18", "due": None,
                                    "last_touch": None}, now)
        assert "due" not in phrase and "last touch" not in phrase
        assert "said 2026-08-18" in phrase

    def test_an_unparseable_date_never_renders_as_zero_days(self):
        """0d would read as "today" and be a lie about how long he has waited."""
        assert cb._days("not-a-date", dt.datetime.now(dt.timezone.utc)) is None
        phrase = cb.my_side_phrase({"said_on": "not-a-date"},
                                   dt.datetime.now(dt.timezone.utc))
        assert "0d" not in phrase

    def test_only_OPEN_promises_count(self, tmp_path):
        """A resolved promise is not something he still owes. Surfacing one would
        recreate the "you did not do this" claim the dates exist to defend against."""
        paths = _tree(tmp_path, commitments="\n".join([
            json.dumps({"slug": "acme", "state": "resolved",
                        "extracted_at": "2026-01-01T00:00:00+00:00"}),
            json.dumps({"slug": "acme", "state": "open",
                        "extracted_at": "2026-08-20T00:00:00+00:00", "due": None}),
        ]), clients={"clients": []})
        got, err = cb.read_my_side(dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc), paths)
        assert err is None
        assert got["acme"]["said_on"].startswith("2026-08-20")

    def test_the_oldest_open_promise_is_the_one_shown(self, tmp_path):
        """Two open promises to one client: the OLDEST is the exposure, because that
        is the number a client would quote back at him."""
        paths = _tree(tmp_path, commitments="\n".join([
            json.dumps({"slug": "acme", "state": "open",
                        "extracted_at": "2026-08-29T00:00:00+00:00"}),
            json.dumps({"slug": "acme", "state": "open",
                        "extracted_at": "2026-07-04T00:00:00+00:00"}),
        ]), clients={"clients": []})
        got, _ = cb.read_my_side(dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc), paths)
        assert got["acme"]["said_on"].startswith("2026-07-04")

    def test_one_corrupt_line_never_voids_the_book(self, tmp_path):
        paths = _tree(tmp_path, commitments="\n".join([
            "{ not json",
            json.dumps({"slug": "acme", "state": "open",
                        "extracted_at": "2026-08-20T00:00:00+00:00"}),
        ]), clients={"clients": []})
        got, err = cb.read_my_side(dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc), paths)
        assert err is None and "acme" in got

    def test_the_registry_is_a_lookup_and_is_never_enumerated_onto_the_board(self, tmp_path):
        """clients.json is 162 rows, ~150 of them cold prospects with no rate and no
        next_touch. Walking it would put every one of them on his morning board."""
        paths = _tree(tmp_path, clients={"clients": [
            {"slug": "ghost-%d" % i, "name": "Ghost Prospect %d" % i,
             "last_touch": None} for i in range(150)]})
        b = cb.buckets(NOW, {}, paths)
        card = paths["card"].read_text(encoding="utf-8")
        # Only rows sourced from the CARD are client rows; gtm/error rows are not.
        client_rows = [r for r in b["top_of_mind"] + b["this_week"]
                       if r["key"].startswith(("client:", "reach:"))]
        assert client_rows, "fixture produced no client rows"
        for r in client_rows:
            bare = r["title"].split(" ", 1)[-1] if r["title"][:1] in "🔴🟡🟢⚪📞🟠" else r["title"]
            assert bare in card, f"{bare!r} reached the board without being on the card"
        assert not any("Ghost Prospect" in r["title"]
                       for r in b["top_of_mind"] + b["this_week"] + b["inbox"]), (
            "the registry was enumerated onto the board")


class TestThisWeekHasASourceAtLast:
    """Founder, 2026-09-03: *"This week should be this week's GTM moves and
    deliverables that are coming up."* Before this the section had NO source and
    carried a description copied off a reference board describing a Sunday planning
    ritual he does not have, so it would have stayed empty while calling itself
    "the plan"."""

    def test_the_top_of_mind_gtm_step_is_never_also_in_this_week(self, tmp_path):
        """Top of Mind takes the top-ranked founder step; This Week takes the rest.
        One step on two surfaces teaches him the sections mean the same thing."""
        paths = _tree(tmp_path, gtm={"rows": {
            "1.1": {"id": "1.1", "action": "the lead", "performer": "founder",
                    "state": "ready", "rank": 1},
            "1.2": {"id": "1.2", "action": "the second", "performer": "founder",
                    "state": "ready", "rank": 2},
        }})
        b = cb.buckets(NOW, {}, paths)
        top = {r["key"] for r in b["top_of_mind"]}
        week = {r["key"] for r in b["this_week"]}
        assert "gtm:1.1" in top and "gtm:1.2" in week
        assert not (top & week), f"a row is on both surfaces: {top & week}"

    def test_mechanism_steps_never_reach_this_week(self, tmp_path):
        """The machine's own steps belong in the engineer's queue. 51 of 57 rows are
        `mechanism`; letting them through would put the build plan back on his board,
        which is the complaint this whole board exists to answer."""
        paths = _tree(tmp_path, gtm={"rows": {
            "9.9": {"id": "9.9", "action": "a machine job", "performer": "mechanism",
                    "state": "ready", "rank": 1},
        }})
        rows, err, _healthy = cb.read_week(NOW, paths)
        assert err is None
        assert not any(r["key"] == "gtm:9.9" for r in rows)

    def test_a_deliverable_due_inside_the_week_is_carried(self, tmp_path):
        due = (NOW.date() + dt.timedelta(days=3)).isoformat()
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": due,
             "promise": "send the audit"}), clients={"clients": []})
        rows, _, _healthy = cb.read_week(NOW, paths)
        hit = [r for r in rows if r["key"] == "due:c1"]
        assert hit, "a deliverable due in 3 days never reached This Week"
        assert "(3d)" in hit[0]["detail"]

    def test_an_OVERDUE_deliverable_is_NOT_repeated_here(self, tmp_path):
        """It is already red in Top of Mind. Two surfaces for one fact is how a
        section stops meaning anything."""
        past = (NOW.date() - dt.timedelta(days=4)).isoformat()
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": past,
             "promise": "send the audit"}), clients={"clients": []})
        rows, _, _healthy = cb.read_week(NOW, paths)
        assert not any(r["key"] == "due:c1" for r in rows)

    def test_a_deliverable_beyond_the_week_is_not_this_weeks_problem(self, tmp_path):
        far = (NOW.date() + dt.timedelta(days=cb.WEEK_DAYS + 1)).isoformat()
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": far,
             "promise": "send the audit"}), clients={"clients": []})
        rows, _, _healthy = cb.read_week(NOW, paths)
        assert not any(r["key"] == "due:c1" for r in rows)

    def test_a_junk_due_date_is_skipped_not_crashed_on(self, tmp_path):
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": "soon-ish",
             "promise": "send the audit"}), clients={"clients": []})
        rows, err, _healthy = cb.read_week(NOW, paths)
        assert err is None
        assert not any(r["key"] == "due:c1" for r in rows)


class TestARowHeNeverTouchedFollowsItsHealth:
    """Codex round 6 (major): `Bucket` was written ONLY on create, so a client that
    went red -> green stayed in Top of Mind forever and a human had to move it by hand.

    The promise the module makes is narrower than the rule it implemented: HIS drag
    wins, not every stale value the machine itself painted. Told apart the way
    `gtm_board.apply_board_moves` does it -- record what THIS module last wrote, and a
    live value that differs from that record was put there by a human, because nothing
    else writes that column.
    """

    ITEM = {"key": "k1", "title": "t", "detail": "d", "scope": "card"}

    @staticmethod
    def _page(live_bucket, note):
        return {"id": "p1", "properties": {
            "Bucket": {"select": ({"name": live_bucket} if live_bucket else None)},
            "Notes": {"rich_text": [{"plain_text": note}]}}}

    def _patch(self, monkeypatch, live_bucket, note, computed_key, item=None):
        """Paint over ONE existing row; return the properties it PATCHed."""
        item = item or dict(self.ITEM)
        have = {board_rows.item_id(computed_key, item): self._page(live_bucket, note)}
        monkeypatch.setattr(board_rows, "existing_rows", lambda *a, **k: have)
        calls = []
        monkeypatch.setattr(
            board_rows, "_request",
            lambda token, method, path, body=None, opener=None, budget=None:
            calls.append((method, body)) or {})
        buckets = {"top_of_mind": [], "this_week": [], "inbox": [],
                   "healthy_scopes": {"card"}}
        buckets[computed_key] = [item]
        board_rows.paint(buckets, "t", "db")
        patches = [b for m, b in calls if m == "PATCH"]
        assert len(patches) == 1, calls
        return patches[0]["properties"]

    @staticmethod
    def _note(props):
        return "".join(t["text"]["content"] for t in props["Notes"]["rich_text"])

    def test_a_row_we_painted_and_he_never_moved_gets_its_new_bucket(self, monkeypatch):
        """The finding. Live value equals what we last painted, so nobody has touched
        it, so the computed health is free to move it."""
        props = self._patch(monkeypatch, "Top of Mind",
                            "d\nscope=card\nbucket=Top of Mind", "this_week")
        assert props["Bucket"]["select"]["name"] == "This Week"
        assert "bucket=This Week" in self._note(props)

    def test_a_row_he_DRAGGED_is_not_moved_back(self, monkeypatch):
        """Live Inbox against a record of Top of Mind: nothing but a human puts it
        there. The row is pinned from this run on."""
        props = self._patch(monkeypatch, "Inbox",
                            "d\nscope=card\nbucket=Top of Mind", "top_of_mind")
        assert "Bucket" not in props
        assert "pinned=1" in self._note(props)

    def test_and_it_STAYS_pinned_on_the_next_run(self, monkeypatch):
        """The negative control, and the reason a straight port of gtm_board is wrong
        here. There a drag CHANGES the computed state, so adopting the live value as
        the new baseline is correct. Here health is computed from the card and a drag
        cannot change it, so adopting would agree with the record next morning and
        move the row back one run later. A pinned row is pinned for good."""
        props = self._patch(monkeypatch, "Inbox",
                            "d\nscope=card\nbucket=Inbox\npinned=1", "top_of_mind")
        assert "Bucket" not in props
        assert "pinned=1" in self._note(props)

    def test_a_row_written_before_this_change_is_moved_ONCE(self, monkeypatch):
        """Cold start: no record, and the live bucket disagrees with the computed one.
        Nothing on disk can tell his drag from our own stale paint, so the bet is made
        toward the reversible side. Moving a row he dragged costs one drag; pinning a
        row he never touched is silent, permanent, and leaves the board wrong."""
        props = self._patch(monkeypatch, "Top of Mind", "d\nscope=card", "this_week")
        assert props["Bucket"]["select"]["name"] == "This Week"
        assert "pinned=1" not in self._note(props)

    def test_and_his_drag_back_pins_it_for_good(self, monkeypatch):
        """The other half of that bet, and what makes it cost exactly one drag."""
        props = self._patch(monkeypatch, "Inbox",
                            "d\nscope=card\nbucket=This Week", "this_week")
        assert "Bucket" not in props
        assert "pinned=1" in self._note(props)

    def test_a_cold_row_that_already_agrees_is_adopted_not_pinned(self, monkeypatch):
        """Nothing is lost by recording a baseline that matches what is on screen."""
        props = self._patch(monkeypatch, "This Week", "d\nscope=card", "this_week")
        assert "bucket=This Week" in self._note(props)
        assert "pinned=1" not in self._note(props)

    def test_a_row_in_NO_bucket_is_given_one(self, monkeypatch):
        """His three views all filter on Bucket, so a row with none is on no view at
        all. Leaving it invisible forever is worse than placing it."""
        props = self._patch(monkeypatch, "", "d\nscope=card", "top_of_mind")
        assert props["Bucket"]["select"]["name"] == "Top of Mind"

    def test_Status_is_never_rewritten_on_an_existing_row(self, monkeypatch):
        """He marks rows done. A refresh that resets Status to Not started would undo
        that every morning."""
        props = self._patch(monkeypatch, "Top of Mind",
                            "d\nscope=card\nbucket=Top of Mind", "this_week")
        assert "Status" not in props

    def test_the_machinery_lines_survive_a_long_detail(self, monkeypatch):
        """`scope=` and `bucket=` live at the END of the note and the note is capped.
        A long detail used to be able to push them off, which reads back as an unknown
        scope (kept forever) and an unknown bucket (pinned forever) with no error."""
        item = dict(self.ITEM, detail="x" * 4000, done="y" * 400)
        props = self._patch(monkeypatch, "Top of Mind",
                            "d\nscope=card\nbucket=Top of Mind", "this_week", item=item)
        note = self._note(props)
        assert len(note) <= 1900
        assert "scope=card" in note and "bucket=This Week" in note


class TestAWeeklyRowLeavesWhenItsWorkDoes:
    """Codex round 6 (major): `read_week` emits `week:gtm` and `week:due`, and neither
    scope was ever reported healthy, so the painter could not archive inside them. A
    delivered commitment or a finished GTM step sat on the board forever.

    The rule the other scopes follow holds here: healthy means THIS SOURCE ANSWERED
    THIS RUN. An unreadable GTM queue or commitment book authorises nothing.
    """

    def _healthy_tree(self, tmp_path):
        due = (NOW.date() + dt.timedelta(days=3)).isoformat()
        return _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": due,
             "promise": "send the audit"}), clients={"clients": []})

    def test_both_week_scopes_are_healthy_when_both_sources_read(self, tmp_path):
        b = cb.buckets(NOW, {}, self._healthy_tree(tmp_path))
        assert {"week:gtm", "week:due"} <= b["healthy_scopes"]

    def test_an_unreadable_gtm_queue_does_NOT_authorise_archiving_week_gtm(self, tmp_path):
        paths = self._healthy_tree(tmp_path)
        paths["gtm"].write_text("{not json", encoding="utf-8")
        b = cb.buckets(NOW, {}, paths)
        assert "week:gtm" not in b["healthy_scopes"]
        assert "week:due" in b["healthy_scopes"], "one broken source must not mute the other"

    def test_an_unreadable_commitment_book_does_NOT_authorise_archiving_week_due(self, tmp_path):
        paths = self._healthy_tree(tmp_path)
        paths["commitments"].unlink()
        paths["commitments"].mkdir()          # readable path, unreadable file
        b = cb.buckets(NOW, {}, paths)
        assert "week:due" not in b["healthy_scopes"]
        assert "week:gtm" in b["healthy_scopes"]

    def test_an_ABSENT_commitment_book_authorises_nothing_either(self, tmp_path):
        """OFF, not broken: no book is a fact and not a failure, so no error row. It
        still says NOTHING about rows written when the book existed, and nothing is
        not "they are gone"."""
        paths = _tree(tmp_path)
        b = cb.buckets(NOW, {}, paths)
        assert "week:due" not in b["healthy_scopes"]
        assert not any("COULD NOT READ" in r["title"] for r in b["this_week"])

    def test_every_scope_the_producer_emits_can_be_archived_when_it_is_healthy(self, tmp_path):
        """The structural check, not a list of the scopes that exist today. Round 6
        found two scopes with no health decision at all; this fails on the third."""
        b = cb.buckets(NOW, {"mail": ([_brief().Row("a thread", "mail:t1")], None)},
                       self._healthy_tree(tmp_path))
        emitted = {r.get("scope") for r in b["top_of_mind"] + b["this_week"] + b["inbox"]}
        assert emitted, "the fixture produced no rows at all"
        assert emitted <= b["healthy_scopes"], (
            f"scopes with no health decision: {sorted(emitted - b['healthy_scopes'])}")

    def test_an_error_row_is_archived_once_its_source_recovers(self, tmp_path):
        """The same hole, in the rows that REPORT the hole. A COULD NOT READ row is
        scoped `week` or `myside`, and neither was ever healthy, so the apology
        outlived the outage and nothing could clear it."""
        paths = self._healthy_tree(tmp_path)
        paths["gtm"].write_text("{not json", encoding="utf-8")
        broken = cb.buckets(NOW, {}, paths)
        assert any(r["scope"] == "week" for r in broken["this_week"])
        assert "week" not in broken["healthy_scopes"]

        paths = self._healthy_tree(tmp_path)          # source recovers
        fixed = cb.buckets(NOW, {}, paths)
        assert not any(r["scope"] == "week" for r in fixed["this_week"])
        assert "week" in fixed["healthy_scopes"], "the apology row can never be cleared"
        assert "myside" in fixed["healthy_scopes"]


class TestRound7:
    """Two findings the round-7 review raised against surfaces round 6 had not touched."""

    def test_an_answer_them_row_is_today_in_BOTH_tables(self, tmp_path):
        """PRIORITY_BY_HEALTH called 🟠 a P0 while the split sent it to This Week, so
        one module said today and not-today about the same row.

        Pins consistency between two tables in this file, NOT a producer behaviour:
        `state_card.py` emits only 🔴🟡🟢⚪📞 and `board_sync.py` is where 🟠 lives. The
        reviewer flagged that too, which is why this test says so rather than implying
        the dot arrives today.
        """
        card = ("# TODAY CARD\n"
                '🟠 *Northwind Design* · you said "reply to them" — not sent\n')
        b = cb.buckets(NOW, {}, _tree(tmp_path, card=card))
        top = [r for r in b["top_of_mind"] if "Northwind" in r["title"]]
        assert top, "an 🟠 row landed outside Top of Mind while being called P0"
        assert top[0]["priority"] == cb.PRIORITY_BY_HEALTH["🟠"] == "P0"

    def test_a_row_over_the_cap_is_counted_and_said_out_loud(self, tmp_path, monkeypatch):
        """The cap was silent, and the read-back structurally cannot see it: `wanted`
        has lost the row before the count is taken. The inbox alone can produce 41."""
        rows = [{"key": f"k{i}", "title": f"t{i}", "detail": "", "scope": "card"}
                for i in range(board_rows.BUDGET_ROWS + 3)]
        counts = board_rows.paint(
            {"top_of_mind": [], "this_week": [], "inbox": rows,
             "healthy_scopes": {"card"}}, "t", "db",
            opener=lambda *a, **k: io.BytesIO(b'{"results": [], "has_more": false}'))
        assert counts["wanted"] == board_rows.BUDGET_ROWS
        assert counts["over_cap"] == 3

    def test_and_the_brief_line_names_the_drop(self, tmp_path, monkeypatch):
        (tmp_path / "tok").write_text("t")
        (tmp_path / "db").write_text("db1")
        monkeypatch.setattr(board_rows, "LOCK_FILE", tmp_path / "board.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        rows = [{"key": f"k{i}", "title": f"t{i}", "detail": "", "scope": "card"}
                for i in range(board_rows.BUDGET_ROWS + 1)]
        monkeypatch.setattr(board_rows.consulting_board, "buckets", lambda *a, **k: {
            "error": None, "top_of_mind": [], "this_week": [], "inbox": rows,
            "healthy_scopes": {"card"}})

        made = []

        def opener(req, timeout):
            if "/databases/" in req.full_url:
                results = [{"properties": {
                    "Item id": {"rich_text": [{"plain_text": i}]},
                    "Notes": {"rich_text": [{"plain_text": "scope=card"}]}}} for i in made]
                return io.BytesIO(json.dumps(
                    {"results": results, "has_more": False}).encode())
            made.append(board_rows.item_id("inbox", rows[len(made)]))
            return io.BytesIO(b'{"id": "p1"}')

        out, err = board_rows.collect(NOW, {}, opener=opener,
                                      token_file=tmp_path / "tok", db_file=tmp_path / "db")
        assert err is None, err
        assert "1 row(s) over the" in out[0], out


class TestEveryPersonOnTheCardReachesTheBoard:
    """Codex round 8 (major): the real producer emitted four people to reach out and
    this reader parsed ONE of them, at exit 0, with the board reporting success.

    Two defects in one line-shape, and the first is a scar this file already carries.
    `_CLIENT_LINE` was taught to tolerate the `*THE MOVE*` prefix after it silently
    dropped the top-ranked client; the reach line is its sibling and was never
    hardened, so when the top-ranked row is a reach-out (which is what the card looks
    like on a day with no red clients) the whole line failed to match. The second is
    the `then:` continuation, which the card packs with every remaining person and
    this reader read as exactly one.

    CAPTURED, not typed. The fixture below is the verbatim output of
    `state_card.build_card` for four fire-temperature prospects, run 2026-09-03. It
    cannot be imported here (`test_boundary.py` forbids this package from reaching into
    the consulting pipeline), and a hand-written approximation of a producer's format
    is what let this ship: every earlier fixture in this file puts `*THE MOVE*` on a
    CLIENT line, so no test ever saw the shape the producer actually emits.
    """

    CAPTURED = (
        "*Your book today* · 0 active · 0 in proposal · 4 to reach out · 2026-09-03\n"
        "*THE MOVE* 📞 *4 to reach out* — 🔥 Alpha (fire, Alpha context): contact Alpha\n"
        "     then: 🔥 Beta (fire) · 🔥 Gamma (fire) · 🔥 Delta (fire)\n"
    )

    def _rows(self, tmp_path):
        paths = _tree(tmp_path, card=self.CAPTURED)
        rows, err = cb.read_card(paths)
        assert err is None, err
        return rows

    def test_all_four_are_parsed(self, tmp_path):
        names = [r["name"] for r in self._rows(tmp_path)]
        assert sorted(names) == ["Alpha", "Beta", "Delta", "Gamma"], names

    def test_the_lead_person_is_not_the_one_dropped(self, tmp_path):
        """Alpha carries `*THE MOVE*`, which is the card's own ranking: the person it
        drops is the most important one on the line."""
        assert "Alpha" in [r["name"] for r in self._rows(tmp_path)]

    def test_each_one_is_its_own_board_row(self, tmp_path):
        b = cb.buckets(NOW, {}, _tree(tmp_path, card=self.CAPTURED))
        keys = [r["key"] for r in b["top_of_mind"] if r["key"].startswith("reach:")]
        assert len(set(keys)) == 4, keys


class TestRateLimitedNotionIsRetriedNotAbandoned:
    """Codex round 8 (major): Notion documents ~3 requests/second and asks clients to
    honour `Retry-After` on 429. This painter sends up to 40 sequential mutations with
    no pacing and no retry, so an ordinary paint could abort part-written and report
    the morning degraded. The next run reconciles the board, so the damage is alert
    noise rather than corruption, which is why this is a retry and not a rewrite.
    """

    @staticmethod
    def _opener(fail_on, retry_after="0"):
        calls = []

        def opener(req, timeout):
            calls.append(req.full_url)
            if len(calls) == fail_on:
                raise urllib.error.HTTPError(
                    req.full_url, 429, "rate_limited", {"Retry-After": retry_after},
                    io.BytesIO(b"{}"))
            if "/query" in req.full_url:
                return io.BytesIO(b'{"results": [], "has_more": false}')
            return io.BytesIO(b'{"id": "p1"}')
        opener.calls = calls
        return opener

    def _rows(self, n=4):
        return [{"key": f"mail:{i}", "title": f"t{i}", "detail": "",
                 "scope": "inbox:Gmail"} for i in range(n)]

    def test_a_429_mid_paint_is_retried_and_the_paint_completes(self):
        opener = self._opener(fail_on=4)
        counts = board_rows.paint(
            {"top_of_mind": [], "this_week": [], "inbox": self._rows(),
             "healthy_scopes": {"inbox:Gmail"}}, "t", "db", opener=opener)
        assert counts["created"] == 4, counts
        assert len(opener.calls) == 6, "the rejected write was not retried"

    def test_a_retry_never_outlives_the_budget(self):
        """The budget is the whole point of the round-4 fix: nothing may write after
        the brief has moved on. A Retry-After longer than what is left is refused
        rather than slept through."""
        opener = self._opener(fail_on=2, retry_after="60")
        # Above WRITE_RESERVE_S so a write is actually attempted, and below the
        # clamped Retry-After (5s) so the wait cannot fit, which is the condition under
        # test. Not a fraction of a second: a budget that can expire before the first
        # request turns this into a load-sensitive coin flip, and a flaky negative
        # control is worse than none.
        budget = board_rows._Budget(board_rows.WRITE_RESERVE_S + 2.0)
        started = time.monotonic()
        # EITHER refusal is correct: the retry declines because the wait does not fit,
        # or the budget was already spent and the next request refuses. The exception
        # TYPE is not the property -- raising is what the unfixed code did too. The
        # CLOCK is the property, and it separates the fix from the defect on its own
        # (removing the budget check makes this same assertion fail after five seconds).
        with pytest.raises((urllib.error.HTTPError, board_rows.Cancelled)):
            board_rows.paint(
                {"top_of_mind": [], "this_week": [], "inbox": self._rows(1),
                 "healthy_scopes": {"inbox:Gmail"}}, "t", "db",
                opener=opener, budget=budget)
        assert time.monotonic() - started < 1.0, "it slept through the Retry-After"

    def test_a_permanently_rate_limited_endpoint_gives_up(self):
        """A retry loop with no cap is how a 15-second budget becomes a hung job."""
        calls = []

        def opener(req, timeout):
            calls.append(req.full_url)
            if "/query" in req.full_url:
                return io.BytesIO(b'{"results": [], "has_more": false}')
            raise urllib.error.HTTPError(req.full_url, 429, "rate_limited",
                                         {"Retry-After": "0"}, io.BytesIO(b"{}"))
        with pytest.raises(urllib.error.HTTPError):
            board_rows.paint(
                {"top_of_mind": [], "this_week": [], "inbox": self._rows(1),
                 "healthy_scopes": {"inbox:Gmail"}}, "t", "db", opener=opener)
        assert len(calls) <= 1 + board_rows.RATE_LIMIT_RETRIES + 1, calls


class TestTheBoardDoesNotRewriteWhatItAlreadyHolds:
    """Round 9 (major): BUDGET_ROWS is per BUCKET, so a full paint could ask for 120
    sequential mutations inside a 15-second budget, against an API documented at
    roughly three requests a second.

    The answer is not a second invented cap. Almost every one of those writes changed
    nothing, and the page needed to prove that has ALREADY been read.
    """

    ITEM = {"key": "k1", "title": "t", "detail": "d", "scope": "card",
            "domain": "Consulting"}

    def _painted_page(self, bucket="Top of Mind"):
        """A row exactly as this painter would have left it last run."""
        props = board_rows._properties(self.ITEM, bucket,
                                       board_rows.item_id("top_of_mind", self.ITEM),
                                       include_bucket=True, status="Not started")
        page = {"id": "p1", "properties": dict(props)}
        page["properties"]["Bucket"] = {"select": {"name": bucket}}
        return page

    def _paint(self, page, monkeypatch, budget=None):
        have = {board_rows.item_id("top_of_mind", self.ITEM): page}
        monkeypatch.setattr(board_rows, "existing_rows", lambda *a, **k: have)
        calls = []
        monkeypatch.setattr(
            board_rows, "_request",
            lambda token, method, path, body=None, opener=None, budget=None:
            calls.append(method) or {})
        counts = board_rows.paint(
            {"top_of_mind": [dict(self.ITEM)], "this_week": [], "inbox": [],
             "healthy_scopes": {"card"}}, "t", "db", budget=budget)
        return counts, calls

    def test_an_unchanged_row_costs_no_request_at_all(self, monkeypatch):
        counts, calls = self._paint(self._painted_page(), monkeypatch)
        assert calls == [], f"a row that already holds its values was rewritten: {calls}"
        assert counts["unchanged"] == 1 and counts["updated"] == 0

    def test_but_a_changed_detail_is_still_written(self, monkeypatch):
        """The negative control. A skip that never writes is not an optimisation, it is
        an outage, so the same fixture with one moved value must produce a PATCH."""
        page = self._painted_page()
        page["properties"]["Notes"] = {"rich_text": [{"plain_text": "something else"}]}
        counts, calls = self._paint(page, monkeypatch)
        assert calls == ["PATCH"] and counts["updated"] == 1

    def test_an_unreadable_property_is_written_not_assumed_to_match(self, monkeypatch):
        page = self._painted_page()
        page["properties"]["Domain"] = {"some_new_notion_shape": True}
        _counts, calls = self._paint(page, monkeypatch)
        assert calls == ["PATCH"], "an unrecognised property shape was assumed equal"

    def test_a_spent_write_budget_defers_rather_than_running_past_it(self, monkeypatch):
        page = self._painted_page()
        page["properties"]["Notes"] = {"rich_text": [{"plain_text": "changed"}]}
        budget = board_rows._Budget(board_rows.WRITE_RESERVE_S / 2)
        counts, calls = self._paint(page, monkeypatch, budget=budget)
        assert calls == [], "it wrote with no time left to prove the write"
        assert counts["deferred"] == 1

    def test_a_deferred_CREATE_is_not_expected_by_the_read_back(self, tmp_path, monkeypatch):
        """A row we never created is not on the board. Counting it as expected would
        report a read-back mismatch about a row we deliberately did not write, which is
        the false-alarm class round 3 already charged for once."""
        (tmp_path / "tok").write_text("t")
        (tmp_path / "db").write_text("db1")
        monkeypatch.setattr(board_rows, "LOCK_FILE", tmp_path / "board.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        monkeypatch.setattr(board_rows.consulting_board, "buckets", lambda *a, **k: {
            "error": None, "card_error": None, "top_of_mind": [dict(self.ITEM)],
            "this_week": [], "inbox": [], "healthy_scopes": {"card"}})
        monkeypatch.setattr(board_rows, "WRITE_RESERVE_S", 999.0)   # nothing may write
        rows, err = board_rows.collect(
            NOW, {}, opener=lambda *a, **k: io.BytesIO(
                b'{"results": [], "has_more": false}'),
            token_file=tmp_path / "tok", db_file=tmp_path / "db")
        assert err is None, err
        assert "1 row(s) deferred" in rows[0], rows


class TestTheAllowlistIsHisChoiceAndFailsCLOSED:
    """Codex round 7 (minor), twice over. The founder's narrowing -- "I only want you
    to look in the AI chat channel" -- could be widened by an IO error, and could not
    name a DM at all."""

    def _tree(self, tmp_path, groups=(), chats=()):
        import json as _json

        def opener(req, timeout):
            url = req.full_url.split("?")[0]
            if url.endswith("/users/me"):
                return io.BytesIO(_json.dumps({"response": {"user_id": "me"}}).encode())
            if "/groups/" in url and url.endswith("/messages"):
                return io.BytesIO(_json.dumps(
                    {"response": {"messages": [{"user_id": "them"}]}}).encode())
            body = list(groups) if url.endswith("/groups") else list(chats)
            return io.BytesIO(_json.dumps({"response": body}).encode())
        return opener

    def test_an_unreadable_allowlist_refuses_rather_than_widening(self, tmp_path, monkeypatch):
        path = tmp_path / "groupme-channels"
        path.write_text("g1\n", encoding="utf-8")
        path.chmod(0o000)
        try:
            monkeypatch.setattr(gm, "CHANNELS_FILE", path)
            monkeypatch.setattr(gm, "load_token", lambda: "t")
            monkeypatch.setattr(gm, "waiting",
                                lambda *a, **k: gm.load_allowlist() and [])
            rows, err = gm.collect(NOW, {})
        finally:
            path.chmod(0o600)
        assert rows == [] and err, "an unreadable allowlist read as no allowlist"
        assert "allowlist" in err

    def test_an_ABSENT_allowlist_still_means_no_choice_recorded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gm, "CHANNELS_FILE", tmp_path / "not-there")
        assert gm.load_allowlist() is None

    def test_a_DM_he_NAMED_is_carried(self, tmp_path, monkeypatch):
        """It used to skip /chats entirely whenever an allowlist existed, so a DM peer
        id in the file matched nothing and the file said nothing about ignoring it."""
        monkeypatch.setattr(gm, "CHANNELS_FILE", tmp_path / "ch")
        (tmp_path / "ch").write_text("u77\n", encoding="utf-8")
        chats = [{"other_user": {"id": "u77", "name": "Dana"},
                  "last_message": {"user_id": "u77", "created_at": 10 ** 12,
                                   "text": "hi"}}]
        rows = gm.waiting(NOW, "t", self._tree(tmp_path, chats=chats))
        assert [r["id"] for r in rows] == ["u77"], rows

    def test_and_a_DM_he_did_not_name_is_not(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gm, "CHANNELS_FILE", tmp_path / "ch")
        (tmp_path / "ch").write_text("u77\n", encoding="utf-8")
        chats = [{"other_user": {"id": "u99", "name": "Someone"},
                  "last_message": {"user_id": "u99", "created_at": 10 ** 12,
                                   "text": "hi"}}]
        assert gm.waiting(NOW, "t", self._tree(tmp_path, chats=chats)) == []


class TestABookWeCouldNotFullyReadArchivesNothing:
    def test_a_malformed_line_withholds_the_week_due_scope(self, tmp_path):
        """Round 10 (major), and it is my round-7 fix's own hole. `week:due` was
        declared healthy after the loop finished, but the loop `continue`s past a line
        that will not parse -- so the painter was authorised to archive the row for the
        very deliverable the corrupt line described."""
        due = (NOW.date() + dt.timedelta(days=3)).isoformat()
        paths = _tree(tmp_path, commitments="\n".join([
            "{ not json at all",
            json.dumps({"id": "c1", "slug": "acme", "state": "open", "due": due,
                        "promise": "send the audit"}),
        ]), clients={"clients": []})
        _rows, err, healthy = cb.read_week(NOW, paths)
        assert "week:due" not in healthy
        assert err and "unreadable line" in err

    def test_a_clean_book_still_authorises_it(self, tmp_path):
        due = (NOW.date() + dt.timedelta(days=3)).isoformat()
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": due,
             "promise": "send the audit"}), clients={"clients": []})
        _rows, err, healthy = cb.read_week(NOW, paths)
        assert err is None and "week:due" in healthy

    def test_a_junk_DUE_DATE_is_still_only_a_skipped_row(self, tmp_path):
        """Deliberately NOT the same thing. The row parsed; one field in it did not.
        Withholding the whole scope for that would keep every deliverable row on the
        board forever over one typo, which is the over-application I made first and
        backed out."""
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": "soon-ish",
             "promise": "send the audit"}), clients={"clients": []})
        _rows, err, healthy = cb.read_week(NOW, paths)
        assert err is None and "week:due" in healthy

    def test_no_allowlist_file_reads_everything_ON_PURPOSE(self, tmp_path, monkeypatch):
        """Round 10 called this a silent widening. Kept, as a decision rather than an
        oversight: nothing distinguishes a vanished file from a machine that never had
        one, and requiring a marker would silence GroupMe on every machine without the
        file. Reporting too much is visible in his own output; reporting nothing is the
        failure the whole brief exists to prevent."""
        monkeypatch.setattr(gm, "CHANNELS_FILE", tmp_path / "absent")
        assert gm.load_allowlist() is None


class TestACappedRowIsNotAnAbsentRow:
    """Round 11 (major): rows trimmed by BUDGET_ROWS never entered `wanted`, so the
    archive loop saw their live pages inside a HEALTHY scope and archived them. A
    producer emitting one row too many destroyed a row he had dragged and pinned."""

    def test_a_row_over_the_cap_is_kept_not_archived(self, monkeypatch):
        rows = [{"key": f"mail:{i}", "title": f"t{i}", "detail": "",
                 "scope": "inbox:Gmail"} for i in range(board_rows.BUDGET_ROWS + 2)]
        over = rows[board_rows.BUDGET_ROWS:]
        have = {}
        for item in over:
            iid = board_rows.item_id("inbox", item)
            have[iid] = {"id": f"p-{iid}", "properties": {
                "Notes": {"rich_text": [{"plain_text": "scope=inbox:Gmail"}]}}}
        monkeypatch.setattr(board_rows, "existing_rows", lambda *a, **k: have)
        calls = []
        monkeypatch.setattr(
            board_rows, "_request",
            lambda token, method, path, body=None, opener=None, budget=None:
            calls.append((method, body)) or {})
        counts = board_rows.paint(
            {"top_of_mind": [], "this_week": [], "inbox": rows,
             "healthy_scopes": {"inbox:Gmail"}}, "t", "db")
        archived = [b for m, b in calls if b == {"archived": True}]
        assert archived == [], f"a capped row's page was archived: {archived}"
        assert counts["archived"] == 0 and counts["kept"] == 2

    def test_but_a_row_whose_work_is_DONE_is_still_archived(self, monkeypatch):
        """The negative control. If nothing is ever archived the board only grows,
        which is the state this painter was built to end."""
        gone = board_rows.item_id("inbox", {"key": "mail:old"})
        have = {gone: {"id": "p1", "properties": {
            "Notes": {"rich_text": [{"plain_text": "scope=inbox:Gmail"}]}}}}
        monkeypatch.setattr(board_rows, "existing_rows", lambda *a, **k: have)
        calls = []
        monkeypatch.setattr(
            board_rows, "_request",
            lambda token, method, path, body=None, opener=None, budget=None:
            calls.append(body) or {})
        counts = board_rows.paint(
            {"top_of_mind": [], "this_week": [], "inbox": [],
             "healthy_scopes": {"inbox:Gmail"}}, "t", "db")
        assert {"archived": True} in calls and counts["archived"] == 1


class TestRound12:
    QUIET = "*Your book today* · 4 active · 0 in proposal · 0 to reach out · 2026-09-03\n"

    def test_a_quiet_morning_is_not_a_format_change(self, tmp_path):
        """Every client green or waiting on THEM emits a header and no client lines.
        Calling that broken put a P0 alarm row on the board every quiet day, which is
        the wolf-cry that costs the real alert later."""
        rows, err = cb.read_card(_tree(tmp_path, card=self.QUIET))
        assert rows == [] and err is None

    def test_but_a_card_with_no_header_at_all_is_still_a_format_change(self, tmp_path):
        """The negative control. If both cases return None the reader can no longer
        tell it has drifted from its writer, which is what the original check was for."""
        rows, err = cb.read_card(_tree(tmp_path, card="something else entirely\n"))
        assert rows == [] and err and "format changed" in err

    def test_and_a_quiet_card_raises_no_alarm_row(self, tmp_path):
        b = cb.buckets(NOW, {}, _tree(tmp_path, card=self.QUIET))
        assert not any(r["scope"] == cb.CARD_ALARM for r in b["top_of_mind"])
        # The scope is deliberately NOT healthy here; round 14 explains why, and
        # test_a_card_that_parses_to_nothing_never_archives_his_rows pins it.

    def test_the_producers_plus_N_more_tail_is_not_a_person(self, tmp_path):
        """A count is not a contact. The split handed the producer's own summary to
        the person extractor, so the board grew a row named after the sentence while
        the people it stands for still never arrived."""
        card = ("*Your book today* · 0 active · 0 in proposal · 4 to reach out · 2026-09-03\n"
                "*THE MOVE* 📞 *4 to reach out* — 🔥 Alpha (fire): contact Alpha\n"
                "     then: 🔥 Beta (fire) · +2 more, lowest-scoring, on the board\n")
        rows, err = cb.read_card(_tree(tmp_path, card=card))
        assert err is None
        names = [r["name"] for r in rows]
        assert names == ["Alpha", "Beta"], names
        assert not any("more" in n for n in names)


class TestAnAbsentNotifierIsNotAFiling:
    def test_send_refuses_when_there_is_no_notifier(self, tmp_path, monkeypatch):
        er = _load_engineering_route()
        monkeypatch.setattr(er, "NOTIFY", tmp_path / "not-there.sh")
        with pytest.raises(FileNotFoundError):
            er.send("anything")

    def test_and_route_counts_it_as_failed_not_filed(self, tmp_path, monkeypatch):
        """It returned None, which `route` reads as a successful filing, so an
        unconfigured machine reported every engineering line as routed to Sana while
        no issue existed anywhere."""
        er = _load_engineering_route()
        monkeypatch.setattr(er, "NOTIFY", tmp_path / "not-there.sh")
        # DEGRADED, because a healthy section is deliberately not news: 
        # emits nothing for it, so a clean source proves nothing about filing.
        filed, failed = er.route({"owed": ([], "linear down")}, (("owed", "Owed today"),))
        assert filed == []
        assert len(failed) == 1 and "no notifier" in failed[0][1]


class TestRound13:
    def test_an_idless_mail_answer_withholds_the_archive_authority(self, tmp_path):
        """When the model returns ids the key is the id; when it does not, it is
        sender+subject. Both are stable in themselves and they are DIFFERENT ids for
        one thread, so the day the model stops returning ids the painter would archive
        the row he pinned and recreate it at "Not started". The rows still paint."""
        brief = _brief()
        rows = [brief.Row("Alice  Re: invoice", "mail:Alice|Re: invoice")]
        b = cb.buckets(NOW, {"mail": (rows, None)}, _tree(tmp_path))
        assert [r["key"] for r in b["inbox"]] == ["mail:Alice|Re: invoice"]
        assert "inbox:Gmail" not in b["healthy_scopes"]

    def test_but_real_thread_ids_still_authorise_it(self, tmp_path):
        """The negative control: withholding it always would mean answered mail never
        leaves the board."""
        brief = _brief()
        rows = [brief.Row("Alice  Re: invoice", "mail:19ff4af34dbc0f56")]
        b = cb.buckets(NOW, {"mail": (rows, None)}, _tree(tmp_path))
        assert "inbox:Gmail" in b["healthy_scopes"]

    def test_two_unreadable_properties_are_not_equal_to_each_other(self):
        """`_already_holds` promised an unreadable property fails toward writing, while
        None == None made two of them compare EQUAL and skip the write, so a row kept
        stale text forever. The docstring was right and the code was not."""
        a = board_rows._prop_value({"some_new_notion_shape": True})
        b = board_rows._prop_value({"another_unknown": 1})
        assert a != b and a != None  # noqa: E711  -- the None case is the defect

    def test_a_card_that_parses_to_nothing_never_archives_his_rows(self, tmp_path):
        """Round 14 (major), against round 12's fix. A format change that keeps the
        header parses to zero rows and looks exactly like a quiet morning, so calling
        that scope healthy handed the painter authority to archive every client row
        including the pinned ones. Quiet costs nothing; drifted costs everything."""
        b = cb.buckets(NOW, {}, _tree(tmp_path, card=TestRound12.QUIET))
        assert "card" not in b["healthy_scopes"]
        assert not any(r["scope"] == cb.CARD_ALARM for r in b["top_of_mind"])

    def test_but_a_card_with_rows_still_authorises_it(self, tmp_path):
        b = cb.buckets(NOW, {}, _tree(tmp_path))
        assert "card" in b["healthy_scopes"]


class TestNoSourceStarvesAnother:
    """claude review 2026-09-04, major, and it is the OPPOSITE of the finding before
    it. Capping mail at the producer deleted rows; not capping it let mail take the
    whole 40-row write budget in source order, so every GroupMe row fell past it and
    sat frozen on his board forever. `capped` protects them from archiving, which is
    round 11 working, but protected is not updated."""

    def test_a_busy_source_cannot_push_another_source_off_the_budget(self):
        rows = ([{"scope": "inbox:Gmail", "key": f"mail:{i}"} for i in range(60)]
                + [{"scope": "inbox:GroupMe", "key": f"gm:{i}"} for i in range(3)])
        head = board_rows._fair_share(rows, 40)[:40]
        assert any(r["scope"] == "inbox:GroupMe" for r in head), (
            "every GroupMe row fell past the write budget and freezes on the board")

    def test_order_WITHIN_a_source_is_never_re_made(self):
        """The mail prompt sorts oldest first. That ordering is a judgement this
        function must not second-guess."""
        rows = [{"scope": "inbox:Gmail", "key": f"mail:{i}"} for i in range(5)]
        rows += [{"scope": "inbox:GroupMe", "key": f"gm:{i}"} for i in range(5)]
        out = board_rows._fair_share(rows, 40)
        mail = [r["key"] for r in out if r["scope"] == "inbox:Gmail"]
        assert mail == [f"mail:{i}" for i in range(5)]

    def test_one_source_alone_is_left_exactly_as_it_came(self):
        rows = [{"scope": "card", "key": f"c:{i}"} for i in range(5)]
        assert board_rows._fair_share(rows, 40) == rows

    def test_PAINT_ITSELF_shares_the_budget(self, monkeypatch):
        """Drives paint(), not the helper. The first version of these tests called
        `_fair_share` directly, so BYPASSING IT AT THE CALL SITE broke nothing and
        the mutant survived: a helper with no wiring test is an undefended helper.
        This one fails if paint stops calling it."""
        created = []
        monkeypatch.setattr(board_rows, "existing_rows", lambda *a, **k: {})
        monkeypatch.setattr(
            board_rows, "_request",
            lambda token, method, path, body=None, opener=None, budget=None:
            created.append(((body or {}).get("properties") or {})) or {"id": "x"})
        buckets = {"top_of_mind": [], "this_week": [],
                   "inbox": ([{"title": f"m{i}", "key": f"mail:{i}", "detail": "",
                               "scope": "inbox:Gmail"} for i in range(60)]
                             + [{"title": f"g{i}", "key": f"gm:{i}", "detail": "",
                                 "scope": "inbox:GroupMe"} for i in range(3)]),
                   "healthy_scopes": {"inbox:Gmail", "inbox:GroupMe"}}
        board_rows.paint(buckets, "t", "db")
        titles = ["".join(t["text"]["content"] for t in (props.get("Task") or {}).get("title", []))
                  for props in created]
        assert any(t.startswith("g") for t in titles), (
            "paint wrote 40 mail rows and no GroupMe row; the channel freezes")

    def test_nothing_is_lost_or_duplicated_by_the_reordering(self):
        rows = ([{"scope": "a", "key": f"a{i}"} for i in range(7)]
                + [{"scope": "b", "key": f"b{i}"} for i in range(2)]
                + [{"scope": "c", "key": f"c{i}"} for i in range(11)])
        out = board_rows._fair_share(rows, 40)
        assert sorted(r["key"] for r in out) == sorted(r["key"] for r in rows)


class TestTwoDeliverablesAreTwoRows:
    """claude review 2026-09-04, minor. Two open commitments for one client with no
    id both keyed `due:<slug>`, so the second overwrote the first in `wanted` and the
    read-back still said ok -- it counts what it wrote, and the row was gone before
    the count. A key derived from too little is a collision, and a collision is a
    silent deletion."""

    def test_two_id_less_deliverables_for_one_client_stay_two_rows(self, tmp_path):
        due = (NOW.date() + dt.timedelta(days=3)).isoformat()
        paths = _tree(tmp_path, commitments="\n".join([
            json.dumps({"slug": "acme", "state": "open", "due": due,
                        "promise": "send the audit"}),
            json.dumps({"slug": "acme", "state": "open", "due": due,
                        "promise": "send the invoice"}),
        ]), clients={"clients": []})
        rows = cb.read_week(NOW, paths)[0]
        keys = [r["key"] for r in rows if r["key"].startswith("due:")]
        assert len(keys) == 2, "one deliverable was silently dropped"
        assert len(set(keys)) == 2, f"both deliverables share one key: {keys}"

    def test_the_key_does_not_move_when_the_countdown_does(self, tmp_path):
        """The detail carries days-remaining, which changes every morning. Keying on
        the rendered line would mint a new row daily."""
        def key_on(days):
            due = (NOW.date() + dt.timedelta(days=days)).isoformat()
            paths = _tree(tmp_path, commitments=json.dumps(
                {"slug": "acme", "state": "open", "due": due,
                 "promise": "send the audit"}), clients={"clients": []})
            return [r["key"] for r in cb.read_week(NOW, paths)[0]
                    if r["key"].startswith("due:")][0]
        assert key_on(2) == key_on(5)

    def test_a_real_commitment_id_still_wins(self, tmp_path):
        due = (NOW.date() + dt.timedelta(days=3)).isoformat()
        paths = _tree(tmp_path, commitments=json.dumps(
            {"id": "c1", "slug": "acme", "state": "open", "due": due,
             "promise": "send the audit"}), clients={"clients": []})
        assert any(r["key"] == "due:c1" for r in cb.read_week(NOW, paths)[0])


class TestTheDoneLineIsACriterionNotAClaim:
    """Founder, 2026-09-04, reading his own board: *"if it says I'm done why is it
    showing me the thread?"* Every Gmail row's note read "Done signal: you replied in
    the thread" -- a past-tense sentence about him. The row asserted the very thing it
    was asking for, while Status said Not started two columns away.

    The phrasing was copied off the reference board and never read back as a sentence.
    A completion criterion has to be written as a condition."""

    def test_the_note_says_when_not_that_it_happened(self):
        props = board_rows._properties(
            {"title": "t", "scope": "inbox:Gmail", "detail": "d",
             "done": "you reply in the thread"}, "Inbox", "kipi-abc", True)
        note = "".join(t["text"]["content"] for t in props["Notes"]["rich_text"])
        assert note.startswith("Done when: "), note
        assert "Done signal" not in note

    def test_no_done_string_is_written_in_the_past_tense(self):
        """A grep, deliberately: the defect was one word in one string, and the next
        one added will be written by whoever adds a source."""
        strings = ([cb.DONE_DEFAULT, cb.DONE_GTM_FALLBACK]
                   + list(cb.DONE_BY_KIND.values())
                   + list(cb.DONE_BY_SOURCE.values()))
        assert strings
        # A RULE, not a list of the seven phrases this PR happened to remove. The
        # first version was that list, so a new source shipping "you responded to
        # them" would have gone green. Any "you <verb>ed" is a claim about the past;
        # a criterion is present tense.
        # Only the LEADING "you <verb>" states the criterion. A later one can be a
        # legitimate past fact: "you send the thing you promised" is correct, because
        # the promise really did happen and sending it is the condition. Matching
        # anywhere failed that string, which is a rule that would have been loosened
        # back into a denylist the first time it fired.
        lead = re.compile(r"\byou(?:'ve| have)?\s+(\w+)")
        for text in strings:
            hit = lead.search(text)
            if not hit:
                continue
            verb = hit.group(1)
            assert not verb.endswith(("ed", "nt")), (
                f"{text!r} opens with {hit.group(0)!r}: that reads as a claim he "
                "already did it, not as the condition for being finished")

    def test_every_row_still_carries_one(self, tmp_path):
        b = cb.buckets(NOW, {"mail": ([_brief().Row("Portant: docs", "mail:t1")], None)},
                       _tree(tmp_path))
        rows = b["top_of_mind"] + b["this_week"] + b["inbox"]
        assert rows and all((r.get("done") or "").strip() for r in rows)
