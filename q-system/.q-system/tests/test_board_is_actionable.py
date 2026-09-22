"""The board carries only what he can act on, and every row he can act on can be started.

Founder-directed 2026-09-07, after a row-by-row walk of the live board: *"remove sana
stuff from the board"* and *"I want you to revamp the crm so it fits what I asked. Dont
punt anything to me. Fix it. right now its not useful."* DEC-34 in the consulting
instance's crm-working.md is the record.

Every case here was RED against the file as it stood that evening; the red run is in
the PR body. The property-name expectations are written out BY HAND rather than
derived from the module's own tables: a test that iterates the thing it is testing
cannot see that thing shrink, so a property silently dropped from the writer would
take its own test with it.
"""
import datetime as dt
import json
import sys

import pytest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import board_rows as br  # noqa: E402
import consulting_board as cb  # noqa: E402

NOW = dt.datetime(2026, 9, 7, 8, 0, tzinfo=dt.timezone.utc)

#: GENERIC CLIENT LABELS ON PURPOSE. This repo is public and the client-name guard
#: blocks real ones in staged content; the shapes under test are the health dots and
#: the line grammar, and neither needs a real engagement's name.
CARD = """*Your book today* - 4 active - 2026-09-07
*THE MOVE* 🟡 *Yellow Engagement, LLC* · touch due 13 days ago
⚪ *White Engagement One* · an agent owes 6: run the long-running search
⚪ *White Engagement Two* · an agent owes 7: point at the key files
🟢 *Green Engagement* · nothing to do
🔴 *Red Engagement* · you said "the intake form" - not sent
"""


def _paths(tmp_path):
    """The module's OWN path map, rooted at a tmp dir. Restating the file names here
    would make this a second source of truth for them, and a rename would leave the
    test green against paths nothing uses."""
    paths = cb._paths(tmp_path)
    for f in paths.values():
        f.parent.mkdir(parents=True, exist_ok=True)
    paths["card"].write_text(CARD, encoding="utf-8")
    # The card is withheld unless its heartbeat is stamped TODAY in PT, which is the
    # freshness rule read_heartbeat enforces. The stamp is derived from the module's
    # own clock rather than hardcoded, because a hardcoded date is a time bomb.
    paths["heartbeat"].write_text(json.dumps(
        {"at": "x", "card": {"date": NOW.astimezone(cb.PT).date().isoformat(),
                             "counts": {"red": 1, "reach": 0}}}), encoding="utf-8")
    paths["gtm"].write_text(json.dumps({"rows": {}}), encoding="utf-8")
    return paths


def _card_items(tmp_path):
    rows, err = cb.read_card(_paths(tmp_path))
    assert err is None, err
    return rows


class TestSanaNeverReachesHisBoard:
    """⚪ is 'their move' or 'Sana owes n'. It is reported on the Slack card and is
    never a row on his board, because it is not an act he can perform (DEC-30/DEC-34)."""

    def test_the_card_still_carries_the_white_lines(self, tmp_path):
        # The reader is unchanged on purpose: the Slack card keeps its Sana line.
        healths = [r["health"] for r in _card_items(tmp_path)]
        assert healths.count("⚪") == 2, healths

    def test_no_white_or_green_line_becomes_a_board_row(self, tmp_path):
        out = cb.buckets(NOW, {}, _paths(tmp_path))
        titles = [i["title"] for i in out["top_of_mind"] + out["this_week"] + out["inbox"]]
        assert not [t for t in titles if t.startswith(("⚪", "🟢"))], titles

    def test_the_rows_he_can_act_on_are_still_there(self, tmp_path):
        out = cb.buckets(NOW, {}, _paths(tmp_path))
        titles = [i["title"] for i in out["top_of_mind"]]
        assert any(t.startswith("🔴") for t in titles), titles
        assert any(t.startswith("🟡") for t in titles), titles


class TestThisWeekIsNotMachineFilledFromTheCard:
    """The section's own text says it is his and that nothing fills it automatically."""

    def test_the_card_writes_nothing_into_this_week(self, tmp_path):
        out = cb.buckets(NOW, {}, _paths(tmp_path))
        from_card = [i for i in out["this_week"] if i.get("scope") == "card"]
        assert from_card == [], from_card

    def test_a_yellow_row_is_top_of_mind_not_this_week(self, tmp_path):
        out = cb.buckets(NOW, {}, _paths(tmp_path))
        assert any(i["title"].startswith("🟡") for i in out["top_of_mind"])
        assert not any(i["title"].startswith("🟡") for i in out["this_week"])


class TestEveryMailRowCanBeStartedFromTheRow:
    """His standing rule: if he cannot click it, it does not belong."""

    def _mail(self, tmp_path, key):
        class Row(str):
            pass
        r = Row("someone@example.test  Intro: two people")
        r.key = key
        out = cb.buckets(NOW, {"mail": ([r], None)}, _paths(tmp_path))
        return out["inbox"][0]

    def test_a_gmail_row_carries_its_thread_link(self, tmp_path):
        item = self._mail(tmp_path, "mail:1a06eb5b0b03759f")
        assert item["link"] == (
            "https://mail.google.com/mail/u/0/#all/1a06eb5b0b03759f"), item

    def test_the_link_is_derived_from_the_id_not_the_text(self, tmp_path):
        # Same rendered line, different thread: different link. The PR #296 rounds 1-4
        # defect was an identity derived from presentation; this must not repeat it.
        a = self._mail(tmp_path, "mail:aaaaaaaaaaaaaaaa")["link"]
        b = self._mail(tmp_path, "mail:bbbbbbbbbbbbbbbb")["link"]
        assert a != b and a.endswith("aaaaaaaaaaaaaaaa"), (a, b)

    def test_the_producer_supplies_no_next_for_an_inbox_row(self, tmp_path):
        """A constant per source restates DONE_BY_SOURCE in the imperative, which is
        the duplication this change removes from Notes (PR reviewer, nit). The link
        and the subject are what make the row startable. Because the writer never
        blanks a property it was not given, a Next a human wrote there survives."""
        assert self._mail(tmp_path, "mail:1a06eb5b0b03759f").get("next") is None


class TestTheWriterCarriesLinkAndNext:
    """Written when the producer supplies them, never blanked when it does not."""

    #: BY HAND, not derived from the writer's own map. A property dropped from that map
    #: would otherwise take its test with it and the suite would still be green.
    EXPECTED = {"Task", "Item id", "Notes", "Domain", "Priority", "Source",
                "Link", "Next"}

    def test_link_and_next_are_written(self):
        props = br._properties({"title": "t", "key": "k", "done": "d",
                                "link": "https://example.test/x",
                                "next": "Open the thread and reply.",
                                "priority": "P1", "source": "Gmail"},
                               "Inbox", "cb:x", False)
        assert props["Link"] == {"url": "https://example.test/x"}
        assert props["Next"]["rich_text"][0]["text"]["content"] == (
            "Open the thread and reply.")

    def test_the_written_property_set_is_exactly_what_is_expected(self):
        props = br._properties({"title": "t", "key": "k", "done": "d",
                                "link": "https://example.test/x", "next": "go",
                                "priority": "P1", "source": "Gmail"},
                               "Inbox", "cb:x", False)
        assert set(props) == self.EXPECTED, set(props) ^ self.EXPECTED

    def test_a_producer_that_knows_neither_clears_neither(self):
        props = br._properties({"title": "t", "key": "k", "done": "d"},
                               "Inbox", "cb:x", False)
        assert "Link" not in props and "Next" not in props, sorted(props)


class TestTheNoteDoesNotRepeatItself:
    """6 of 12 live rows on 2026-09-07 printed one sentence twice."""

    def test_a_detail_equal_to_the_done_signal_is_written_once(self):
        signal = "the old token is dead and the new one is not in a tracked file."
        props = br._properties({"title": "t", "key": "k", "done": signal,
                                "detail": signal}, "This Week", "cb:x", False)
        note = props["Notes"]["rich_text"][0]["text"]["content"]
        assert note.count(signal) == 1, note

    def test_a_detail_that_adds_something_is_kept(self):
        props = br._properties({"title": "t", "key": "k", "done": "signal",
                                "detail": "a real extra fact"}, "This Week",
                               "cb:x", False)
        note = props["Notes"]["rich_text"][0]["text"]["content"]
        assert "a real extra fact" in note and "signal" in note, note


class TestHisPlacementSurvivesTheProducerDroppingTheRow:
    """The module's contract is that a row a human moved is never moved by the machine.
    The archive loop was the hole in it: a pinned row was archived the moment its
    producer stopped emitting it, taking his placement and his Status with it. Filtering
    white client lines off the board makes that flip ordinary rather than rare."""

    def _page(self, iid, note):
        return {"id": f"page-{iid}",
                "properties": {"Item id": {"rich_text": [{"plain_text": iid}]},
                               "Notes": {"rich_text": [{"plain_text": note}]}}}

    def test_a_pinned_row_is_kept_when_its_producer_stops_emitting_it(self, monkeypatch):
        page = self._page("cb:gone", "Done signal: x\nscope=card\nbucket=This Week\npinned=1")
        sent = []
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {"cb:gone": page})
        monkeypatch.setattr(br, "_request",
                            lambda tok, m, path, body, op=None, bud=None: sent.append((m, path, body)))
        counts = br.paint({"top_of_mind": [], "this_week": [], "inbox": [],
                           "healthy_scopes": {"card"}}, "tok", "db")
        assert counts["archived"] == 0, sent
        # `held`, not `kept`: a quiet source and a row he pinned whose source is
        # healthy are different facts and the morning line reports both.
        assert counts["held"] == 1 and counts["kept"] == 0, counts
        assert not [s for s in sent if s[2].get("archived")], sent

    def test_a_held_row_is_reported_as_held_and_as_nothing_else(self, monkeypatch):
        """A held row IS on the board, so it has to be a term of `collect`'s read-back
        sum or the proof reports a mismatch every run once any pinned row's producer
        goes quiet (PR reviewer round 4, major).

        THIS TEST DOES NOT RECOMPUTE THAT SUM. The first version did, and a test that
        recomputes the formula it guards stays green when the real one drops a term
        (round 7, minor). The sum itself is held by
        test_every_row_on_the_board_is_a_term_of_the_read_back_sum in
        test_consulting_board.py, which reads the expression `collect` actually uses.
        What belongs here is the count that expression consumes."""
        page = self._page("cb:gone", "Done signal: x\nscope=card\nbucket=This Week\npinned=1")
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {"cb:gone": page})
        monkeypatch.setattr(br, "_request", lambda *a, **k: None)
        counts = br.paint({"top_of_mind": [], "this_week": [], "inbox": [],
                           "healthy_scopes": {"card"}}, "tok", "db")
        assert counts["held"] == 1, counts
        assert counts["kept"] == 0 and counts["archived"] == 0, counts
        assert counts["wanted"] == 0 and counts["deferred_new"] == 0, counts

    def test_nothing_is_written_to_a_held_row(self, monkeypatch):
        """The first answer to 'a pinned row has no exit' wrote a stamp into its Notes,
        and truncating the note to fit deleted `pinned=1` itself. Nothing is written
        now; his exit is his own archive."""
        page = self._page("cb:gone", "Done signal: x\nscope=card\nbucket=This Week\npinned=1")
        sent = []
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {"cb:gone": page})
        monkeypatch.setattr(br, "_request",
                            lambda tok, m, path, body, op=None, bud=None: sent.append((m, path, body)))
        br.paint({"top_of_mind": [], "this_week": [], "inbox": [],
                  "healthy_scopes": {"card"}}, "tok", "db")
        assert sent == [], sent

    def test_an_unpinned_row_the_producer_dropped_is_still_archived(self, monkeypatch):
        page = self._page("cb:gone", "Done signal: x\nscope=card\nbucket=This Week")
        sent = []
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {"cb:gone": page})
        monkeypatch.setattr(br, "_request",
                            lambda tok, m, path, body, op=None, bud=None: sent.append((m, path, body)))
        counts = br.paint({"top_of_mind": [], "this_week": [], "inbox": [],
                           "healthy_scopes": {"card"}}, "tok", "db")
        assert counts["archived"] == 1, (counts, sent)


class TestALinkIsComparable:
    """Without url in `_prop_value` every row carrying a Link read as unreadable, so
    `_already_holds` was always False and the painter rewrote every Gmail row every
    run (PR reviewer, major)."""

    def test_a_url_property_reads_back_as_its_value(self):
        assert br._prop_value({"url": "https://example.test/x"}) == "https://example.test/x"

    def test_an_unchanged_link_is_not_rewritten(self):
        props = br._properties({"title": "t", "key": "k", "done": "d",
                                "link": "https://example.test/x"},
                               "Inbox", "cb:x", False)
        page = {"properties": {k: v for k, v in props.items()}}
        assert br._already_holds(page, props), "a row that already holds its Link was rewritten"

    def test_a_changed_link_is_rewritten(self):
        props = br._properties({"title": "t", "key": "k", "done": "d",
                                "link": "https://example.test/new"},
                               "Inbox", "cb:x", False)
        page = {"properties": dict(props, Link={"url": "https://example.test/old"})}
        assert not br._already_holds(page, props)


class TestAColumnThisBoardLacksIsNotAWholeLostMorning:
    """`Link` and `Next` are new. Notion answers an unknown property with a 400 that
    aborts the paint mid-write, so a board that predates them would lose every row of
    that morning to a column nobody noticed was missing (PR reviewer round 5, major).

    `known` maps a column name to its TYPE. Name alone was not enough: a board carrying
    `Link` as rich_text rather than url takes the same 400 the guard exists to prevent,
    and the guard would have called the column fine (round 7, minor)."""

    ITEM = {"title": "t", "key": "k", "done": "d", "priority": "P1",
            "source": "Gmail", "link": "https://example.test/x", "next": "go"}
    #: BY HAND, never derived from WRITES_TYPE: a column dropped from that map would
    #: otherwise take its own test with it and the suite would stay green.
    OLD_BOARD = {"Task": "title", "Item id": "rich_text", "Notes": "rich_text",
                 "Domain": "multi_select", "Priority": "select", "Source": "select",
                 "Bucket": "select", "Status": "select"}

    def _props(self):
        return br._properties(self.ITEM, "Inbox", "cb:x", False)

    def test_a_board_without_the_new_columns_is_written_without_them(self):
        keep, dropped = br._only_known(self._props(), self.OLD_BOARD)
        assert "Link" not in keep and "Next" not in keep, sorted(keep)
        assert dropped == ("Link", "Next"), dropped

    def test_a_board_that_has_them_as_the_WRONG_TYPE_drops_them_too(self):
        board = dict(self.OLD_BOARD, Link="rich_text", Next="rich_text")
        keep, dropped = br._only_known(self._props(), board)
        assert "Next" in keep, sorted(keep)
        assert len(dropped) == 1 and dropped[0].startswith("Link"), dropped

    def test_a_wrongly_typed_column_is_named_as_present_not_missing(self):
        """"cannot take the Link column" sends him looking for something that is
        sitting right there. The message names both types instead (PR #332, minor)."""
        board = dict(self.OLD_BOARD, Link="rich_text", Next="rich_text")
        _, dropped = br._only_known(self._props(), board)
        assert "it is rich_text" in dropped[0] and "this writes url" in dropped[0], dropped

    def test_a_board_with_them_keeps_them(self):
        board = dict(self.OLD_BOARD, Link="url", Next="rich_text")
        keep, dropped = br._only_known(self._props(), board)
        assert keep == self._props() and dropped == (), dropped

    def test_an_unreadable_schema_writes_everything_exactly_as_before(self):
        """The read failing is not the columns being gone. Refusing to write on a bad
        response would turn one bad answer into a blank morning."""
        keep, dropped = br._only_known(self._props(), None)
        assert keep == self._props() and dropped == ()

    def test_a_failed_schema_request_is_None_not_an_exception(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("notion said no")
        monkeypatch.setattr(br, "_request", boom)
        assert br._schema_properties("tok", "db") is None

    def test_an_empty_schema_answer_is_None_not_an_empty_map(self, monkeypatch):
        """An empty map would drop EVERY property and write nothing at all, which is
        the same lost morning by a different route."""
        monkeypatch.setattr(br, "_request", lambda *a, **k: {"properties": {}})
        assert br._schema_properties("tok", "db") is None

    def test_the_schema_read_keeps_the_type(self, monkeypatch):
        monkeypatch.setattr(br, "_request", lambda *a, **k: {
            "properties": {"Task": {"type": "title"}, "Link": {"type": "url"}}})
        assert br._schema_properties("tok", "db") == {"Task": "title", "Link": "url"}

    def _paint_against(self, monkeypatch, board):
        sent = []
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {})
        monkeypatch.setattr(br, "_request",
                            lambda tok, m, path, body, op=None, bud=None: sent.append((m, path, body)))
        counts = br.paint({"top_of_mind": [dict(self.ITEM, scope="card")],
                           "this_week": [], "inbox": [], "healthy_scopes": {"card"}},
                          "tok", "db", known=board)
        return counts, sent

    def test_the_create_path_is_filtered_too(self, monkeypatch):
        """The first fix filtered the PATCH and not the POST, so a board lacking the
        column still took a 400 on its first NEW row and abandoned the whole paint. The
        patch printed "write sites filtered: 1" and nobody asked whether there were two
        (round 6, major)."""
        counts, sent = self._paint_against(monkeypatch, self.OLD_BOARD)
        posts = [s for s in sent if s[0] == "POST"]
        assert posts, sent
        written = set(posts[0][2]["properties"])
        assert "Link" not in written and "Next" not in written, sorted(written)

    def test_what_could_not_be_written_is_reported_never_silent(self, monkeypatch):
        """A board without `Link` wrote every row with no link and still said
        "read-back ok". A silent half-write is worse than the crash it replaced,
        because the crash gets looked at (round 7, major)."""
        counts, _ = self._paint_against(monkeypatch, self.OLD_BOARD)
        assert counts["dropped_columns"] == ("Link", "Next"), counts["dropped_columns"]

    def test_a_complete_board_reports_nothing_dropped(self, monkeypatch):
        board = dict(self.OLD_BOARD, Link="url", Next="rich_text")
        counts, _ = self._paint_against(monkeypatch, board)
        assert counts["dropped_columns"] == (), counts["dropped_columns"]


class TestTheIdentityColumnIsNeverDropped:
    """`Item id` is how every lookup, refresh and archive decision finds a row, and
    `existing_rows` queries the board by its prefix. Dropping it does not degrade a
    row: it creates a page this module can never find again, one more per wanted row
    per run, with no error anywhere (PR reviewer round 8, major)."""

    ITEM = {"title": "t", "key": "k", "done": "d", "priority": "P1", "source": "Gmail"}

    def _props(self):
        return br._properties(self.ITEM, "Inbox", "cb:x", False)

    def test_a_board_that_cannot_take_the_id_stops_the_paint(self):
        board = {"Task": "title", "Notes": "rich_text", "Domain": "multi_select",
                 "Priority": "select", "Source": "select"}
        with pytest.raises(br.MissingIdentityColumn) as e:
            br._only_known(self._props(), board)
        assert "Item id" in str(e.value)

    def test_the_id_under_the_wrong_type_stops_it_too(self):
        board = {"Task": "title", "Item id": "select", "Notes": "rich_text",
                 "Domain": "multi_select", "Priority": "select", "Source": "select"}
        with pytest.raises(br.MissingIdentityColumn):
            br._only_known(self._props(), board)

    def test_a_missing_title_stops_it(self):
        board = {"Item id": "rich_text", "Notes": "rich_text",
                 "Domain": "multi_select", "Priority": "select", "Source": "select"}
        with pytest.raises(br.MissingIdentityColumn) as e:
            br._only_known(self._props(), board)
        assert "Task" in str(e.value)

    def test_an_optional_column_still_only_drops(self):
        """The refusal is for identity, not for everything. A board missing `Link`
        still paints, minus the link, and says so."""
        board = {"Task": "title", "Item id": "rich_text", "Notes": "rich_text",
                 "Domain": "multi_select", "Priority": "select", "Source": "select"}
        keep, dropped = br._only_known(
            br._properties(dict(self.ITEM, link="https://example.test/x"),
                           "Inbox", "cb:x", False), board)
        assert dropped == ("Link",) and "Item id" in keep


class TestTheSchemaGuardIsActuallyWiredIntoTheRun:
    """A guard the production path never passes is a guard that does not exist, and the
    suite would stay green either way (PR reviewer round 8, nit)."""

    def test_the_runner_hands_paint_the_schema_it_read(self, monkeypatch, tmp_path):
        seen = {}
        monkeypatch.setattr(br, "_schema_properties",
                            lambda *a, **k: {"Task": "title", "Item id": "rich_text"})

        def spy_paint(buckets, token, db, opener=None, budget=None, known=None):
            seen["known"] = known
            return {"created": 0, "updated": 0, "archived": 0, "kept": 0, "held": 0,
                    "wanted": 0, "moved": 0, "pinned": 0, "over_cap": 0,
                    "unchanged": 0, "deferred": 0, "deferred_new": 0,
                    "dropped_columns": ()}

        monkeypatch.setattr(br, "paint", spy_paint)
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {})
        monkeypatch.setattr(br, "ensure_columns", lambda known, *a, **k: (known, ()))
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        # NOT THE PRODUCTION LOCK (PR #332 reviewer, major). `collect` takes a flock on
        # ~/.config/kipi/board-rows.lock, the same file the live painter holds, so the
        # suite and the 07:40 job could each block the other. Tests get their own.
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        assert seen.get("known") == {"Task": "title", "Item id": "rich_text"}, seen


class TestTheCardLineDoesNotPointAtRowsThatAreNotThere:
    """"...and N more on the board" counted every row past the display cap, including
    ⚪ and 🟢 rows that no longer reach the board at all. A pointer to a place the thing
    is not is worse than no pointer (PR reviewer round 5, minor; round 9 asked for the
    test that stops it reverting)."""

    def _card(self, tmp_path, lines):
        paths = _paths(tmp_path)
        paths["card"].write_text(
            "*Your book today* - 2026-09-07\n" + "\n".join(lines), encoding="utf-8")
        return paths

    def _many(self, health, n):
        return [f"{health} *Client {i}* · something" for i in range(n)]

    def test_rows_past_the_cap_that_reach_the_board_are_counted_as_on_the_board(self, tmp_path):
        over = cb.MAX_CLIENT_ROWS + 3
        paths = self._card(tmp_path, self._many("🔴", over))
        rows, err = cb.collect(NOW, {}, paths)
        assert err is None, err
        assert any("more on the board" in r for r in rows), rows
        assert not any("ball is not with you" in r for r in rows), rows

    def test_rows_past_the_cap_that_never_reach_it_are_counted_separately(self, tmp_path):
        over = cb.MAX_CLIENT_ROWS + 3
        paths = self._card(tmp_path, self._many("⚪", over))
        rows, err = cb.collect(NOW, {}, paths)
        assert err is None, err
        assert not any("more on the board" in r for r in rows), rows
        assert any("ball is not with you" in r for r in rows), rows

    def test_the_two_counts_do_not_double_count_one_row(self, tmp_path):
        half = cb.MAX_CLIENT_ROWS
        paths = self._card(tmp_path, self._many("🔴", half) + self._many("⚪", 4))
        rows, err = cb.collect(NOW, {}, paths)
        assert err is None, err
        board = [r for r in rows if "more on the board" in r]
        quiet = [r for r in rows if "ball is not with you" in r]
        assert not board, board
        assert quiet and "4" in quiet[0], quiet


class TestADeadLinkIsWorseThanNoLink:
    """The mail producer's documented fallback key is `mail:<sender>|<subject>`.
    Pasting that after the thread URL builds a link that opens nothing, which costs a
    click and teaches him the column lies (PR reviewer round 10, minor)."""

    def test_a_real_thread_id_gets_a_link(self):
        assert cb.gmail_link("mail:1a06eb5b0b03759f") == (
            "https://mail.google.com/mail/u/0/#all/1a06eb5b0b03759f")

    def test_a_key_that_is_not_a_thread_id_gets_no_link(self):
        """A CONSTRUCTED shape, deliberately: no producer emits one today (the model-era
        collector that could was removed by ASK-1323). The guard is here so a future
        producer meets it instead of shipping dead links first."""
        assert cb.gmail_link("mail:someone@example.test|Re: a subject") is None

    def test_an_empty_or_odd_id_gets_no_link(self):
        assert cb.gmail_link("mail:") is None
        assert cb.gmail_link("") is None
        assert cb.gmail_link("mail:not hex at all") is None

    def test_the_row_still_paints_without_its_link(self, tmp_path):
        class Row(str):
            pass
        r = Row("someone@example.test  Re: a subject")
        r.key = "mail:someone@example.test|Re: a subject"
        item = cb.buckets(NOW, {"mail": ([r], None)}, _paths(tmp_path))["inbox"][0]
        assert item["link"] is None and item["title"], item


class TestTheIdentityRefusalFiresBeforeTheFirstQuery:
    """`existing_rows` filters its query on `Item id`, so a board without that column
    takes a raw 400 from Notion before `_only_known` is reached and the remediation
    never fires (PR reviewer round 10, minor)."""

    def test_a_board_without_the_id_column_is_refused_up_front(self):
        with pytest.raises(br.MissingIdentityColumn):
            br._refuse_without_identity({"Task": "title", "Notes": "rich_text"})

    def test_a_wrongly_typed_id_column_is_refused_too(self):
        with pytest.raises(br.MissingIdentityColumn):
            br._refuse_without_identity({"Task": "title", "Item id": "select"})

    def test_a_good_board_passes(self):
        br._refuse_without_identity({"Task": "title", "Item id": "rich_text"})

    def test_an_unreadable_schema_is_not_a_verdict_about_the_columns(self):
        br._refuse_without_identity(None)

    def test_the_runner_refuses_before_it_queries(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(br, "_schema_properties",
                            lambda *a, **k: {"Task": "title"})
        monkeypatch.setattr(br, "existing_rows",
                            lambda *a, **k: calls.append("queried") or {})
        monkeypatch.setattr(br, "ensure_columns", lambda known, *a, **k: (known, ()))
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        # NOT THE PRODUCTION LOCK (PR #332 reviewer, major). `collect` takes a flock on
        # ~/.config/kipi/board-rows.lock, the same file the live painter holds, so the
        # suite and the 07:40 job could each block the other. Tests get their own.
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        rows, err = br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        assert calls == [], "it queried the board before refusing"
        assert rows == [] and "identifies rows by" in err, err


class TestTheMorningLineSaysWhatHappened:
    """The dropped-columns sentence and the held count are what the founder actually
    reads. Neither was asserted anywhere, so deleting either left the suite green
    (PR reviewer round 11, minor)."""

    COUNTS = {"created": 1, "updated": 0, "archived": 0, "kept": 0, "held": 2,
              "wanted": 1, "moved": 0, "pinned": 0, "over_cap": 0, "unchanged": 0,
              "deferred": 0, "deferred_new": 0, "dropped_columns": ("Link", "Next")}

    def _line(self, monkeypatch, tmp_path, counts):
        monkeypatch.setattr(br, "_schema_properties",
                            lambda *a, **k: {"Task": "title", "Item id": "rich_text"})
        # NOTHING LEAVES THIS MACHINE. These tests delete the PYTEST_CURRENT_TEST guard
        # to reach `collect`'s line builder, and `ensure_columns` would then fire a real
        # authenticated PATCH at api.notion.com on every suite run (PR #332 reviewer,
        # major). Every outbound seam is stubbed, and `_request` is replaced by one that
        # RAISES so a new call site cannot quietly start talking to the network.
        monkeypatch.setattr(br, "ensure_columns", lambda known, *a, **k: (known, ()))
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        # NOT THE PRODUCTION LOCK (PR #332 reviewer, major). `collect` takes a flock on
        # ~/.config/kipi/board-rows.lock, the same file the live painter holds, so the
        # suite and the 07:40 job could each block the other. Tests get their own.
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        monkeypatch.setattr(br, "paint", lambda *a, **k: counts)
        seen = counts["wanted"] + counts["kept"] + counts["held"] - counts["deferred_new"]
        monkeypatch.setattr(br, "existing_rows",
                            lambda *a, **k: {f"cb:{i}": {} for i in range(seen)})
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        rows, err = br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        assert err is None, err
        return rows[0]

    def test_the_columns_it_could_not_write_are_named(self, monkeypatch, tmp_path):
        line = self._line(monkeypatch, tmp_path, dict(self.COUNTS))
        assert "cannot take" in line and "Link" in line and "Next" in line, line
        assert "columns" in line, line

    def test_one_dropped_column_is_singular(self, monkeypatch, tmp_path):
        line = self._line(monkeypatch, tmp_path,
                          dict(self.COUNTS, dropped_columns=("Link",)))
        # NOT `"Link column" in line`: that substring is inside "Link columns" too, so
        # the plural branch survived the mutation (round 4, minor). Assert the exact end.
        assert "the Link column, so those values were not written" in line, line
        assert "columns" not in line, line

    def test_a_complete_board_says_nothing_about_columns(self, monkeypatch, tmp_path):
        line = self._line(monkeypatch, tmp_path,
                          dict(self.COUNTS, dropped_columns=()))
        assert "cannot take" not in line, line

    def test_held_rows_are_reported_on_the_line(self, monkeypatch, tmp_path):
        line = self._line(monkeypatch, tmp_path, dict(self.COUNTS))
        assert "2 yours (source stopped reporting it)" in line, line


class TestTheBoardHealsItsOwnOptionalColumns:
    """Nothing created `Link`, so on every board but the one patched by hand it was
    dropped on each run and the line said the board could not take it, forever, with
    no way given to change that (PR reviewer round 12, major)."""

    #: A board from before Link and Next existed: everything else, right types. Written
    #: out BY HAND rather than derived from WRITES_TYPE, so a column added there and
    #: forgotten in CREATABLE cannot quietly make this fixture agree with itself.
    OLD = {"Task": "title", "Item id": "rich_text", "Notes": "rich_text",
           "Domain": "multi_select", "Priority": "select", "Source": "select",
           "Bucket": "select", "Status": "select"}
    COMPLETE = dict(OLD, Link="url", Next="rich_text")

    def _notion_patch(self, sent, returns):
        """Notion answers a schema PATCH with the whole database. The fake has to as
        well: returning None made this module refuse to believe its own create, which
        is the correct new behaviour and the reason this fake got more honest."""
        def fake(tok, m, path, body, op=None, bud=None):
            sent.append((m, path, body))
            return returns
        return fake

    def test_a_missing_column_is_created_and_then_usable(self, monkeypatch, tmp_path):
        sent = []
        after = {"properties": {n: {"type": t} for n, t in self.COMPLETE.items()}}
        monkeypatch.setattr(br, "_request", self._notion_patch(sent, after))
        # ITS OWN RECORD FILE. The real one lives beside the painter's lock, and a
        # suite that writes there teaches the live job that he deleted things.
        out, problems = br.ensure_columns(dict(self.OLD), "tok", "db",
                                          record=tmp_path / "made.json")
        assert problems and "added the" in problems[0], problems
        assert sent and sent[0][0] == "PATCH" and "/databases/db" in sent[0][1], sent
        assert set(sent[0][2]["properties"]) == {"Link", "Next"}, sent[0][2]
        assert sent[0][2]["properties"]["Link"] == {"url": {}}, sent[0][2]
        assert out["Link"] == "url" and out["Next"] == "rich_text", out

    def test_a_complete_board_is_not_touched(self, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setattr(br, "_request",
                            lambda *a, **k: sent.append(a))
        assert br.ensure_columns(dict(self.COMPLETE), "tok", "db",
                                 record=tmp_path / "made.json") == (self.COMPLETE, ())
        assert sent == [], sent

    def test_a_create_notion_does_not_confirm_is_not_believed(self, monkeypatch, tmp_path):
        """Synthesising the schema asserts the create took effect. If it did not, the
        next write carries the column anyway and takes the raw 400 this whole guard
        exists to prevent (PR #332 reviewer, minor)."""
        sent = []
        monkeypatch.setattr(br, "_request", self._notion_patch(sent, {"properties": {}}))
        out, problems = br.ensure_columns(dict(self.OLD), "tok", "db",
                                          record=tmp_path / "made.json")
        assert "Link" not in out, out
        assert any("unconfirmed" in x for x in problems), problems

    def test_a_refused_creation_degrades_exactly_as_before(self, monkeypatch, tmp_path):
        def boom(*a, **k):
            raise RuntimeError("notion said no")
        monkeypatch.setattr(br, "_request", boom)
        out, problems = br.ensure_columns(dict(self.OLD), "tok", "db",
                                          record=tmp_path / "made.json")
        assert out == self.OLD
        assert any("notion said no" in x for x in problems), problems

    def test_a_refusal_carries_notions_own_words_not_just_the_status(self, monkeypatch, tmp_path):
        """"HTTPError: 400 Bad Request" is the half that says nothing. Notion puts what
        is actually wrong in the body, which is why this branch exists (round 4)."""
        import io as _io
        import urllib.error

        def boom(*a, **k):
            raise urllib.error.HTTPError(
                "u", 400, "Bad Request", {},
                _io.BytesIO(b'{"message": "Link is not a valid property name here"}'))
        monkeypatch.setattr(br, "_request", boom)
        _, problems = br.ensure_columns(dict(self.OLD), "tok", "db",
                                        record=tmp_path / "made.json")
        assert any("not a valid property name" in x for x in problems), problems

    def test_a_column_he_deleted_is_not_put_back(self, monkeypatch, tmp_path):
        """Re-creating it every morning gives him no way to say no. Same "his choice
        wins" line the row painter holds, one level down (round 4, major)."""
        rec = tmp_path / "made.json"
        rec.write_text(json.dumps({"db": ["Link"]}), encoding="utf-8")
        sent = []
        after = {"properties": {n: {"type": ty} for n, ty in
                                dict(self.OLD, Next="rich_text").items()}}
        monkeypatch.setattr(br, "_request", self._notion_patch(sent, after))
        out, problems = br.ensure_columns(dict(self.OLD), "tok", "db", record=rec)
        asked = set(sent[0][2]["properties"])
        assert "Link" not in asked and "Next" in asked, asked
        # NO SECOND SENTENCE. Losing Link costs one value on a row, so it earns no
        # explanation of itself every morning. The ordinary "was not written" report
        # still names it, exactly as it names any other column, and asserting silence
        # here would have been asserting something false (round 7, minor).
        assert not any("your removal" in x for x in problems), problems

    def test_a_structural_column_he_deleted_is_named_every_run(self, monkeypatch, tmp_path):
        """Losing `Notes` stops archiving entirely and losing `Bucket` hides every row.
        Round 5 filtered those warnings out and the line still said "read-back ok",
        which is silent degradation (round 6, major)."""
        rec = tmp_path / "made.json"
        rec.write_text(json.dumps({"db": ["Notes", "Bucket"]}), encoding="utf-8")
        bare = {"Task": "title", "Item id": "rich_text"}
        sent = []
        after = {"properties": {n: {"type": ty} for n, ty in br.WRITES_TYPE.items()
                                if n not in ("Notes", "Bucket")}}
        monkeypatch.setattr(br, "_request", self._notion_patch(sent, after))
        _, problems = br.ensure_columns(dict(bare), "tok", "db", record=rec)
        asked = set(sent[0][2]["properties"])
        assert "Notes" not in asked and "Bucket" not in asked, asked
        joined = " ".join(problems)
        assert "nothing is ever archived" in joined, problems
        assert "invisible on the board" in joined, problems

    def test_no_module_state_leaks_between_boards(self, monkeypatch, tmp_path):
        """The round-5 fix kept this in a module global that was never cleared and was
        unioned across every board id, so one board's report contaminated another's and
        the suite went order-dependent (round 6, minor)."""
        rec = tmp_path / "made.json"
        rec.write_text(json.dumps({"board-a": ["Notes"]}), encoding="utf-8")
        after = {"properties": {n: {"type": ty} for n, ty in br.WRITES_TYPE.items()}}
        monkeypatch.setattr(br, "_request", self._notion_patch([], after))
        _, a = br.ensure_columns({"Task": "title", "Item id": "rich_text"},
                                 "tok", "board-a", record=rec)
        _, b = br.ensure_columns({"Task": "title", "Item id": "rich_text"},
                                 "tok", "board-b", record=rec)
        assert any("archived" in x for x in a), a
        assert not any("archived" in x for x in b), b

    def test_a_column_never_created_here_is_still_offered(self, monkeypatch, tmp_path):
        rec = tmp_path / "made.json"
        rec.write_text(json.dumps({"other-board": ["Link"]}), encoding="utf-8")
        sent = []
        after = {"properties": {n: {"type": ty} for n, ty in self.COMPLETE.items()}}
        monkeypatch.setattr(br, "_request", self._notion_patch(sent, after))
        br.ensure_columns(dict(self.OLD), "tok", "db", record=rec)
        assert "Link" in set(sent[0][2]["properties"]), sent

    def test_an_unreadable_schema_creates_nothing(self, monkeypatch, tmp_path):
        sent = []
        monkeypatch.setattr(br, "_request", lambda *a, **k: sent.append(a))
        assert br.ensure_columns(None, "tok", "db",
                                 record=tmp_path / "made.json") == (None, ())
        assert sent == [], sent

    def test_the_identity_columns_are_never_created(self):
        """A board with no `Item id` is not one this module should quietly reshape."""
        assert "Item id" not in br.CREATABLE and "Task" not in br.CREATABLE

    def test_every_column_it_writes_can_be_created_except_identity(self):
        """Listing only Link and Next was a half-heal: a board missing `Notes` cannot
        carry the `scope=` line, so nothing is ever archived, and one missing `Bucket`
        shows rows in none of his three sections. Both reported no problem at all
        (PR #332 reviewer round 3, major). Written out BY HAND so a column added to
        WRITES_TYPE and forgotten cannot take this test with it."""
        assert set(br.CREATABLE) == {"Notes", "Domain", "Priority", "Source",
                                     "Bucket", "Status", "Link", "Next"}, br.CREATABLE

    def test_a_board_missing_notes_and_bucket_is_healed_too(self, monkeypatch, tmp_path):
        bare = {"Task": "title", "Item id": "rich_text"}
        sent = []
        after = {"properties": {n: {"type": t} for n, t in br.WRITES_TYPE.items()}}
        monkeypatch.setattr(br, "_request", self._notion_patch(sent, after))
        out, problems = br.ensure_columns(dict(bare), "tok", "db",
                                          record=tmp_path / "made.json")
        asked = set(sent[0][2]["properties"])
        assert {"Notes", "Bucket"} <= asked, asked
        assert out["Notes"] == "rich_text", out

    def test_the_runner_checks_identity_before_it_heals(self, monkeypatch, tmp_path):
        order = []
        monkeypatch.setattr(br, "_schema_properties", lambda *a, **k: dict(self.OLD))
        monkeypatch.setattr(br, "ensure_columns",
                            lambda known, *a, **k: (order.append("heal") or dict(
                                known, Link="url", Next="rich_text"), ()))
        monkeypatch.setattr(br, "_refuse_without_identity",
                            lambda known: order.append("identity"))
        monkeypatch.setattr(br, "paint", lambda *a, **k: {
            "created": 0, "updated": 0, "archived": 0, "kept": 0, "held": 0,
            "wanted": 0, "moved": 0, "pinned": 0, "over_cap": 0, "unchanged": 0,
            "deferred": 0, "deferred_new": 0, "dropped_columns": ()})
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {})
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        # NOT THE PRODUCTION LOCK (PR #332 reviewer, major). `collect` takes a flock on
        # ~/.config/kipi/board-rows.lock, the same file the live painter holds, so the
        # suite and the 07:40 job could each block the other. Tests get their own.
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        # IDENTITY BEFORE HEAL. The first version of this test asserted the opposite
        # and called it correct, so the mistake shipped with a guard of its own: two
        # columns were PATCHed onto a database this module then rejected as not its
        # board (PR #332 reviewer, major).
        assert order == ["identity", "heal"], order


class TestAFailedColumnCreationReachesTheLine:
    """Every test that reaches the morning line stubs `ensure_columns`, so the sentence
    for a refused creation was asserted nowhere and deleting it left the suite green
    (PR #332 reviewer round 3, minor)."""

    COUNTS = {"created": 0, "updated": 0, "archived": 0, "kept": 0, "held": 0,
              "wanted": 0, "moved": 0, "pinned": 0, "over_cap": 0, "unchanged": 0,
              "deferred": 0, "deferred_new": 0, "dropped_columns": ()}

    def _line(self, monkeypatch, tmp_path, problems):
        monkeypatch.setattr(br, "_schema_properties",
                            lambda *a, **k: {"Task": "title", "Item id": "rich_text"})
        # NOT stubbed away this time: the whole point is the value it hands back.
        monkeypatch.setattr(br, "ensure_columns",
                            lambda known, *a, **k: (known, problems))
        monkeypatch.setattr(br, "paint", lambda *a, **k: dict(self.COUNTS))
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {})
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        rows, err = br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        assert err is None, err
        return rows[0]

    def test_a_refusal_is_named_on_the_line(self, monkeypatch, tmp_path):
        line = self._line(monkeypatch, tmp_path, ("HTTPError: 403 restricted",))
        assert "403 restricted" in line, line

    def test_a_clean_run_says_nothing_about_it(self, monkeypatch, tmp_path):
        line = self._line(monkeypatch, tmp_path, ())
        assert "403" not in line and "restricted" not in line, line


class TestACorruptRecordDoesNotKillTheBoardSection:
    """`_remember_columns` refused a non-dict and `_columns_made` did not, so a file
    holding a JSON list raised AttributeError out of `.get`, which no `collect` handler
    catches, and the whole section died on a malformed file this module writes itself
    (PR #332 reviewer round 5, minor)."""

    def test_a_json_list_reads_empty_not_a_crash(self, tmp_path):
        rec = tmp_path / "made.json"
        rec.write_text("[1, 2, 3]", encoding="utf-8")
        assert br._columns_made("db", rec) == set()

    def test_a_json_string_reads_empty(self, tmp_path):
        rec = tmp_path / "made.json"
        rec.write_text('"not a mapping"', encoding="utf-8")
        assert br._columns_made("db", rec) == set()

    def test_a_board_entry_that_is_not_a_list_reads_empty(self, tmp_path):
        rec = tmp_path / "made.json"
        rec.write_text(json.dumps({"db": "Link"}), encoding="utf-8")
        assert br._columns_made("db", rec) == set()

    def test_broken_json_reads_empty(self, tmp_path):
        rec = tmp_path / "made.json"
        rec.write_text("{ not json", encoding="utf-8")
        assert br._columns_made("db", rec) == set()

    def test_an_absent_file_reads_empty(self, tmp_path):
        assert br._columns_made("db", tmp_path / "never-written.json") == set()

    def test_a_good_record_still_reads(self, tmp_path):
        rec = tmp_path / "made.json"
        rec.write_text(json.dumps({"db": ["Link", "Next"]}), encoding="utf-8")
        assert br._columns_made("db", rec) == {"Link", "Next"}


class TestNoTestCanWriteTheLiveColumnRecord:
    """Three rounds of this PR found a test reaching something live, each fixed by hand.
    A hand fix protects the tests that exist; this protects the ones nobody has written
    yet (PR #332 reviewer round 7, minor)."""

    def test_writing_without_a_record_path_always_raises(self, monkeypatch):
        """NOT "under pytest". The first guard read PYTEST_CURRENT_TEST, and every test
        here that reaches `collect` deletes that variable to get past the board's own
        chokepoint, so the guard was bypassed by the exact idiom that caused the problem
        (round 9, minor). With no ambient default there is no environment to defeat."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with pytest.raises(AssertionError) as e:
            br._remember_columns("db", ["Link"])
        assert "no default" in str(e.value)

    def test_production_names_the_live_path_itself(self, monkeypatch, tmp_path):
        """The one caller allowed to touch the live record names it, so the guard above
        cannot break production. Asserted by WATCHING the call, not by grepping the
        source: the first version counted the string `record=COLUMNS_MADE` and found
        two, because the guard's own error message contains that sentence. A source
        substring is not a behaviour."""
        seen = {}
        monkeypatch.setattr(br, "_schema_properties",
                            lambda *a, **k: {"Task": "title", "Item id": "rich_text"})

        # KEYWORD-ONLY, exactly as `ensure_columns` declares it (round 4, minor). The
        # loose version accepted a positional `record`, so a `collect` that passed it
        # positionally kept this test green while the real function raised TypeError,
        # which no `collect` arm catches: the board section would die at 07:40 with a
        # bare type name. A spy looser than its subject cannot see a regression.
        def spy(known, token, db, opener=None, budget=None, *, record):
            seen["record"] = record
            return known, ()

        monkeypatch.setattr(br, "ensure_columns", spy)
        monkeypatch.setattr(br, "paint", lambda *a, **k: {
            "created": 0, "updated": 0, "archived": 0, "kept": 0, "held": 0,
            "wanted": 0, "moved": 0, "pinned": 0, "over_cap": 0, "unchanged": 0,
            "deferred": 0, "deferred_new": 0, "dropped_columns": ()})
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {})
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        assert seen.get("record") == br.COLUMNS_MADE, seen

    def test_the_live_path_is_refused_when_a_caller_names_it(self, monkeypatch, tmp_path):
        """THE REGRESSION THIS GUARD EXISTS FOR. Requiring an explicit `record=` closed
        the direct callers and opened the one that mattered: `collect` names
        COLUMNS_MADE itself, so any test reaching `collect` sailed through a check the
        previous commit would have failed (round 3, major). The signal is `sys.modules`,
        because every collect-level test here deletes PYTEST_CURRENT_TEST to get past
        the board's own chokepoint.

        _LIVE_RECORD IS REDIRECTED HERE, and that is the whole point (round 4, minor).
        The first version handed the founder's real file to the subject and trusted the
        subject to refuse it, so a regressed guard did not fail this test, it wrote his
        config and then reported a missing exception. The reviewer reproduced exactly
        that. A test whose failure mode is the incident it guards is the shape this PR
        argues against. The guard is pure path equality, so pointing both ends at tmp
        exercises identical logic and a regression writes tmp instead of home."""
        monkeypatch.setattr(br, "_LIVE_RECORD", tmp_path / "live.json")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with pytest.raises(AssertionError) as e:
            br._remember_columns("db", ["Link"], br._LIVE_RECORD)
        assert "live column record" in str(e.value)
        with pytest.raises(AssertionError):
            br._columns_made("db", br._LIVE_RECORD)
        assert not (tmp_path / "live.json").exists(), "the refusal still wrote the file"

    def test_the_guard_fires_through_collect_itself(self, monkeypatch, tmp_path):
        """The axis the name promised and the body never drove (round 4, nit). The test
        above calls the two leaf functions directly; nothing exercised the guard through
        `collect`, which is the caller the round-3 major was about.

        On his machine COLUMNS_MADE and _LIVE_RECORD are the same path. Pointing both at
        one tmp file reproduces that identity without going near his config, so `collect`
        names the live record exactly the way production does and the guard fires from
        inside `ensure_columns`, at its `_columns_made` read."""
        live = tmp_path / "made.json"
        monkeypatch.setattr(br, "_LIVE_RECORD", live)
        monkeypatch.setattr(br, "COLUMNS_MADE", live)
        monkeypatch.setattr(br, "_schema_properties",
                            lambda *a, **k: {"Task": "title", "Item id": "rich_text"})
        monkeypatch.setattr(br, "existing_rows", lambda *a, **k: {})
        def no_network(*a, **k):
            raise AssertionError("a test tried to reach Notion")
        monkeypatch.setattr(br, "_request", no_network)
        monkeypatch.setattr(br, "LOCK_FILE", tmp_path / "board-rows.lock")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("KIPI_BRIEF_DRY_RUN", raising=False)
        tf = tmp_path / "notion-token"; tf.write_text("t", encoding="utf-8")
        dbf = tmp_path / "notion-board-db"; dbf.write_text("d", encoding="utf-8")
        with pytest.raises(AssertionError) as e:
            br.collect(NOW, {}, token_file=str(tf), db_file=str(dbf))
        assert "live column record" in str(e.value)
        # NO write assertion here, deliberately (round 5, minor). The guard fires on the
        # `_columns_made` READ at the top of `ensure_columns`, and the write is past the
        # network stub, so `not live.exists()` could never have failed. A branch that
        # cannot go red reads as coverage and is not. The write path is pinned by the
        # test above, where the call reaches `_remember_columns` directly.

    def test_redirecting_columns_made_is_how_a_test_opts_in(self, monkeypatch, tmp_path):
        """The escape hatch is the same one LOCK_FILE already uses, so the habit is
        one habit rather than two."""
        monkeypatch.setattr(br, "COLUMNS_MADE", tmp_path / "made.json")
        br._remember_columns("db", ["Link"], br.COLUMNS_MADE)
        assert br._columns_made("db", br.COLUMNS_MADE) == {"Link"}

    def test_ensure_columns_cannot_be_called_without_a_record(self):
        """The refusal used to arrive from two frames down, as an AssertionError no
        `collect` arm catches, instead of from the call a person was looking at
        (round 2, minor). It is a TypeError at the call site now."""
        with pytest.raises(TypeError):
            br.ensure_columns({"Task": "title"}, "tok", "db")

    def test_reading_without_a_record_path_also_raises(self, monkeypatch):
        """The write lost its default and the comment said there was none left, while
        the READ still had one, so a caller that omitted `record=` quietly consulted
        the live file (PR #334 reviewer, minor). Half a chokepoint described as a
        whole one."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        with pytest.raises(AssertionError) as e:
            br._columns_made("db")
        assert "no default" in str(e.value)

    def test_a_private_path_is_allowed(self, tmp_path):
        rec = tmp_path / "made.json"
        br._remember_columns("db", ["Link"], rec)
        assert json.loads(rec.read_text())["db"] == ["Link"]

    # DELETED, NOT WEAKENED: `test_the_live_record_does_not_exist_after_this_suite`.
    # It asserted the absence of a file PRODUCTION writes, so the first morning the real
    # job healed a column on his board the suite would have gone red on his machine and
    # blamed itself for correct behaviour (PR #332 reviewer round 8, major). It was
    # conflating "no test wrote this" with "this never exists", and only the first is a
    # property of the suite. The chokepoint in `_remember_columns` is what actually
    # holds the rule, and it holds it at the moment of the write rather than by
    # inspecting the world afterwards.


class TestARefusedCreateStillNamesWhatItCosts:
    """The consequence belongs to the ABSENCE, not to the reason for it. It was
    attached only to his deletion, so a board where Notion refused to create `Notes`
    heard about the refusal and never that nothing would be archived (round 7)."""

    BARE = {"Task": "title", "Item id": "rich_text"}

    def test_a_refusal_names_the_cost(self, monkeypatch, tmp_path):
        def boom(*a, **k):
            raise RuntimeError("no permission")
        monkeypatch.setattr(br, "_request", boom)
        _, problems = br.ensure_columns(dict(self.BARE), "tok", "db",
                                        record=tmp_path / "made.json")
        joined = " ".join(problems)
        assert "no permission" in joined, problems
        assert "nothing is ever archived" in joined, problems
        assert "invisible on the board" in joined, problems

    def test_a_response_that_answers_but_lacks_the_column_is_not_a_success(
            self, monkeypatch, tmp_path):
        """Notion accepting the PATCH and quietly not adding the column read as a clean
        run, while the empty and refused paths both reported it (round 8, minor)."""
        after = {"properties": {"Task": {"type": "title"},
                                "Item id": {"type": "rich_text"}}}
        monkeypatch.setattr(br, "_request", lambda *a, **k: after)
        _, problems = br.ensure_columns(dict(self.BARE), "tok", "db",
                                        record=tmp_path / "made.json")
        joined = " ".join(problems)
        assert "does not carry them" in joined, problems
        assert "nothing is ever archived" in joined, problems

    def test_an_unconfirmed_create_names_the_cost(self, monkeypatch, tmp_path):
        monkeypatch.setattr(br, "_request",
                            lambda *a, **k: {"properties": {}})
        _, problems = br.ensure_columns(dict(self.BARE), "tok", "db",
                                        record=tmp_path / "made.json")
        joined = " ".join(problems)
        assert "unconfirmed" in joined and "nothing is ever archived" in joined, problems
