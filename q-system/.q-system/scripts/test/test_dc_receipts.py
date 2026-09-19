#!/usr/bin/env python3
"""dc-10: a receipt says what ran, and the passive gate believes a receipt only when it can check it.

WHY. The RCA (rca-design-chain-trusts-its-own-account-2026-09-18.md, round B): a hand-typed
receipts.json read COMPLETE, because the passive gate compared one page sha and nothing else.
And ASK-1808 (final review, finding-7): seal wrote a round digest that nothing ever read, so a
stylesheet swapped AFTER the seal left the round COMPLETE.

Every test here drives the REAL gate at its tracked path (verify contract 2, ASK-1810). The
grandfather tests also run a copy committed INTO a throwaway repo, because the cutover is the
commit date of the gate as committed in the round's own repo, which is what an instance has
after the fleet sync. Temp directories only; real producers and real chromium.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_dc_seal_snapshot as snap  # noqa: E402  (the sealable-round fixture, shared)

SCRIPTS = HERE.parent
REAL_GATE = SCRIPTS / "design-chain-gate.py"
PRODUCERS = ("design-standard-check.py", "design-gap-check.py")


def git(repo, *args, date=None):
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        env.pop(k, None)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Base(snap.Base):
    def setUp(self):
        super().setUp()
        self.css.write_text(snap.PASSING_CSS)
        self.repo = self.tmp
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t.co")
        git(self.repo, "config", "user.name", "t")

    def commit(self, msg, date=None):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", msg, "--allow-empty", date=date)

    def status(self, gate=REAL_GATE):
        r = subprocess.run([sys.executable, str(gate), "status", str(self.round)], capture_output=True,
                           text=True, env=self.env())
        return r.returncode, r.stdout + r.stderr

    def receipt(self):
        return json.loads((self.round / "receipts.json").read_text())

    def seal_ok(self, gate=REAL_GATE):
        r = subprocess.run([sys.executable, str(gate), "seal", str(self.round)], capture_output=True,
                           text=True, env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def gate_in_repo(self, date, tweak=""):
        """A copy of the gate (and its producers) committed into the round's own repo, the way
        the fleet sync puts it into an instance. `tweak` changes its bytes: an upgrade."""
        d = self.repo / "q-system" / ".q-system" / "scripts"
        d.mkdir(parents=True, exist_ok=True)
        (d / REAL_GATE.name).write_text(REAL_GATE.read_text() + tweak)
        for p in PRODUCERS:
            shutil.copy(SCRIPTS / p, d / p)
        self.commit(f"sync the gate {tweak.strip()}", date=date)
        return d / REAL_GATE.name


class TheReceiptSaysWhatRan(Base):
    def test_a_seal_records_the_gate_and_each_producer_that_ran(self):
        self.seal_ok()
        rec = self.receipt()
        import hashlib
        gate = rec["__gate__"]
        self.assertEqual(Path(gate["path"]).name, REAL_GATE.name)
        self.assertEqual(gate["sha256"], hashlib.sha256(REAL_GATE.read_bytes()).hexdigest())
        stages = rec[self.page.name]["stages"]
        std = [s for s in stages if s["stage"] == "standard"]
        self.assertEqual(len(std), 1, stages)
        self.assertEqual(std[0]["exit"], 0)
        self.assertEqual(std[0]["sha256"], hashlib.sha256((SCRIPTS / PRODUCERS[0]).read_bytes()).hexdigest())

    def test_no_stage_is_recorded_for_a_producer_this_gate_does_not_have(self):
        self.seal_ok()
        names = {s["stage"] for s in self.receipt()[self.page.name]["stages"]}
        self.assertEqual(names & {"impeccable", "readers", "checks", "engines", "floor", "vision"}, set())
        self.assertNotIn("gap", names, "the gap producer did not run for this round (not required)")


class AnEditAfterTheSealOpensTheRound(Base):
    CHAIN_RECORDS = ("brief.md", "craft-manifest.json", "directions.md", "critique.md", "proof.md",
                     "sources.json", "gate/reader-runs.jsonl", "shared.css")

    def test_every_chain_record_and_asset_edited_after_the_seal_opens_the_round(self):
        self.seal_ok()
        rc, out = self.status()
        self.assertEqual(rc, 0, out)
        for rel in self.CHAIN_RECORDS:
            f = self.round / rel
            before = f.read_bytes() if f.is_file() else None
            with f.open("a") as fh:
                fh.write("\n")
            rc, out = self.status()
            self.assertEqual(rc, 2, f"{rel} changed after the seal and the round still read COMPLETE\n{out}")
            self.assertIn("changed after", out)
            if before is None:
                f.unlink()
            else:
                f.write_bytes(before)
            rc, out = self.status()
            self.assertEqual(rc, 0, f"restoring {rel} did not bring the round back\n{out}")

    def test_what_seal_itself_writes_does_not_open_it(self):
        self.seal_ok()
        std = self.round / "standard.json"
        std.write_text(std.read_text() + "\n")
        rc, out = self.status()
        self.assertEqual(rc, 0, out)


class ACorrectionIsNotAnEdit(Base):
    def test_correcting_one_page_leaves_another_sealed_page_complete(self):
        other = self.round / "Other-laptop.html"
        other.write_text(snap.PAGE.replace("bill", "count"))
        self.seal_ok()
        self.commit("sealed")
        self.page.write_text(snap.PAGE.replace("Somebody retypes it every week.",
                                               "Somebody retypes it every single week."))
        r = subprocess.run([sys.executable, str(REAL_GATE), "correct", str(self.page), "--reason", "wording"],
                           capture_output=True, text=True, env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rc, out = self.status()
        self.assertEqual(rc, 0, out)


class ABareReceiptIsBelievedOnlyFromGitHistory(Base):
    def bare_receipt(self):
        import hashlib
        (self.round / "receipts.json").write_text(json.dumps(
            {self.page.name: {"sha256": hashlib.sha256(self.page.read_bytes()).hexdigest(),
                              "sealed": "2026-09-01T00:00:00"}}))

    def test_a_hand_typed_receipt_reads_open(self):
        # the RCA's round B: typed, never committed
        self.bare_receipt()
        rc, out = self.status()
        self.assertEqual(rc, 2, out)
        self.assertIn("receipt", out)

    def test_a_receipt_committed_before_the_gate_arrived_is_history(self):
        self.bare_receipt()
        self.commit("an old seal", date="2026-09-01T00:00:00")
        gate = self.gate_in_repo("2026-09-10T00:00:00")
        rc, out = self.status(gate)
        self.assertEqual(rc, 0, out)

    def test_a_bare_receipt_committed_after_the_gate_arrived_is_not(self):
        gate = self.gate_in_repo("2026-09-10T00:00:00")
        self.bare_receipt()
        self.commit("a bare receipt, after the stages-aware gate", date="2026-09-12T00:00:00")
        rc, out = self.status(gate)
        self.assertEqual(rc, 2, out)

    def test_a_receipt_edited_since_its_commit_is_not(self):
        self.bare_receipt()
        self.commit("an old seal", date="2026-09-01T00:00:00")
        gate = self.gate_in_repo("2026-09-10T00:00:00")
        rec = json.loads((self.round / "receipts.json").read_text())
        rec[self.page.name]["sealed"] = "2026-09-02T00:00:00"
        (self.round / "receipts.json").write_text(json.dumps(rec))
        rc, out = self.status(gate)
        self.assertEqual(rc, 2, out)

    def test_a_repo_with_no_history_for_the_gate_fails_closed(self):
        # the real gate lives outside this repo: nothing dates the cutover, so nothing is history
        self.bare_receipt()
        self.commit("an old seal", date="2026-09-01T00:00:00")
        rc, out = self.status()
        self.assertEqual(rc, 2, out)


class AnUpgradeKeepsHistory(Base):
    def test_an_upgraded_gate_keeps_every_previously_sealed_round_complete(self):
        v1 = self.gate_in_repo("2026-09-10T00:00:00")
        self.seal_ok(v1)
        self.commit("sealed with v1", date="2026-09-11T00:00:00")
        v2 = self.gate_in_repo("2026-09-20T00:00:00", tweak="\n# v2\n")
        rc, out = self.status(v2)
        self.assertEqual(rc, 0, f"a gate upgrade opened a round sealed under the old gate\n{out}")

    def test_a_copied_gate_that_is_gone_is_not_believed(self):
        bin_ = Path(tempfile.mkdtemp(prefix="dc10-copy-"))
        try:
            shutil.copy(REAL_GATE, bin_ / REAL_GATE.name)
            (bin_ / REAL_GATE.name).write_text(REAL_GATE.read_text() + "\n# a copy\n")
            for p in PRODUCERS:
                shutil.copy(SCRIPTS / p, bin_ / p)
            self.seal_ok(bin_ / REAL_GATE.name)
        finally:
            shutil.rmtree(bin_, ignore_errors=True)
        rc, out = self.status()
        self.assertEqual(rc, 2, out)
        self.assertIn("receipt", out)


class AProducerThatChangedIsNotBelieved(Base):
    def test_a_producer_changed_after_the_seal_and_never_committed_is_not_believed(self):
        # the gate here is believed (same bytes at the same path), so only the stage check can see it
        d = self.repo / "q-system" / ".q-system" / "scripts"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL_GATE, d / REAL_GATE.name)
        for p in PRODUCERS:
            shutil.copy(SCRIPTS / p, d / p)
        self.seal_ok(d / REAL_GATE.name)
        rc, out = self.status(d / REAL_GATE.name)
        self.assertEqual(rc, 0, out)
        (d / PRODUCERS[0]).write_text((SCRIPTS / PRODUCERS[0]).read_text() + "\n# changed\n")
        rc, out = self.status(d / REAL_GATE.name)
        self.assertEqual(rc, 2, out)
        self.assertIn("standard producer", out)

class AGateThatChangedIsNotBelieved(Base):
    def test_a_gate_changed_after_the_seal_and_never_committed_is_not_believed(self):
        # the producers stay byte-identical, so only the gate check can see it (mutant D4 survived
        # the first version: the copied-gate test also removed the producers, and the stage check
        # refused first)
        d = self.repo / "q-system" / ".q-system" / "scripts"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL_GATE, d / REAL_GATE.name)
        for p in PRODUCERS:
            shutil.copy(SCRIPTS / p, d / p)
        self.seal_ok(d / REAL_GATE.name)
        (d / REAL_GATE.name).write_text(REAL_GATE.read_text() + "\n# changed after the seal\n")
        rc, out = self.status(d / REAL_GATE.name)
        self.assertEqual(rc, 2, out)
        self.assertIn("names a gate", out)

class ThePassiveCheckIsCached(Base):
    def test_repeated_checks_recompute_once_and_again_after_a_change(self):
        self.seal_ok()
        cache = Path(self.env()["DESIGN_CHAIN_STATE"]) / "round-cache.json"
        for _ in range(3):
            rc, out = self.status()
            self.assertEqual(rc, 0, out)
        entry = json.loads(cache.read_text())[str(self.round.resolve())]
        self.assertEqual(entry["computed"], 1, "three checks of an unchanged round recomputed more than once")
        (self.round / "notes.md").write_text("x")
        self.status()
        entry = json.loads(cache.read_text())[str(self.round.resolve())]
        self.assertEqual(entry["computed"], 2, "a changed round was not recomputed")


if __name__ == "__main__":
    unittest.main()
