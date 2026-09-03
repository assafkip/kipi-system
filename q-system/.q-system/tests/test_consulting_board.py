"""The consulting morning board: mirror, never a second derivation (2026-09-03).

The load-bearing classes are TestAStaleCardIsAnError and TestTheDryRunWritesNothing.
Both pin defects this work actually hit, not defects imagined for it.
"""
import datetime as dt
import json
import os
import sys
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
        a = cb.buckets(NOW, {"mail": (["Portant: 2h ago about the docs"], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": (["Portant: 5h ago about the docs"], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a == b, "an age change minted a new id and would orphan his row"

    def test_but_a_different_thread_is_a_different_row(self, tmp_path):
        a = cb.buckets(NOW, {"mail": (["Portant: about the docs"], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        b = cb.buckets(NOW, {"mail": (["Harbor: about the invoice"], None)},
                       _tree(tmp_path))["inbox"][0]["key"]
        assert a != b, "stripping volatile tokens must not collapse distinct rows"


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
        b = cb.buckets(NOW, {"mail": (["a thread"], None)}, _tree(tmp_path))
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
