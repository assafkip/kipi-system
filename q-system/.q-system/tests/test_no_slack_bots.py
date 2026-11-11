"""Census: no tracked code in the skeleton posts to or reads from Slack (RULE-2026-11-11-A).

Founder, 2026-11-11, verbatim: "part of your plan needs to be to remove all bots
from slack. No bots should be there".

WHY A CENSUS AND NOT A CALL-SITE CHECK. The skeleton had a Slack sender module
(slack_founder.py) plus a webhook reader in each of three scripts and their tests.
Fixing the senders someone remembers leaves the next one live, so this walks every
tracked file. It reads `git ls-files`, not the working tree, so an untracked scratch
file cannot turn it red and a tracked one cannot hide.

This is the same census consulting carries (q-consult/pipeline/tests/test_no_slack_bots.py,
same patterns). Consulting's copy of the skeleton arrives by sync, so a sender removed
here leaves consulting's shrink-only list when this lands there.

WHAT IT EXCLUDES, EACH WITH ITS REASON:
- docs and history: *.md, *.jsonl, logs, .prd-os/, q-system/output/. They talk about
  Slack; they do not call it.
- .review-tmp-pr11/ and .review-scratch/: stray review trees, not code that runs.
- this file: it names the patterns.
"""
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

#: Built from pieces so this file never matches itself (it is also excluded).
_PATTERNS = [
    r"hooks\.slack" + r"\.com",
    r"chat\.post" + r"Message",
    r"slack" + r"_sdk",
    r"slack\.com" + r"/api",
    r"xox" + r"[bpa]-",
    # a READ of the env var: os.environ / getenv / shell ${VAR}
    r"(?:environ|getenv)[^\n]{0,24}SLACK_\w*(?:WEBHOOK|BOT_TOKEN)",
    r"\$\{?\w*SLACK_\w*(?:WEBHOOK|BOT_TOKEN)",
    # the credential files the old senders read, inside a quoted path (prose that
    # names the file in backticks is not a read)
    r"[\"'][^\"'\n]*kipi/slack" + r"-(?:webhook|bot-token)",
    r"ask-crm-slack" + r"-token",
]
CENSUS = re.compile("|".join("(?:%s)" % p for p in _PATTERNS))

_SKIP_SUFFIX = (".md", ".jsonl", ".log", ".out", ".err", ".bak", ".png", ".jpg", ".pdf",
                ".woff2", ".ico", ".svg", ".xlsx", ".docx")
_SKIP_PREFIX = (
    ".prd-os/",
    ".review-tmp-pr11/",
    ".review-scratch/",
    "q-system/output/",
    "q-system/.q-system/tests/test_no_slack_bots.py",
    # This file reaches every instance through kipi update, where REPO is the
    # instance root. These are consulting's exclusions, the same ones its twin
    # (q-consult/pipeline/tests/test_no_slack_bots.py) carries, so the census is
    # green in both repos (PR #519 review, minor): the secret scanners hold token
    # SHAPES on purpose, output is generated, and SEND_SHAPES in test_bookings.py
    # is a detector list that sends nothing.
    "q-consult/output/",
    "gtm/scripts/secret_scan/",
    "gtm/scripts/env_ref_scan/",
    "q-consult/pipeline/tests/test_no_slack_bots.py",
    "q-consult/pipeline/tests/test_bookings.py",
)


def scan_text(text):
    """Line numbers of every census hit in `text`."""
    return [n for n, line in enumerate(text.splitlines(), 1) if CENSUS.search(line)]


def _skipped(rel):
    return rel.endswith(_SKIP_SUFFIX) or rel.startswith(_SKIP_PREFIX)


def census(root=REPO):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    hits = []
    for rel in out.stdout.decode("utf-8", "replace").split("\0"):
        if not rel or _skipped(rel):
            continue
        try:
            with open(os.path.join(root, rel), "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for n in scan_text(text):
            hits.append("%s:%d" % (rel, n))
    return hits


def test_no_tracked_code_posts_to_or_reads_slack():
    hits = census()
    assert not hits, "Slack sender or reader still in the tree:\n" + "\n".join(hits)


def test_negative_self_test_a_webhook_in_a_py_is_caught(tmp_path):
    """A check that cannot fail is not a check. Prove the matcher and the walk
    both catch the bad case, on a throwaway repo, never the live tree."""
    repo = tmp_path / "r"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    for k in [k for k in env if k.startswith("GIT_") and k not in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")]:
        env.pop(k)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    (repo / "bad.py").write_text("URL = 'https://hooks." + "slack.com/services/T/B/x'\n")
    (repo / "good.py").write_text("print('telegram')\n")
    (repo / "notes.md").write_text("we retired hooks." + "slack.com\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    assert census(str(repo)) == ["bad.py:1"]


@pytest.mark.parametrize("line", [
    "requests.post('https://slack." + "com/api/chat.post" + "Message')",
    "from slack" + "_sdk import WebClient",
    "tok = 'xox" + "b-123'",
    "os.environ.get('KIPI_SLACK_BOT" + "_TOKEN')",
    "TOKEN=\"${KIPI_SLACK_BOT" + "_TOKEN:-}\"",
    "W = Path('~/.config/kipi/slack" + "-webhook')",
])
def test_every_pattern_catches_its_shape(line):
    assert scan_text(line) == [1]


def test_prose_naming_an_env_var_is_not_a_read():
    assert scan_text("the strings `KIPI_SLACK_WEB" + "HOOK` stay out of code") == []
