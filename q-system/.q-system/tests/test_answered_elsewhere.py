"""A thread he answered SOMEWHERE ELSE is not owed."""
import datetime as dt
import importlib.util
import pathlib

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def _load(stem):
    spec = importlib.util.spec_from_file_location(stem, SCRIPTS / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ae():
    return _load("answered_elsewhere")


HIM = "assaf@askconsulting.io"
THEM = "audrey@example.com"


def _msg(sender, to, date):
    return {"sender": sender, "toRecipients": [to], "date": date}


def _cache(msgs):
    return {"t1": {"id": "t1", "messages": msgs}}


REG = {"clients": [{"slug": "acme", "contacts": [{"email": THEM}]}]}


class TestAReplyInAnotherThreadCounts:
    """He answers by starting a new mail instead of hitting reply, and the old
    thread stays open forever. A model reading one thread cannot see that."""

    def test_a_later_mail_to_the_same_address_answers_it(self, ae):
        cache = {
            "old": {"messages": [_msg(THEM, HIM, "2026-08-05T20:11:00Z")]},
            "new": {"messages": [_msg(HIM, THEM, "2026-08-19T09:00:00Z")]},
        }
        kept, notes = ae.filter_answered(
            [{"id": "old", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=cache, registry=REG)
        assert kept == []
        assert notes and "answered by mail" in notes[0]

    def test_a_mail_he_sent_BEFORE_theirs_does_not_answer_it(self, ae):
        cache = _cache([_msg(HIM, THEM, "2026-08-01T09:00:00Z"),
                        _msg(THEM, HIM, "2026-08-05T20:11:00Z")])
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=cache, registry=REG)
        assert len(kept) == 1, "a reply that predates their mail is not a reply to it"

    def test_a_mail_to_SOMEBODY_ELSE_does_not_answer_it(self, ae):
        cache = _cache([_msg(HIM, "other@example.com", "2026-08-19T09:00:00Z")])
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=cache, registry=REG)
        assert len(kept) == 1


class TestPresenceIsNotAReply:
    """Reviewer, PR #300: the first rule dropped a mail the moment his LAST chat
    message postdated it. For a client he talks to daily that deleted every email
    older than this morning -- a two-hour-old signature request and a twenty-day
    overdue invoice both vanish because he said something in the chat at 10am."""

    def test_one_chat_day_does_NOT_answer_a_recent_mail(self, ae):
        """He mailed at 09:00, chatted at 10:00. That is not evidence."""
        today = dt.datetime.now(dt.timezone.utc)
        kept, notes = ae.filter_answered(
            [{"id": "t1", "from": THEM, "age_hours": 2}],
            cache=_cache([]), registry=REG,
            chat_days={"acme": [today.date()]})
        assert len(kept) == 1
        assert any("presence is not a reply" in n for n in notes)

    def test_two_chat_days_still_does_not(self, ae):
        base = dt.datetime.now(dt.timezone.utc)
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "age_hours": 100}],
            cache=_cache([]), registry=REG,
            chat_days={"acme": [(base - dt.timedelta(days=d)).date() for d in (0, 1)]})
        assert len(kept) == 1

    def test_sustained_engagement_DOES(self, ae):
        """The case this rule was built from: they mailed, and he then wrote in their
        chat on many separate days."""
        base = dt.datetime.now(dt.timezone.utc)
        kept, notes = ae.filter_answered(
            [{"id": "t1", "from": THEM, "age_hours": 24 * 20}],
            cache=_cache([]), registry=REG,
            chat_days={"acme": [(base - dt.timedelta(days=d)).date()
                                for d in range(0, 12)]})
        assert kept == []
        assert any("on 12 days" in n for n in notes)

    def test_chat_days_BEFORE_their_mail_never_count(self, ae):
        base = dt.datetime.now(dt.timezone.utc)
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "age_hours": 1}],
            cache=_cache([]), registry=REG,
            chat_days={"acme": [(base - dt.timedelta(days=d)).date()
                                for d in range(1, 30)]})
        assert len(kept) == 1

    def test_the_OLD_single_timestamp_caller_answers_nothing(self, ae):
        """One timestamp cannot show sustained engagement, so a caller that was
        never updated must KEEP rows, not silently drop them on weak evidence."""
        kept, notes = ae.filter_answered(
            [{"id": "t1", "from": THEM, "age_hours": 500}],
            cache=_cache([]), registry=REG,
            chat_last={"acme": dt.datetime.now(dt.timezone.utc)})
        assert len(kept) == 1
        assert any("single-timestamp" in n for n in notes)


class TestItReallyNeverRaises:
    def test_a_cache_that_is_not_a_map_keeps_everything(self, ae):
        kept, notes = ae.filter_answered([{"id": "t1", "from": THEM, "age_hours": 5}],
                                         cache=["not", "a", "map"], registry=REG)
        assert len(kept) == 1 and any("not a map" in n for n in notes)

    def test_a_registry_that_is_not_a_map_keeps_everything(self, ae):
        kept, _ = ae.filter_answered([{"id": "t1", "from": THEM, "age_hours": 5}],
                                     cache=_cache([]), registry="nonsense")
        assert len(kept) == 1


class TestTheAllowlistHasTwoReaders:
    """The file grew a second column for the commitment miner and this reader was
    never taught it, so the allowlist held "116326607 acme-corp", matched no group
    id, and the section rendered "nothing" live for hours."""

    def test_a_two_column_line_still_yields_the_bare_id(self, tmp_path):
        gm = _load("groupme_inbox")
        f = tmp_path / "groupme-channels"
        f.write_text("# note\n116326607 acme-corp\n999 other\n", encoding="utf-8")
        assert gm.load_allowlist(f) == {"116326607", "999"}

    def test_both_readers_agree_on_the_same_file(self, tmp_path, ae):
        gm = _load("groupme_inbox")
        f = tmp_path / "groupme-channels"
        f.write_text("116326607 acme-corp\n", encoding="utf-8")
        assert set(ae.channel_slugs(f)) == gm.load_allowlist(f), (
            "the two readers of this file disagree, which is how it broke")


class TestAReplyInTheChatCounts:
    """Measured on live data: one client emailed 2026-08-05, and he sent 36 chat
    messages to them between 08-18 and 09-02. The board called it 717 hours owed."""

    def test_speaking_in_that_clients_chat_answers_their_mail(self, ae):
        """Now requires SUSTAINED engagement, not one last-seen stamp: see
        TestPresenceIsNotAReply for why a single message cannot answer a mail."""
        days = [dt.date(2026, 8, 18) + dt.timedelta(days=d) for d in range(0, 15, 2)]
        kept, notes = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG, chat_days={"acme": days})
        assert kept == []
        assert "chat" in notes[0]

    def test_ANOTHER_clients_chat_does_not_answer_it(self, ae):
        days = [dt.date(2026, 8, 18) + dt.timedelta(days=d) for d in range(0, 15, 2)]
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG, chat_days={"other": days})
        assert len(kept) == 1

    def test_chat_activity_BEFORE_their_mail_does_not_answer_it(self, ae):
        days = [dt.date(2026, 7, 1) + dt.timedelta(days=d) for d in range(0, 20)]
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG, chat_days={"acme": days})
        assert len(kept) == 1


class TestEveryUncertaintyKeepsTheRow:
    """Answering here REMOVES a row from his board. A wrong removal hides work he
    owes; a wrong keep costs one glance. So doubt resolves toward keeping."""

    def test_a_thread_with_no_parseable_address_is_kept(self, ae):
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": "Audrey", "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG)
        assert len(kept) == 1

    def test_a_thread_with_no_timestamp_at_all_is_kept(self, ae):
        kept, _ = ae.filter_answered([{"id": "t1", "from": THEM}],
                                     cache=_cache([]), registry=REG)
        assert len(kept) == 1

    def test_an_unreadable_cache_keeps_EVERYTHING_and_says_so(self, ae, monkeypatch):
        monkeypatch.setattr(ae, "CACHE", pathlib.Path("/nonexistent/nope.json"))
        kept, notes = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}])
        assert len(kept) == 1
        assert notes and "unreadable" in notes[0]

    def test_age_hours_is_used_when_no_inbound_date_is_given(self, ae):
        """The live producer returns age_hours, not a date."""
        recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
        cache = _cache([_msg(HIM, THEM, recent.isoformat())])
        kept, _ = ae.filter_answered([{"id": "t1", "from": THEM, "age_hours": 100}],
                                     cache=cache, registry=REG)
        assert kept == [], "a reply 2h ago answers a mail from 100h ago"


class TestClientMatchingIsExact:
    def test_a_domain_match_is_not_a_client_match(self, ae):
        """Answering one client's mail with another's chat is worse than keeping it."""
        assert ae.client_of("someone@example.com", REG) is None
        assert ae.client_of(THEM, REG) == "acme"
