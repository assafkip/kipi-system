#!/usr/bin/env python3
"""Six probe states, per-surface alerting, and the two decisions that are code.

Written after the first live morning surfaced four defects the original suite
could not see. Each test below names the live observation that motivates it.

THE SHAPE OF ALL FOUR DEFECTS IS THE SAME: a state the system could not
determine rendered identically to a healthy one. `1 profiles, 0 dead, 0 sent`
with rc 0 was printed by a run that learned nothing at all, because Chrome
could not even open. "Zero problems found" and "the instrument did not run"
must never be the same output.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
PROFILES_JSON = SCRIPTS / "browser_profiles.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def health():
    return _load(SCRIPTS / "browser_session_health.py", "browser_session_health")


@pytest.fixture(scope="module")
def session():
    return _load(SCRIPTS / "browser_session.py", "browser_session")


def _profile(name="research-hn", surfaces=None, root=None):
    root = root or Path("/tmp/bs-not-used")
    return {
        "name": name,
        "dir": str(root / name),
        "identity": "test identity",
        "purpose": "test",
        "kill_switch": str(root / f"{name}.disabled"),
        # Present so a load-refusal test fails for the reason it names. Without
        # it, load_profiles raised about expected_cookie_hosts instead and BOTH
        # refusal tests passed against a mutant with the check deleted
        # (N7, N12, measured 2026-08-31).
        "expected_cookie_hosts": ["news.ycombinator.com"],
        "liveness_probes": surfaces or [
            {"name": "hn", "url": "https://news.ycombinator.com/news",
             "logged_in_marker": "logout"}],
    }


def _result(surface, *, reachable=True, logged_in=True, held=False, error=None,
            reason=None):
    return {"profile": "p", "surface": surface, "url": "u",
            "reachable": reachable, "logged_in": logged_in, "held": held,
            "error": error, "reason": reason, "content_len": 10, "at": "t"}


def _prober(by_surface):
    """by_surface: {surface_name: result-dict}. Records every call."""
    calls = []

    def prober(profile, surface):
        calls.append((profile["name"], surface["name"]))
        return dict(by_surface[surface["name"]])

    prober.calls = calls
    return prober


def _recorder():
    sends = []

    def sender(message):
        sends.append(message)
        return {"delivered": True, "transport": "recorder"}

    sender.sends = sends
    return sender


# ---------------------------------------------------------------------------
# FIX 1 -- a profile held by another Chrome is its own state, and it is neither
# healthy nor an alert.
# ---------------------------------------------------------------------------

def test_a_held_profile_gets_its_own_state(health):
    """Measured live 2026-08-31 08:13: the founder's own sign-in window was
    still open, 1 Chrome process held the directory, and Playwright refused
    with "Opening in existing browser session ... already in use by another
    instance of Chromium". A Chrome persistent context is single-holder, so
    this is expected and transient, not a fault."""
    assert health.classify(_result("hn", reachable=False, logged_in=None,
                                   held=True, error="already in use")) == "held"


def test_held_is_not_dead_and_not_alive_and_not_unknown(health):
    """The whole defect: three different situations collapsing into one word."""
    seen = {
        health.classify(_result("hn")),
        health.classify(_result("hn", logged_in=False, reason="marker absent")),
        health.classify(_result("hn", reachable=False, logged_in=None,
                                error="TimeoutError")),
        health.classify(_result("hn", reachable=False, logged_in=None, held=True,
                                error="already in use")),
    }
    assert seen == {"alive", "dead", "unknown", "held"}


def test_a_held_profile_never_alerts_and_is_never_probed_twice(tmp_path, health):
    prober = _prober({"hn": _result("hn", reachable=False, logged_in=None,
                                    held=True, error="already in use")})
    sender = _recorder()
    out = health.run_once(profiles=[_profile()], prober=prober, sender=sender,
                          receipt_path=tmp_path / "r.json",
                          now=dt.datetime(2026, 8, 31, 9, 0))
    assert sender.sends == []
    assert prober.calls == [("research-hn", "hn")]
    assert out["profiles"]["research-hn"]["surfaces"]["hn"]["state"] == "held"


def test_a_held_profile_does_not_clear_a_standing_alert(tmp_path, health):
    """He signs in to repair a dead session; the window he uses is what makes
    the next probe `held`. If held cleared the alerted state, closing the
    window would produce a second alert for the same outage."""
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    # Seed a live probe first. Without it the marker has never been seen true,
    # both "dead" probes below are `unverified` and silent, and this test passes
    # against a module where held wipes the suppression (N11, 2026-08-31).
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=_recorder(), receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 8, 0))
    dead = _prober({"hn": _result("hn", logged_in=False, reason="marker absent")})
    first = _recorder()
    health.run_once(profiles=profiles, prober=dead, sender=first,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    assert len(first.sends) == 1

    held = _prober({"hn": _result("hn", reachable=False, logged_in=None,
                                  held=True, error="already in use")})
    health.run_once(profiles=profiles, prober=held, sender=_recorder(),
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 30))

    again = _recorder()
    health.run_once(profiles=profiles, prober=dead, sender=again,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 10, 0))
    assert again.sends == [], "a held probe reset the suppression and re-alerted"


def test_the_summary_line_never_reports_a_blind_run_as_zero_dead(health, capsys):
    """`1 profiles, 0 dead, 0 sent` rc 0 is what a run that learned NOTHING
    printed in production on day one. The count of surfaces that could not be
    determined has to be on the same line as the count of dead ones."""
    cycle = {"at": "t", "sends": [], "profiles": {"research-hn": {"surfaces": {
        "hn": {"state": "held"}, "li": {"state": "unknown"}}}}}
    assert health.main([], runner=lambda: cycle) == 0
    line = capsys.readouterr().out
    assert "held" in line and "unknown" in line
    assert "0 dead" not in line or ("held" in line and "unknown" in line)


# ---------------------------------------------------------------------------
# FIX 1b -- `unknown` gets a real disposition. sp-b08a139b, no longer theoretical.
# ---------------------------------------------------------------------------

def test_repeated_unknown_escalates_to_the_engineering_queue_not_the_founder(tmp_path, health):
    """An unknown is a probe that could not look. One is a blip. Four in a row
    is a broken checker, and a broken checker is an ENGINEERING signal: it goes
    to Sana's Linear queue via slack-notify.sh, not to the founder, because he
    cannot fix a browser that will not launch."""
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    broken = _prober({"hn": _result("hn", reachable=False, logged_in=None,
                                    error="TimeoutError: boom")})
    founder, ops = _recorder(), _recorder()
    for i in range(health.UNKNOWN_ESCALATION_AFTER):
        health.run_once(profiles=profiles, prober=broken, sender=founder,
                        ops_sender=ops, receipt_path=receipt,
                        now=dt.datetime(2026, 8, 31, 9, 0) + dt.timedelta(minutes=30 * i))
    assert founder.sends == [], "an unresolvable probe paged the founder"
    assert len(ops.sends) == 1, ops.sends
    assert "research-hn" in ops.sends[0] and "hn" in ops.sends[0]


def test_a_refused_alert_is_retried_next_run_and_a_delivered_one_is_not(tmp_path, health):
    """PR #294 review, major: the alerted state was stamped whether or not the
    send landed, so a Slack or Linear outage silenced a death until the browser
    state changed. Suppression starts only after a DELIVERED send."""
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=_recorder(), receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 8, 0))
    dead = _prober({"hn": _result("hn", logged_in=False, reason="marker absent")})
    refused = []

    def refuser(message):
        refused.append(message)
        return {"delivered": False, "transport": "webhook", "reason": "HTTP 502"}

    health.run_once(profiles=profiles, prober=dead, sender=refuser,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    assert len(refused) == 1
    retry = _recorder()
    health.run_once(profiles=profiles, prober=dead, sender=retry,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 30))
    assert len(retry.sends) == 1, "a refused alert must be retried on the next run"
    quiet = _recorder()
    health.run_once(profiles=profiles, prober=dead, sender=quiet,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 10, 0))
    assert quiet.sends == [], "once delivered, the same outage alerts no more"


def test_the_unknown_escalation_fires_once_not_every_run(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    broken = _prober({"hn": _result("hn", reachable=False, logged_in=None,
                                    error="TimeoutError: boom")})
    ops = _recorder()
    for i in range(health.UNKNOWN_ESCALATION_AFTER + 3):
        health.run_once(profiles=profiles, prober=broken, sender=_recorder(),
                        ops_sender=ops, receipt_path=receipt,
                        now=dt.datetime(2026, 8, 31, 9, 0) + dt.timedelta(minutes=30 * i))
    assert len(ops.sends) == 1, f"escalated {len(ops.sends)} times for one outage"


def test_a_good_probe_resets_the_unknown_counter(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    broken = _prober({"hn": _result("hn", reachable=False, logged_in=None,
                                    error="boom")})
    alive = _prober({"hn": _result("hn")})
    for i in range(health.UNKNOWN_ESCALATION_AFTER - 1):
        health.run_once(profiles=profiles, prober=broken, sender=_recorder(),
                        ops_sender=_recorder(), receipt_path=receipt,
                        now=dt.datetime(2026, 8, 31, 9, 0) + dt.timedelta(minutes=30 * i))
    health.run_once(profiles=profiles, prober=alive, sender=_recorder(),
                    ops_sender=_recorder(), receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 14, 0))
    out = health.run_once(profiles=profiles, prober=broken, sender=_recorder(),
                          ops_sender=_recorder(), receipt_path=receipt,
                          now=dt.datetime(2026, 8, 31, 14, 30))
    assert out["profiles"]["research-hn"]["surfaces"]["hn"]["consecutive_unknown"] == 1


# ---------------------------------------------------------------------------
# FIX 2 -- a probe per SURFACE, not per profile.
# ---------------------------------------------------------------------------

def test_every_declared_surface_is_probed(tmp_path, health):
    """Live 2026-08-31: research-hn held cookies for linkedin (17), reddit (8),
    google (17) and youtube (11), and the single probe watched only
    news.ycombinator.com. Every session but one had zero continuity
    monitoring, which is the entire capability."""
    prof = _profile(surfaces=[
        {"name": "hn", "url": "https://news.ycombinator.com/news", "logged_in_marker": "logout"},
        {"name": "linkedin", "url": "https://www.linkedin.com/feed/", "logged_in_marker": "logout"},
    ])
    prober = _prober({"hn": _result("hn"), "linkedin": _result("linkedin")})
    health.run_once(profiles=[prof], prober=prober, sender=_recorder(),
                    receipt_path=tmp_path / "r.json",
                    now=dt.datetime(2026, 8, 31, 9, 0))
    assert prober.calls == [("research-hn", "hn"), ("research-hn", "linkedin")]


def test_alerting_is_keyed_per_surface_not_per_profile(tmp_path, health):
    """The per-profile version of arm 4, one level down. A profile-level
    alerted_state means the second surface's death is swallowed by the first
    surface's standing alert."""
    receipt = tmp_path / "r.json"
    prof = _profile(surfaces=[
        {"name": "hn", "url": "https://a/", "logged_in_marker": "logout"},
        {"name": "linkedin", "url": "https://b/", "logged_in_marker": "logout"},
    ])
    seen = {"hn": _result("hn"), "linkedin": _result("linkedin")}
    # Both verified alive once, so neither is `unverified` later.
    health.run_once(profiles=[prof], prober=_prober(seen), sender=_recorder(),
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))

    dead_hn = {"hn": _result("hn", logged_in=False, reason="marker absent"),
               "linkedin": _result("linkedin")}
    first = _recorder()
    health.run_once(profiles=[prof], prober=_prober(dead_hn), sender=first,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 30))
    assert len(first.sends) == 1 and "hn" in first.sends[0]

    both_dead = {"hn": _result("hn", logged_in=False, reason="marker absent"),
                 "linkedin": _result("linkedin", logged_in=False, reason="marker absent")}
    second = _recorder()
    health.run_once(profiles=[prof], prober=_prober(both_dead), sender=second,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 10, 0))
    assert len(second.sends) == 1, f"expected one send about linkedin: {second.sends}"
    assert "linkedin" in second.sends[0]


# ---------------------------------------------------------------------------
# A marker never seen TRUE is unverified, not dead. This is what makes it safe
# to declare a surface whose signed-in DOM has not been observed yet.
# ---------------------------------------------------------------------------

def test_a_marker_never_observed_true_is_unverified_and_silent(tmp_path, health):
    """sp-8ee7b122, promoted here because fix 2 depends on it. Declaring a
    surface means guessing its signed-in marker. A wrong guess and a genuinely
    signed-out session are the same observation, so a marker that has never
    once been seen true must not be able to page him with a false death."""
    prober = _prober({"hn": _result("hn", logged_in=False, reason="marker absent")})
    sender = _recorder()
    out = health.run_once(profiles=[_profile()], prober=prober, sender=sender,
                          receipt_path=tmp_path / "r.json",
                          now=dt.datetime(2026, 8, 31, 9, 0))
    entry = out["profiles"]["research-hn"]["surfaces"]["hn"]
    assert entry["state"] == "unverified"
    assert entry["marker_ever_seen"] is False
    assert sender.sends == []


def test_once_the_marker_is_seen_true_a_later_absence_is_a_real_death(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=_recorder(), receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 0))
    sender = _recorder()
    out = health.run_once(
        profiles=profiles,
        prober=_prober({"hn": _result("hn", logged_in=False, reason="marker absent")}),
        sender=sender, receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 30))
    entry = out["profiles"]["research-hn"]["surfaces"]["hn"]
    assert entry["state"] == "dead" and entry["marker_ever_seen"] is True
    assert len(sender.sends) == 1


# ---------------------------------------------------------------------------
# T+0 re-stamp. The 72h clock reads off the first probe that actually saw a
# signed-in session, never off the run that happened to write the receipt.
# ---------------------------------------------------------------------------

def test_first_verified_at_is_stamped_by_the_first_true_probe(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    health.run_once(profiles=profiles,
                    prober=_prober({"hn": _result("hn", logged_in=False,
                                                  reason="marker absent")}),
                    sender=_recorder(), receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 0))
    assert health.read_receipt(receipt)["profiles"]["research-hn"]["surfaces"]["hn"][
        "first_verified_at"] is None

    out = health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                          sender=_recorder(), receipt_path=receipt,
                          now=dt.datetime(2026, 8, 31, 10, 0))
    stamped = out["profiles"]["research-hn"]["surfaces"]["hn"]["first_verified_at"]
    assert stamped == "2026-08-31T10:00:00"

    out = health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                          sender=_recorder(), receipt_path=receipt,
                          now=dt.datetime(2026, 8, 31, 11, 0))
    assert out["profiles"]["research-hn"]["surfaces"]["hn"]["first_verified_at"] == stamped


def test_a_death_voids_the_continuity_clock(tmp_path, health):
    """72 hours of continuity means 72 UNBROKEN hours. A session that died and
    was signed back in starts a new clock, or the number is a lie."""
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=_recorder(), receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 0))
    out = health.run_once(
        profiles=profiles,
        prober=_prober({"hn": _result("hn", logged_in=False, reason="marker absent")}),
        sender=_recorder(), receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 30))
    assert out["profiles"]["research-hn"]["surfaces"]["hn"]["first_verified_at"] is None


# ---------------------------------------------------------------------------
# DECISION 3 -- Reddit. Canon 2026-07-17 stays in force, and is now executable
# rather than a comment in a JSON file.
# ---------------------------------------------------------------------------

def test_a_reddit_probe_is_refused_at_load(tmp_path, health):
    bad = tmp_path / "p.json"
    prof = _profile()
    prof["liveness_probes"] = [{"name": "reddit", "url": "https://www.reddit.com/",
                                "logged_in_marker": "logout"}]
    bad.write_text(json.dumps({"research_root": "~/.config/kipi/browser-profiles",
                               "profiles": [prof]}))
    with pytest.raises(health.ProfileConfigError) as exc:
        health.load_profiles(bad)
    assert "reddit" in str(exc.value).lower()


def test_the_refusal_covers_subdomains_and_old_reddit(tmp_path, health):
    for url in ("https://old.reddit.com/r/test", "https://np.reddit.com/x",
                "https://REDDIT.com/"):
        prof = _profile()
        prof["liveness_probes"] = [{"name": "r", "url": url, "logged_in_marker": "logout"}]
        bad = tmp_path / "p.json"
        bad.write_text(json.dumps({"research_root": "~/.config/kipi/browser-profiles",
                                   "profiles": [prof]}))
        with pytest.raises(health.ProfileConfigError) as exc:
            health.load_profiles(bad)
        assert "reddit" in str(exc.value).lower(), f"refused {url} for the wrong reason"


def test_the_shipped_config_declares_no_forbidden_surface(health):
    for prof in health.load_profiles(PROFILES_JSON):
        for probe in prof["liveness_probes"]:
            assert "reddit" not in probe["url"].lower()


# ---------------------------------------------------------------------------
# DECISION 4 -- identity is the profile boundary. Recorded, and observable.
# ---------------------------------------------------------------------------

def test_every_profile_declares_the_identities_its_jar_may_hold(health):
    """Live 2026-08-31: one cookie jar held LinkedIn, Reddit, Google and
    YouTube. The plan's isolation constraint only ever separated research from
    his real Chrome, never research profiles from each other, so nothing
    noticed. A profile now has to SAY which identity it is, and an undeclared
    cookie host is recorded rather than discovered by hand months later."""
    for prof in health.load_profiles(PROFILES_JSON):
        assert prof["identity"], prof["name"]
        assert isinstance(prof.get("expected_cookie_hosts"), list)
        assert prof["expected_cookie_hosts"], prof["name"]


def test_undeclared_cookie_hosts_are_reported_not_silently_tolerated(health, tmp_path):
    prof = _profile()
    prof["expected_cookie_hosts"] = ["news.ycombinator.com"]
    found = health.undeclared_hosts(prof, hosts=[".linkedin.com", ".reddit.com",
                                                 "news.ycombinator.com",
                                                 ".doubleclick.net"])
    assert ".linkedin.com" in found and ".reddit.com" in found
    assert "news.ycombinator.com" not in found
    # Ad/tracking hosts are noise, not identities, and must not drown the signal.
    assert ".doubleclick.net" not in found


# ---------------------------------------------------------------------------
# The shipped config still loads, and still refuses a probeless profile.
# ---------------------------------------------------------------------------

def test_shipped_profiles_load_and_declare_at_least_one_surface(health):
    profiles = health.load_profiles(PROFILES_JSON)
    assert profiles
    for prof in profiles:
        assert prof["liveness_probes"]
        for probe in prof["liveness_probes"]:
            assert probe["name"] and probe["url"].startswith("https://")
            assert probe["logged_in_marker"]


def test_a_profile_with_an_empty_surface_list_is_refused(tmp_path, health):
    prof = _profile()
    prof["liveness_probes"] = []
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({"research_root": "~/.config/kipi/browser-profiles",
                               "profiles": [prof]}))
    with pytest.raises(health.ProfileConfigError) as exc:
        health.load_profiles(bad)
    assert "liveness_probes" in str(exc.value)


# ---------------------------------------------------------------------------
# CONSTRAINT 4 and CONSTRAINT 6, moved here from test_browser_session.py when
# the receipt went per-surface. Each now SEEDS a live probe first, because a
# marker that has never been seen true is `unverified` and deliberately silent.
# ---------------------------------------------------------------------------

def _seed_alive(health, profiles, receipt, at=dt.datetime(2026, 8, 31, 8, 0)):
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=_recorder(), receipt_path=receipt, now=at)


def test_c4_a_logged_out_surface_is_reported_with_a_reason(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    _seed_alive(health, profiles, receipt)
    out = health.run_once(
        profiles=profiles,
        prober=_prober({"hn": _result("hn", logged_in=False, reason="marker absent")}),
        sender=_recorder(), receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    entry = out["profiles"]["research-hn"]["surfaces"]["hn"]
    assert entry["logged_in"] is False
    assert entry["reason"], "a dead session must say why"
    assert entry["state"] == "dead"
    assert health.read_receipt(receipt)["profiles"]["research-hn"]["surfaces"]["hn"]["state"] == "dead"


def test_c4_a_dead_surface_is_probed_once_and_not_retried(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    _seed_alive(health, profiles, receipt)
    prober = _prober({"hn": _result("hn", logged_in=False, reason="marker absent")})
    health.run_once(profiles=profiles, prober=prober, sender=_recorder(),
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    assert prober.calls == [("research-hn", "hn")], "a dead session was probed twice"


def test_c6_arm1_first_death_sends_exactly_one_alert(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    _seed_alive(health, profiles, receipt)
    sender = _recorder()
    health.run_once(profiles=profiles,
                    prober=_prober({"hn": _result("hn", logged_in=False, reason="gone")}),
                    sender=sender, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 0))
    assert len(sender.sends) == 1 and "research-hn" in sender.sends[0]


def test_c6_arm2_two_further_probes_while_still_dead_are_silent(tmp_path, health):
    """THE ARM THAT MATTERS. A module alerting every run passes arm 1."""
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    _seed_alive(health, profiles, receipt)
    dead = {"hn": _result("hn", logged_in=False, reason="gone")}
    first = _recorder()
    health.run_once(profiles=profiles, prober=_prober(dead), sender=first,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    assert len(first.sends) == 1
    for minute in (30, 60):
        later = _recorder()
        health.run_once(profiles=profiles, prober=_prober(dead), sender=later,
                        receipt_path=receipt,
                        now=dt.datetime(2026, 8, 31, 9 + minute // 60, minute % 60))
        assert later.sends == [], f"alerted again at +{minute}m while still dead"


def test_c6_arm3_recovery_sends_exactly_one_line(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    _seed_alive(health, profiles, receipt)
    dead = {"hn": _result("hn", logged_in=False, reason="gone")}
    health.run_once(profiles=profiles, prober=_prober(dead), sender=_recorder(),
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    back = _recorder()
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=back, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 10, 0))
    assert len(back.sends) == 1, back.sends
    still = _recorder()
    health.run_once(profiles=profiles, prober=_prober({"hn": _result("hn")}),
                    sender=still, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 10, 30))
    assert still.sends == [], "recovery was announced twice"


def test_c6_arm4_a_second_profile_dying_alerts_while_the_first_stays_silent(tmp_path, health):
    """A module holding ONE global already-alerted flag passes arms 1-3 and
    fails here: profile A is down and already reported, and B must still land."""
    receipt = tmp_path / "r.json"
    a, b = _profile("prof-a"), _profile("prof-b")
    alive = _prober({"hn": _result("hn")})
    health.run_once(profiles=[a, b], prober=alive, sender=_recorder(),
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 8, 0))

    def mixed(states):
        calls = []

        def prober(profile, surface):
            calls.append((profile["name"], surface["name"]))
            if states[profile["name"]] == "alive":
                return _result(surface["name"])
            return _result(surface["name"], logged_in=False, reason="gone")
        prober.calls = calls
        return prober

    first = _recorder()
    health.run_once(profiles=[a, b], prober=mixed({"prof-a": "dead", "prof-b": "alive"}),
                    sender=first, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 0))
    assert len(first.sends) == 1 and "prof-a" in first.sends[0], first.sends

    quiet = _recorder()
    health.run_once(profiles=[a, b], prober=mixed({"prof-a": "dead", "prof-b": "alive"}),
                    sender=quiet, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 30))
    assert quiet.sends == [], quiet.sends

    second = _recorder()
    health.run_once(profiles=[a, b], prober=mixed({"prof-a": "dead", "prof-b": "dead"}),
                    sender=second, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 10, 0))
    assert len(second.sends) == 1, f"expected one send about prof-b: {second.sends}"
    assert "prof-b" in second.sends[0] and "prof-a" not in second.sends[0]


def test_c6_a_healthy_first_run_says_nothing(tmp_path, health):
    sender = _recorder()
    health.run_once(profiles=[_profile()], prober=_prober({"hn": _result("hn")}),
                    sender=sender, receipt_path=tmp_path / "r.json",
                    now=dt.datetime(2026, 8, 31, 9, 0))
    assert sender.sends == [], "a healthy surface paged the founder on startup"


def test_c6_an_unreachable_probe_does_not_page_and_does_not_clear_the_state(tmp_path, health):
    receipt = tmp_path / "r.json"
    profiles = [_profile()]
    _seed_alive(health, profiles, receipt)
    dead = {"hn": _result("hn", logged_in=False, reason="gone")}
    health.run_once(profiles=profiles, prober=_prober(dead), sender=_recorder(),
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 9, 0))
    blip = _recorder()
    health.run_once(profiles=profiles,
                    prober=_prober({"hn": _result("hn", reachable=False,
                                                  logged_in=None, error="boom")}),
                    sender=blip, receipt_path=receipt,
                    now=dt.datetime(2026, 8, 31, 9, 30))
    assert blip.sends == []
    again = _recorder()
    health.run_once(profiles=profiles, prober=_prober(dead), sender=again,
                    receipt_path=receipt, now=dt.datetime(2026, 8, 31, 10, 0))
    assert again.sends == [], "a blip reset the suppression and re-alerted"


def test_c6_a_kill_switched_profile_is_never_probed(tmp_path, health):
    prof = _profile(root=tmp_path)
    Path(prof["kill_switch"]).parent.mkdir(parents=True, exist_ok=True)
    Path(prof["kill_switch"]).write_text("off")
    prober = _prober({"hn": _result("hn", logged_in=False, reason="gone")})
    sender = _recorder()
    out = health.run_once(profiles=[prof], prober=prober, sender=sender,
                          receipt_path=tmp_path / "r.json",
                          now=dt.datetime(2026, 8, 31, 9, 0))
    assert prober.calls == [], "a disabled profile still opened a browser"
    assert sender.sends == []
    assert out["profiles"]["research-hn"]["state"] == "disabled"


def test_a_dead_surface_is_not_a_failed_job(health):
    """launchd-health-check reports a non-zero label as failing, so exiting 1
    on a signed-out profile reintroduces "continuously alerting" through a
    second channel. Measured under launchd 2026-08-30."""
    cycle = {"at": "t", "sends": [], "ops_sends": [],
             "profiles": {"research-hn": {"surfaces": {"hn": {"state": "dead"}}}}}
    assert health.main([], runner=lambda: cycle) == 0


def test_every_identity_in_the_jar_is_either_probed_or_declared_unmonitored(health):
    """The invariant that makes the 2026-08-31 blind spot unrepeatable. Every
    identity the config says the jar holds must be one of: probed by a surface,
    or named in unmonitored_surfaces WITH a reason. Nothing may be neither."""
    for prof in health.load_profiles(PROFILES_JSON):
        probed = " ".join(p["url"] for p in prof["liveness_probes"]).lower()
        excused = {u["host"].lower(): u.get("reason") for u
                   in prof.get("unmonitored_surfaces", [])}
        for host in prof["expected_cookie_hosts"]:
            bare = host.lower().lstrip(".")
            if bare in probed:
                continue
            if any(bare.endswith(h) or h.endswith(bare) for h in excused):
                assert next(r for h, r in excused.items()
                            if bare.endswith(h) or h.endswith(bare)), bare
                continue
            pytest.fail(f"{prof['name']} expects cookies for {host} but neither "
                        f"probes it nor declares it unmonitored")


def test_the_real_launch_error_maps_to_held(session):
    """The producer side of `held`. Every other held test injects held=True,
    which proves the state machine and proves NOTHING about detection. This
    feeds probe() the launch failure verbatim from the 2026-08-31 receipt."""
    measured = ("BrowserType.launch_persistent_context: Opening in existing "
                "browser session. This usually means that the profile is already "
                "in use by another instance of Chromium.")

    def held_fetch(profile_dir, url, timeout_ms=None):
        raise session.BrowserEnvError(f"browser launch failed for /x: {measured}")

    result = session.probe("p", "unused", "u", "logout", fetcher=held_fetch,
                           surface="hn")
    assert result.held is True
    assert result.reachable is False and result.logged_in is None


def test_an_ordinary_launch_failure_is_not_held(session):
    """The negative arm. If everything BrowserEnvError were held, a genuinely
    broken Chrome would be silently tolerated forever instead of escalating."""
    def broken_fetch(profile_dir, url, timeout_ms=None):
        raise session.BrowserEnvError(
            "browser launch failed for /x: Executable doesn't exist at /nope")

    result = session.probe("p", "unused", "u", "logout", fetcher=broken_fetch)
    assert result.held is False
