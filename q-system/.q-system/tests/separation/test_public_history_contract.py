import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
ARCHITECTURE = REPO_ROOT / "ARCHITECTURE.md"


def decision_section():
    content = ARCHITECTURE.read_text(encoding="utf-8")
    marker = "## Public History Containment Decision"
    assert content.count(marker) == 1
    return content.split(marker, 1)[1].split("\n## ", 1)[0]


def test_public_history_decision_has_owner_and_selected_action():
    section = decision_section()

    assert "**Decision owner:** Repository owner" in section
    assert "**Decision:** Document current exposure" in section
    assert "**Status:** Accepted" in section


def test_no_history_rewrite_is_authorized():
    section = decision_section()

    assert section.count("**Constraint:**") == 1
    assert "No history rewrite is authorized by this program." in section
    assert "separate approved PRD" in section
    assert "coordinated security response" in section
    normalized = section.lower().replace(
        "no history rewrite is authorized by this program.",
        "",
    )
    assert not re.search(
        r"(authorize|permit|allow).{0,80}"
        r"(history rewrite|force.?push|remote reference)",
        normalized,
    )
    for destructive_token in (
        "git filter-repo",
        "git reset --hard",
        "git push --force",
        "force-push",
        "force push",
        "delete remote reference",
    ):
        assert destructive_token not in normalized


def test_decision_preserves_current_containment_work():
    section = decision_section()

    assert "verified instance owner" in section
    assert "generic working tree" in section
    assert "does not erase historical objects" in section


def test_future_trigger_and_verification_are_explicit():
    section = decision_section()

    assert "**Escalation trigger:**" in section
    assert "**Verification:**" in section
    assert "repository host" in section
