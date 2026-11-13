"""Every 2026-11-13 ruling and decision in decisions.md names code that holds it.

Founder, 2026-11-13, verbatim: "remember - every decision needs to be anchored in code."
This reads RULE-2026-11-13-A to F in q-system/canonical/decisions.md, and it is the
holder of RULE-2026-11-13-F's verdict table (D2).

The contract per entry, the same linkage rule_gate applies to rule files:
  ENFORCED  every backticked path in "Held by" exists, and the first one names the rule id
  PARTIAL   the same, plus a "Not yet" line naming the ticket that builds the rest
  ADVISORY  "Held by" names no code path (no fake enforcer), and "Advisory because" says why
Limit: this proves linkage. Review proves the named code does what the entry says.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LEDGER = REPO / "q-system/canonical/decisions.md"
IDS = tuple(f"RULE-2026-11-13-{c}" for c in "ABCDEF")
PATH_RX = re.compile(r"`([\w.-]+(?:/[\w.-]+)+)`")
ORIGIN_RX = re.compile(r"\[(USER-DIRECTED|SYSTEM-INFERRED|COUNCIL-DEBATED|CLAUDE-RECOMMENDED -> [A-Z]+)\]")
D2_ROW = re.compile(r"^\| ([1-6]) \| [^|]+ \| (code|model) \| ([^|]*) \|", re.M)


def section(text, rid):
    parts = text.split("### " + rid + ":", 1)
    return parts[1].split("\n### ", 1)[0].split("\n## ", 1)[0] if len(parts) == 2 else ""


def field(sect, name):
    m = re.search(r"^- \*\*" + re.escape(name) + r":\*\* (.+)$", sect, re.M)
    return m.group(1).strip() if m else ""


def problems(text, rid, repo=REPO):
    s = section(text, rid)
    if not s:
        return [f"{rid}: no entry"]
    out = []
    if not ORIGIN_RX.search(field(s, "Origin")):
        out.append(f"{rid}: no origin tag")
    status = field(s, "Enforcement").split(" ")[0]
    paths = PATH_RX.findall(field(s, "Held by"))
    if status not in ("ENFORCED", "PARTIAL", "ADVISORY"):
        out.append(f"{rid}: Enforcement is '{status}'")
    if status in ("ENFORCED", "PARTIAL"):
        missing = [p for p in paths if not (repo / p).exists()]
        if not paths:
            out.append(f"{rid}: names no enforcer")
        out += [f"{rid}: {p} does not exist" for p in missing]
        if paths and not missing and rid not in (repo / paths[0]).read_text():
            out.append(f"{rid}: {paths[0]} does not name {rid}")
    if status == "PARTIAL" and not re.search(r"ASK-\d+", field(s, "Not yet")):
        out.append(f"{rid}: PARTIAL with no ticket for the rest")
    if status == "ADVISORY":
        if paths:
            out.append(f"{rid}: ADVISORY but Held by names code")
        if len(field(s, "Advisory because")) < 60:
            out.append(f"{rid}: ADVISORY with no reason")
    return out


def d2_problems(text):
    rows = D2_ROW.findall(section(text, "RULE-2026-11-13-F"))
    out = [] if sorted(r[0] for r in rows) == list("123456") else [f"D2 rows {[r[0] for r in rows]}"]
    return out + [f"D2 row {n}: code verdict names no ticket" for n, v, t in rows
                  if v == "code" and not re.search(r"ASK-\d+", t)]


class RulingsAnchored(unittest.TestCase):
    def test_each_entry_names_code_that_holds_it(self):
        text = LEDGER.read_text()
        self.assertEqual([p for rid in IDS for p in problems(text, rid)], [])

    def test_d2_has_six_verdicts_and_each_code_one_has_a_ticket(self):
        self.assertEqual(d2_problems(LEDGER.read_text()), [])

    def test_negative_self_test_each_check_can_fail(self):
        def entry(status, held, extra=""):
            return (f"### RULE-NEG-9: t\n- **Origin:** [SYSTEM-INFERRED]\n- **Enforcement:** {status}\n"
                    f"- **Held by:** {held}\n{extra}")
        me = "`q-system/.q-system/tests/test_rulings_anchored.py`"
        self.assertEqual(problems(entry("ENFORCED", me).replace("RULE-NEG-9", IDS[5]), IDS[5]), [])
        cases = (
            entry("ENFORCED", "`no/such/file.py`"),
            entry("ENFORCED", "nothing"),
            entry("ENFORCED", "`q-system/canonical/decisions.md`"),   # exists, never names RULE-NEG-9
            entry("PARTIAL", me),
            entry("ADVISORY", me, "- **Advisory because:** " + "x" * 80 + "\n"),
            entry("ADVISORY", "nothing", "- **Advisory because:** short\n"),
            entry("DONE", me),
            entry("ENFORCED", me).replace("[SYSTEM-INFERRED]", "Sana"),
        )
        for i, c in enumerate(cases):
            self.assertTrue(problems(c, "RULE-NEG-9"), f"case {i} passed")
        self.assertTrue(d2_problems("### RULE-2026-11-13-F: x\n| 1 | a | code | none |\n"))


if __name__ == "__main__":
    unittest.main()
