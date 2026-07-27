#!/usr/bin/env python3
"""The SEVENTH review's own probes, re-run against the reworked tree.

Not a paraphrase: each block is the reviewer's reproducer, with their expected
values as assertions. Runnable from the PR head, so the claim "your corpora pass"
is checkable rather than asserted.

Run: python3 q-system/output/ask150-review7-corpus.py   (exit 0 = pass)
"""

import importlib.util
import re
import sys
from pathlib import Path

HEALTH = Path(__file__).resolve().parents[1] / ".q-system/scripts/fleet-health-daily.py"
_spec = importlib.util.spec_from_file_location("fh", HEALTH)
fh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fh)

# The suite's own FakeLinear, imported rather than re-implemented: a second fake
# would drift from the one the contract is proven against.
TEST = HEALTH.parent / "test/test-fleet-health-daily.py"
_src = TEST.read_text().split("# --- the shipped registry must satisfy its own contract")[0]
_ns = {"__name__": "fake_linear_only", "__file__": str(TEST)}
exec(compile(_src, str(TEST), "exec"), _ns)  # noqa: S102 - the suite's own fixture code
FakeLinear = _ns["FakeLinear"]

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


LINE_1 = "0 3 * * * cd ~/p && timeout 1800 claude -p 'sweep' </dev/null"
LINE_2 = "30 4 * * * claude -p 'second job added a month later'"


def rollup(cron_text):
    out = fh.detect_cron_shells_claude(None, cron_text=cron_text)
    for f in out:
        f["key"] = fh.finding_key("cron-shells-claude", f["subject"])
        f["detector"] = "cron-shells-claude"
    return out


# --- finding 1: the reviewer's exact driver ---------------------------------
# "day 1: create / operator annotates it / unchanged / crontab grows"
print("finding 1 - operator annotation across a CONTENT change")
NOTE = "operator note: waiting on the mini"
fake = FakeLinear()
fh.file_findings(rollup(LINE_1 + "\n"), apply=True, linear=fake)
fake.issues["id-1"]["description"] += "\n\n" + NOTE
check("note present after annotation", NOTE in fake.issues["id-1"]["description"], True)
same = fh.file_findings(rollup(LINE_1 + "\n"), apply=True, linear=fake)
check("unchanged run issues no update", same["updated"], 0)
check("unchanged run  -> note present", NOTE in fake.issues["id-1"]["description"], True)
grown = fh.file_findings(rollup(LINE_1 + "\n" + LINE_2 + "\n"), apply=True, linear=fake)
check("changed run DOES update", grown["updated"], 1)
check("changed   run  -> note present", NOTE in fake.issues["id-1"]["description"], True)

# The reviewer's ASK-148 migration driver: pre-hash body, built the way the
# suite's own `legacy` block builds it, plus an operator note.
print("finding 1 - the pre-hash migration of every live fleet-health issue")
_lf = rollup(LINE_1 + "\n")[0]
mig = FakeLinear()
mig.issues["id-legacy"] = {
    "identifier": "ASK-148",
    "title": _lf["title"],
    "description": (f"<!-- kipi-key: {_lf['key']} -->\n\n{_lf['body']}\n\n"
                    f"Filed by `fleet-health-daily.py`.\n\n{NOTE}"),
    "state_type": "unstarted",
}
check("BEFORE first post-merge 08:15 run -> note present",
      NOTE in mig.issues["id-legacy"]["description"], True)
out = fh.file_findings(rollup(LINE_1 + "\n"), apply=True, linear=mig)
check("outcome  updated", out["updated"], 1)
check("AFTER                            -> note present",
      NOTE in mig.issues["id-legacy"]["description"], True)
check("mutations issued", [q for q, _ in mig.mutations], ["ISSUE_UPDATE"])

# --- finding 2: the reviewer's five leak shapes ------------------------------
print("finding 2 - a credential must not reach a permanent issue")
# The reviewer's own values, composed from variables rather than written as a
# literal NAME=value: a script proving secrets get redacted must not carry one.
_LINEAR, _NOTION = "lin" + "_api_L1v3T0k3nAAAA", "ntn" + "_deadbeefdeadbeef"
_JWT, _PG = "eyJhbGciOiJIUzI1NiJ9secret", "hunter2hunter2"
SECRETS = [_LINEAR, _NOTION, _JWT, _PG]
CASES = [
    ("nested single-quote shell -c",
     f"""0 3 * * * bash -lc 'LINEAR_API_KEY={_LINEAR} claude -p "sweep"'"""),
    ("nested double-quote shell -c",
     f'0 3 * * * bash -lc "NOTION_TOKEN={_NOTION} claude -p x"'),
    ("after a semicolon, no space",
     f"0 3 * * * cd /x;SUPABASE_SERVICE_KEY={_JWT} claude -p x"),
    ("after (,  subshell", f"0 3 * * * (PGPASSWORD={_PG} claude -p x)"),
    ("plain, space-preceded (control)",
     f"0 3 * * * ANTHROPIC_API_KEY={_PG} claude -p x"),
]
for label, line in CASES:
    check(f"detected=True  [{label}]",
          bool(fh.detect_cron_shells_claude(None, cron_text=line + "\n")), True)
    check(f"leak=[]        [{label}]",
          [t for t in SECRETS if t in fh._redact_secrets(line)], [])

# --- finding 3: the reviewer's substitution / xargs corpus -------------------
print("finding 3 - substitution and xargs are no longer silent misses")
for cmd, want in [("xargs -I{} claude -p {} < list", True),
                  ("OUT=$(claude -p 'x'); echo $OUT", True),
                  ("OUT=`claude -p 'x'`", True)]:
    check(f"want={want}  {cmd!r}", fh._shells_claude(cmd), want)

# --- their round-3/4/5 corpora, re-run so the widening bought no regression --
print("prior rounds - the false-positive corpus must still hold")
HOUSEKEEPING = [
    "0 2 * * * tar czf ~/backups/claude.tgz ~/projects/claude --exclude=.git",
    "15 2 * * * rsync -a ~/projects/claude/ ~/backups/claude/",
    "30 2 * * * du -sh ~/projects/claude",
    "45 2 * * * cd ~/projects/claude && git gc --prune=now",
    "0 3 * * * chmod -R go-w ~/projects/claude",
]
for line in HOUSEKEEPING:
    check(f"benign: {line[:46]!r}", fh._shells_claude(fh._cron_command(line)), False)
for cmd, want in [
    ('notify-send "run claude -p tomorrow"', False),
    ('echo "step one; claude -p x"', False),
    ("claude-code --version", False),
    ("bash ~/.claude/hooks/rotate-logs.sh", False),
    ("flock -n /tmp/claude.lock /opt/svc/run.sh", False),
    ("ssh claude@mini ./run.sh", False),
    ("sudo -Hu claude /opt/svc/run.sh", False),
    ("command -v claude", False),
    ("timeout 1800 claude -p 'x' </dev/null", True),
    ("bash -lc 'claude -p \"x\"'", True),
    ("flock -n /tmp/x.lock claude -p x", True),
    ("sudo -uH claude -p 'x'", True),
    ("{ claude -p x ; }", True),
    ("if claude -p x ; then true ; fi", True),
    ("command claude -p x", True),
]:
    check(f"want={want}  {cmd!r}", fh._shells_claude(cmd), want)

# The splice's consumer: linear-sync parses this marker fleet-wide.
body = fake.issues["id-1"]["description"]
check("exactly one kipi-key marker in a spliced body",
      len(re.findall(r"<!--\s*kipi-key:", body)), 1)
check("exactly one kipi-hash marker in a spliced body",
      len(re.findall(r"<!--\s*kipi-hash:", body)), 1)

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: the seventh review's own corpora, and every prior round's, hold")
sys.exit(0)
