"""No spend cap in the dispatcher or the worker (RULE-2026-11-13-A).

Founder, 2026-11-13, verbatim: "I don't want a cap. We never have a cap. It's more of a
hindrance than anything else."

WHY THIS SHAPE. Every cap needs a reading of tokens or money. So this test does not hunt
stop lines (there are hundreds and most are fine). It finds every line where the
dispatcher, the worker, the door they launch claude through, and the libs they source
touch a SPEND SOURCE, directly or through a shell variable that holds one. Each such
site must match a declaration below, of one of three kinds:
  record         writes a row and cannot stop the run
  environmental  no key has credit left, or the key door is broken: the money is gone,
                 not a ceiling we chose (ASK-4714 owns plan billing after that)
  debt           a stop on a spend reading that R1 forbids, with the ticket removing it
A new cap reads a spend source somewhere, lands outside every declaration or past a
declaration's pinned count, and goes red. Debt only shrinks: a removed debt line leaves
its declaration matching nothing, and a stale declaration is red too.

NOT spend limits, never sites here, pinned by test_count_limits_are_not_spend_sites: the
review round cap (MAX_ROUNDS), the live-run cap (MAX_CONCURRENT) and the daily dispatch
count (DAILY_MAX). They count runs, not tokens or dollars.

Spend sources: every script under q-system/.q-system and plugins whose basename names
token, spend, usage, cost, budget, credit, billing, meter or breaker, minus NOT_SPEND,
plus EXTRA_SOURCES and the spend data files. A source with none of those words in its
name is this test's blind spot: add it to EXTRA_SOURCES.

SCAR: PR #783 (ASK-4721) put a 25M-per-24h token cap into both files on 2026-11-12 and
the founder closed it the next morning with the ruling above. Two older spend stops
were still live when this test was written: the worker's usage breaker (ASK-2010) and
the dispatcher's daily API-credit allowance (ASK-4311). They are the debt rows.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
S = "q-system/.q-system/scripts/"
SCANNED = ("kipi-dispatch.sh", "kipi-dispatch-pinned.sh", S + "linear-worker.sh",
           S + "converge.sh", S + "fleet-claude.sh")
SPEND_NAME = re.compile(r"(token|spend|usage|cost|budget|credit|billing|meter|breaker)", re.I)
NOT_SPEND = {
    "capability-token.sh": "an auth capability token",
    "install-capability-token.sh": "installs that auth token",
    "html-token-validator.py": "design tokens in HTML",
    "slide-token-validator.py": "design tokens in slides",
    "check_budget.py": "sizes an issue's test list to the files it touches",
    "instruction-budget-audit.py": "measures instruction file length",
    "reviewer-token-lib.sh": "the reviewer's GitHub token",
    "token-guard.py": "tool-call counts inside one session",
}
EXTRA_SOURCES = ("fleet_api_key.py",)   # answers whether any key still has credit
SPEND_DATA = ("run-tokens.jsonl", "usage-ledger.jsonl", "run-token-cap.json", "fleet-api.json")
REMOVAL = "ASK-4761"   # the ticket that removes both debt stops

# (file, needle, kind, max sites). First declaration whose needle is in the line wins.
DECLARED = (
    ("kipi-dispatch.sh", "SPEND_HELPER", "debt", 4),        # daily API-credit allowance (ASK-4311)
    ("kipi-dispatch.sh", "BUDGET_LINE", "debt", 2),
    ("kipi-dispatch.sh", "KEY_", "environmental", 7),       # the key probe: credit gone or helper broken
    ("kipi-dispatch.sh", "fleet_api_key.py", "environmental", 1),
    (S + "linear-worker.sh", "BREAKER_", "debt", 5),        # plan usage breaker (ASK-2010)
    (S + "linear-worker.sh", 'run_tokens.py" --record', "record", 1),
    (S + "fleet-claude.sh", "HELPER", "environmental", 4),  # key door: refuses only with no credit
)

SOURCED = re.compile(r'^\s*\.\s+"\$SCRIPT_DIR/([\w.-]+\.sh)"')
ASSIGN = re.compile(r"^\s*(?:local\s+|export\s+|readonly\s+)?([A-Za-z_]\w*)=")


def spend_sources():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-co", "--exclude-standard", "--",
                          "q-system/.q-system", "plugins"], capture_output=True, text=True, check=True).stdout
    names = set(EXTRA_SOURCES) | set(SPEND_DATA)
    for p in out.splitlines():
        base = p.rsplit("/", 1)[-1]
        if not base.endswith((".py", ".sh")) or "/test" in p or base.startswith(("test_", "test-")):
            continue
        if SPEND_NAME.search(base) and base not in NOT_SPEND:
            names.add(base)
    return names


def scanned_files():
    """SCANNED plus every lib they source: a cap moved into a sourced lib is still seen."""
    files = list(SCANNED)
    for f in SCANNED:
        for line in (REPO / f).read_text().splitlines():
            m = SOURCED.match(line)
            if m and S + m.group(1) not in files:
                files.append(S + m.group(1))
    return files


def sites(text, names):
    """(line number, line) of every code line touching a spend source or a var holding one."""
    lines = [(n, l) for n, l in enumerate(text.splitlines(), 1)
             if l.strip() and not l.strip().startswith("#")]
    held = set()

    def touches(line):
        return any(t in line for t in names) or any(re.search(r"\$\{?" + v + r"\b", line) for v in held)
    while True:   # a var assigned from a var that holds a source holds it too
        before = len(held)
        for _, line in lines:
            m = ASSIGN.match(line)
            if m and touches(line):
                held.add(m.group(1))
        if len(held) == before:
            break
    return [(n, line) for n, line in lines if touches(line)]


def unaccounted(rel, text, names, declared=DECLARED):
    """Sites no declaration covers, plus sites past a declaration's pinned count."""
    bad, used = [], {}
    for n, line in sites(text, names):
        hit = next((d for d in declared if d[0] == rel and d[1] in line), None)
        if hit is None:
            bad.append(f"{rel}:{n}: {line.strip()[:140]}")
            continue
        used[hit] = used.get(hit, 0) + 1
        if used[hit] > hit[3]:
            bad.append(f"{rel}:{n}: past the {hit[3]} pinned for '{hit[1]}': {line.strip()[:120]}")
    return bad, used


class NoSpendCap(unittest.TestCase):
    def setUp(self):
        self.names = spend_sources()

    def test_every_spend_site_is_declared(self):
        bad, used_all = [], {}
        for rel in scanned_files():
            b, used = unaccounted(rel, (REPO / rel).read_text(), self.names)
            bad += b
            used_all.update(used)
        self.assertEqual(bad, [], "a spend reading the founder's no-cap ruling does not allow")
        stale = [d[:2] for d in DECLARED if d not in used_all]
        self.assertEqual(stale, [], "a declaration matches nothing: remove it (debt only shrinks)")

    def test_debt_names_its_removal_ticket_in_the_ledger(self):
        ledger = (REPO / "q-system/canonical/decisions.md").read_text()
        sect = ledger.split("### RULE-2026-11-13-A", 1)[1].split("\n### ", 1)[0]
        self.assertIn(REMOVAL, sect)

    def test_known_answers_for_the_source_scan(self):
        for must in ("usage_breaker.py", "run_tokens.py", "fleet_api_spend.py", "budget_check.py"):
            self.assertIn(must, self.names)
        for never in NOT_SPEND:
            self.assertTrue(SPEND_NAME.search(never), f"{never} needs no exclusion")
            self.assertNotIn(never, self.names)

    def test_count_limits_are_not_spend_sites(self):
        for rel, word in (("kipi-dispatch.sh", "DAILY_MAX"), ("kipi-dispatch.sh", "MAX_CONCURRENT"),
                          (S + "converge.sh", "MAX_ROUNDS")):
            text = (REPO / rel).read_text()
            self.assertIn(word, text, f"{word} moved; re-pin the control")
            hits = [l for _, l in sites(text, self.names) if word in l]
            self.assertEqual(hits, [], f"{rel}: the {word} count limit read as a spend site")

    def test_negative_self_test_a_new_cap_is_caught(self):
        rel = S + "linear-worker.sh"
        base = (REPO / rel).read_text()
        direct = base + '\nif [ "$(python3 "$SCRIPT_DIR/run_tokens.py" --sum-24h)" -gt 25000000 ]; then exit 3; fi\n'
        self.assertTrue(unaccounted(rel, direct, self.names)[0])
        via_var = base + '\nCAP="$SCRIPT_DIR/budget_check.py"\nCAP2="$CAP"\npython3 "$CAP2" --cap-total 1 || exit 0\n'
        self.assertEqual(len(unaccounted(rel, via_var, self.names)[0]), 3)
        past_pin = base + '\nif [ "$BREAKER_DEFAULT" ]; then exit 3; fi\n'
        self.assertIn("past the 5 pinned", " ".join(unaccounted(rel, past_pin, self.names)[0]))


if __name__ == "__main__":
    unittest.main()
