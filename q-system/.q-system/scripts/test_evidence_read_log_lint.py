#!/usr/bin/env python3
"""Tests for evidence-read-log-lint.py (ASK-438).

The three ids below are the ticket's three catchable scars, taken verbatim from the
issue: each was cited in a record while the session had never opened its row.

The transcript fixtures copy the SHAPE of a real case found by the pre-wiring replay
(2026-09-23, a subagent writing a client note under output/): the id reached the
session only through a Read of a canonical decisions log, a summary, never through the
ledger. Record layout (`type`, `message.content[]` with `tool_use` / `tool_result`,
`tool_use_id`) is copied from that transcript; paths and text are scrubbed because
this repo is public.

Every case runs the hook as a subprocess with a real stdin payload, the way Claude
Code calls it, inside a throwaway directory. Nothing here reads or writes a live path.
Run: python3 test_evidence_read_log_lint.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = Path(os.environ.get("EVIDENCE_READ_LOG_LINT", HERE / "evidence-read-log-lint.py"))
LEDGER = HERE / "evidence_ledger.py"

SCARS = ("ev-dff4be2c63", "ev-5d89ba6c80", "ev-b21a3e4aaf")


def _use(uid, name, inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": uid, "name": name, "input": inp}]}}


def _result(uid, text):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid,
         "content": [{"type": "text", "text": text}]}]}}


def summary_read(ident):
    """The real shape: the id arrives inside a decisions log, not the ledger."""
    return [_use("t1", "Read", {"file_path": "~/<instance>/canonical/decisions.md"}),
            _result("t1", f"  12\t- transfer landed [{ident}] (see ledger)\n")]


def ledger_show(ident):
    row = {"claim_id": ident, "claim": "<scrubbed>", "source": "<scrubbed>",
           "command": "<scrubbed>", "result": "<scrubbed>", "verified_at": "2026-08-05"}
    return [_use("t2", "Bash", {"command": f"python3 evidence_ledger.py show {ident}"}),
            _result("t2", json.dumps(row))]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="erl-"))
        self.out = self.tmp / "inst" / "output"
        self.out.mkdir(parents=True)

    def transcript(self, records, name="sess.jsonl", where=None):
        p = (where or self.tmp) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r) + "\n" for r in records))
        return p

    def run_hook(self, payload, mode=None):
        env = {k: v for k, v in os.environ.items() if k != "KIPI_EVIDENCE_READ_LOG_MODE"}
        env["CLAUDE_PROJECT_DIR"] = str(self.tmp)
        if mode:
            env["KIPI_EVIDENCE_READ_LOG_MODE"] = mode
        self.assertTrue(LINT.is_file(), f"lint under test is missing: {LINT}")
        return subprocess.run([sys.executable, str(LINT)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)

    def write(self, body, transcript, name="note.md", original=None):
        fp = self.out / name
        fp.write_text(body)
        return {"tool_name": "Write", "transcript_path": str(transcript),
                "tool_input": {"file_path": str(fp), "content": body},
                "tool_response": {"type": "create" if original is None else "update",
                                  "filePath": str(fp), "originalFile": original}}


class TheThreeScars(Base):
    def test_each_scar_cited_from_a_summary_is_blocked(self):
        for ident in SCARS:
            with self.subTest(ident=ident):
                t = self.transcript(summary_read(ident))
                r = self.run_hook(self.write(f"The transfer landed [{ident}].\n", t))
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn(ident, r.stderr)
                self.assertIn(f"evidence_ledger.py show {ident}", r.stderr)

    def test_the_same_citation_after_opening_the_row_passes(self):
        for ident in SCARS:
            with self.subTest(ident=ident):
                t = self.transcript(summary_read(ident) + ledger_show(ident))
                r = self.run_hook(self.write(f"Not landed [{ident}].\n", t))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr, "")

    def test_a_block_leaves_a_calibration_row(self):
        t = self.transcript(summary_read(SCARS[0]))
        self.run_hook(self.write(f"x [{SCARS[0]}]\n", t))
        log = self.tmp / "q-system/output/evidence-read-log-lint.jsonl"
        rows = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual([r["ids"] for r in rows], [[SCARS[0]]])
        self.assertEqual(rows[0]["event"], "blocked")


class OnlyNewIdsAndOnlyLedgerReads(Base):
    def test_an_id_already_in_the_file_is_not_new(self):
        t = self.transcript([])
        old = f"Earlier line [{SCARS[1]}].\n"
        r = self.run_hook(self.write(old + "A new line.\n", t, original=old))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_edit_that_moves_an_existing_id_passes(self):
        t = self.transcript([])
        fp = self.out / "e.md"
        after = f"Top [{SCARS[2]}]\nrest\n"
        fp.write_text(after)
        payload = {"tool_name": "Edit", "transcript_path": str(t),
                   "tool_input": {"file_path": str(fp), "old_string": f"rest [{SCARS[2]}]",
                                  "new_string": "rest"},
                   "tool_response": {"filePath": str(fp)}}  # no originalFile: rebuild it
        # before = after with "rest" -> "rest [id]" (first occurrence only) holds the id
        r = self.run_hook(payload)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_edit_that_adds_an_id_is_checked_without_original_file(self):
        t = self.transcript([])
        fp = self.out / "e2.md"
        fp.write_text(f"line [{SCARS[0]}]\n")
        payload = {"tool_name": "Edit", "transcript_path": str(t),
                   "tool_input": {"file_path": str(fp), "old_string": "line",
                                  "new_string": f"line [{SCARS[0]}]"},
                   "tool_response": {"filePath": str(fp)}}
        self.assertEqual(self.run_hook(payload).returncode, 2)

    def test_an_edit_result_echoing_the_id_does_not_launder_it(self):
        recs = [_use("w1", "Edit", {"file_path": "x.md"}),
                _result("w1", f"The file has been updated. 1\t[{SCARS[0]}]")]
        t = self.transcript(recs)
        self.assertEqual(self.run_hook(self.write(f"[{SCARS[0]}]\n", t)).returncode, 2)

    def test_a_raw_read_of_the_ledger_file_counts(self):
        recs = [_use("r1", "Read", {"file_path": "~/<instance>/canonical/evidence.jsonl"}),
                _result("r1", '1\t{"claim_id": "%s"}' % SCARS[1])]
        t = self.transcript(recs)
        self.assertEqual(self.run_hook(self.write(f"[{SCARS[1]}]\n", t)).returncode, 0)

    def test_a_read_in_the_parent_counts_for_its_subagent(self):
        parent = self.transcript(ledger_show(SCARS[2]), name="S1.jsonl")
        sub = self.transcript([], name="agent-a1.jsonl", where=self.tmp / "S1" / "subagents")
        self.assertTrue(parent.is_file())
        self.assertEqual(self.run_hook(self.write(f"[{SCARS[2]}]\n", sub)).returncode, 0)

    def test_a_read_in_a_subagent_counts_for_the_parent(self):
        parent = self.transcript([], name="S2.jsonl")
        self.transcript(ledger_show(SCARS[0]), name="agent-b.jsonl",
                        where=self.tmp / "S2" / "subagents")
        self.assertEqual(self.run_hook(self.write(f"[{SCARS[0]}]\n", parent)).returncode, 0)


class ScopeModeAndBoundary(Base):
    def test_out_of_scope_path_is_ignored(self):
        t = self.transcript([])
        fp = self.tmp / "inst" / "notes" / "n.md"
        fp.parent.mkdir(parents=True)
        payload = self.write(f"[{SCARS[0]}]\n", t)
        payload["tool_input"]["file_path"] = str(fp)
        self.assertEqual(self.run_hook(payload).returncode, 0)

    def test_canonical_and_prd_trees_are_in_scope(self):
        t = self.transcript([])
        for sub in ("canonical", ".prd-os/prds"):
            with self.subTest(sub=sub):
                fp = self.tmp / "inst" / sub / "f.md"
                fp.parent.mkdir(parents=True, exist_ok=True)
                payload = self.write(f"[{SCARS[0]}]\n", t)
                payload["tool_input"]["file_path"] = str(fp)
                self.assertEqual(self.run_hook(payload).returncode, 2)

    def test_advisory_mode_warns_and_passes(self):
        t = self.transcript([])
        r = self.run_hook(self.write(f"[{SCARS[0]}]\n", t), mode="advisory")
        self.assertEqual(r.returncode, 0)
        self.assertIn(SCARS[0], r.stderr)

    def test_a_mistyped_mode_still_blocks(self):
        t = self.transcript([])
        self.assertEqual(self.run_hook(self.write(f"[{SCARS[0]}]\n", t),
                                       mode="advisroy").returncode, 2)

    def test_no_transcript_passes_with_a_note(self):
        r = self.run_hook(self.write(f"[{SCARS[0]}]\n", self.tmp / "absent.jsonl"))
        self.assertEqual(r.returncode, 0)
        self.assertIn("no session transcript", r.stderr)

    def test_skip_marker(self):
        t = self.transcript([])
        body = f"[{SCARS[0]}]\n<!-- evidence-read-log-skip -->\n"
        self.assertEqual(self.run_hook(self.write(body, t)).returncode, 0)


class TheShowVerb(Base):
    def test_show_prints_only_the_named_row_and_refuses_unknown(self):
        inst = self.tmp / "repo"
        (inst / "q-system" / "canonical").mkdir(parents=True)
        rows = [{"claim_id": i, "claim": "c", "source": "s", "command": "k", "result": "r",
                 "verified_at": "2026-08-05"} for i in SCARS]
        (inst / "q-system" / "canonical" / "evidence.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))
        env = dict(os.environ, KIPI_EVIDENCE_REGISTRY=str(self.tmp / "none.json"))
        run = lambda *ids: subprocess.run(  # noqa: E731
            [sys.executable, str(LEDGER), "--repo", str(inst), "show", *ids],
            capture_output=True, text=True, env=env, timeout=30)
        ok = run(SCARS[1])
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn(SCARS[1], ok.stdout)
        self.assertNotIn(SCARS[0], ok.stdout)
        bad = run("ev-0000000000")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("ev-0000000000", bad.stderr)



def _load_lint():
    import importlib.util
    spec = importlib.util.spec_from_file_location("erll_persist", LINT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PersistedLedgerOutput(unittest.TestCase):
    """PR #433 review: `list` on a 255-row ledger (210 KB) is persisted out of the
    transcript; the id is reachable only by reading the pointer file."""

    PTR = "/s/proj/sess/tool-results/beglog6ri.txt"

    def _recs(self, read_path):
        def use(i, name, inp):
            return {"message": {"content": [
                {"type": "tool_use", "id": i, "name": name, "input": inp}]}}

        def res(i, text):
            return {"message": {"content": [
                {"type": "tool_result", "tool_use_id": i, "content": text}]}}
        return [
            use("a", "Bash", {"command": "python3 evidence_ledger.py list"}),
            res("a", "<persisted-output>Output too large (209.8KB). Full output saved "
                     f"to: {self.PTR}\nPreview: ev-0000000001 ...</persisted-output>"),
            use("b", "Read", {"file_path": read_path}),
            res("b", '{"claim_id": "ev-a9fff8f571", "claim": "x"}'),
        ]

    def test_reading_the_ledger_pointer_counts_as_opening(self):
        mod = _load_lint()
        self.assertIn("ev-a9fff8f571", mod.opened_ids(self._recs(self.PTR)))

    def test_reading_another_tool_results_file_does_not(self):
        mod = _load_lint()
        other = "/s/proj/sess/tool-results/zzzz.txt"
        self.assertNotIn("ev-a9fff8f571", mod.opened_ids(self._recs(other)))


class RoundThree(unittest.TestCase):
    """PR #433 review round 3."""

    def _pair(self, name, inp, text):
        return [{"message": {"content": [
                    {"type": "tool_use", "id": "a", "name": name, "input": inp}]}},
                {"message": {"content": [
                    {"type": "tool_result", "tool_use_id": "a", "content": text}]}}]

    def test_a_failed_show_does_not_open_the_id(self):
        mod = _load_lint()
        recs = self._pair("Bash", {"command": "python3 evidence_ledger.py show ev-00000000ff"},
                          "evidence_ledger show: no such row: ev-00000000ff")
        self.assertNotIn("ev-00000000ff", mod.opened_ids(recs))

    def test_a_list_line_opens_its_id(self):
        mod = _load_lint()
        recs = self._pair("Bash", {"command": "python3 evidence_ledger.py list"},
                          "ev-0123456789  a claim\n    source : s")
        self.assertIn("ev-0123456789", mod.opened_ids(recs))

    def test_a_task_summary_is_not_a_ledger_read(self):
        mod = _load_lint()
        recs = self._pair("Task", {"prompt": "read evidence.jsonl"},
                          '{"claim_id": "ev-0123456789"}')
        self.assertNotIn("ev-0123456789", mod.opened_ids(recs))

    def test_a_write_update_without_original_claims_nothing_new(self):
        mod = _load_lint()
        payload = {"tool_name": "Write", "tool_input": {"content": "cites ev-0123456789"},
                   "tool_response": {"type": "update", "originalFile": None}}
        before, after = mod.before_and_after(payload, None)
        self.assertEqual(mod.introduced(before, after), [])

if __name__ == "__main__":
    unittest.main(verbosity=1)
