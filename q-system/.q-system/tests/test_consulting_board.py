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
    (q / "output").mkdir(parents=True)
    (q / "my-project").mkdir(parents=True)
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
        assert {r["name"]: r["health"] for r in rows}["Kestrel Group"] == "⚪"


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

    def test_the_flag_stops_the_board_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KIPI_BRIEF_DRY_RUN", "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        rows, err = board_rows.collect(NOW, {})
        assert rows == [] and "dry-run" in err

    def test_pytest_alone_also_stops_it(self, monkeypatch):
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        rows, err = board_rows.collect(NOW, {})
        assert rows == [] and "pytest" in err


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
        """Hashed from the title only. Hashing the detail too would mint a new row every
        morning as due-dates and reply counts move, and the board would only grow."""
        a = board_rows.item_id("top_of_mind", {"title": "Northwind", "detail": "due Mon"})
        b = board_rows.item_id("top_of_mind", {"title": "Northwind", "detail": "due Tue"})
        assert a == b and a.startswith(board_rows.OWNED_PREFIX)

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
        mb.route_engineering({"owed": ([], "linear down"),
                              "overnight": (["fine"], None)}, notify=sent.append)
        assert len(sent) == 1 and "linear down" in sent[0]

    def test_a_healthy_section_pages_nobody(self):
        """A ticket every morning is how an alert channel gets muted."""
        mb = self._brief()
        sent = []
        mb.route_engineering({"owed": (["x"], None), "overnight": ([], None)},
                             notify=sent.append)
        assert sent == []

    def test_only_one_module_writes_the_board(self):
        mb = self._brief()
        stems = {s for s, _, _ in mb.OPTIONAL_SECTIONS}
        assert "board_rows.py" in stems
        assert "notion_board.py" not in stems, (
            "notion_board.py writes bullets to the same page board_rows writes rows to; "
            "the first live dry-run rendered both")
