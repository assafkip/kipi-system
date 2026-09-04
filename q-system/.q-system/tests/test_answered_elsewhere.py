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


class TestAReplyInTheChatCounts:
    """Measured on live data: one client emailed 2026-08-05, and he sent 36 chat
    messages to them between 08-18 and 09-02. The board called it 717 hours owed."""

    def test_speaking_in_that_clients_chat_answers_their_mail(self, ae):
        kept, notes = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG,
            chat_last={"acme": dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc)})
        assert kept == []
        assert "chat" in notes[0]

    def test_ANOTHER_clients_chat_does_not_answer_it(self, ae):
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG,
            chat_last={"other": dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc)})
        assert len(kept) == 1

    def test_chat_activity_BEFORE_their_mail_does_not_answer_it(self, ae):
        kept, _ = ae.filter_answered(
            [{"id": "t1", "from": THEM, "inbound_at": "2026-08-05T20:11:00Z"}],
            cache=_cache([]), registry=REG,
            chat_last={"acme": dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)})
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
