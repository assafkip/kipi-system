#!/usr/bin/env python3
"""dc-23: the command doc matches the code.

WHY. The command was the only place the chain was described, and it drifted: it told the author to
do steps the gate never checked, and named scripts by paths that had moved. The three RCAs all quote
it. This test derives what the doc must name FROM the gate (its producers, its check registry, its
chain files and dirs) instead of restating a list here, and refuses a step that no executable holds.
"""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "q-system" / ".q-system" / "scripts"
DOC = ROOT / "plugins" / "kipi-core" / "commands" / "design-chain.md"


def gate():
    spec = importlib.util.spec_from_file_location("dc23_gate", SCRIPTS / "design-chain-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CommandDoc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = gate()
        cls.text = DOC.read_text()
        # fenced blocks are examples, not the doc's own words: a stage name surviving in the bash
        # fence at the top let a whole step be deleted and still pass (review of 24d907c5)
        cls.prose = re.sub(r"(?ms)^```.*?^```", "", cls.text)
        cls.steps = re.split(r"(?m)^## ", cls.prose)[1:]

    def test_every_script_the_doc_names_exists(self):
        named = set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:py|sh))`", self.text))
        self.assertTrue(named, "the doc names no script")
        missing = sorted(n for n in named
                         if not (SCRIPTS / Path(n).name).is_file() and not (ROOT / n).is_file())
        self.assertEqual(missing, [], "the doc names a script that is not in the tree")

    def test_every_stage_the_gate_records_is_in_the_doc(self):
        stages = set(self.gate.STAGE_PRODUCERS) | {f"check:{n}" for n in self.gate.CHECKS}
        self.assertTrue(stages)
        # as its own token: "impeccable" inside design-impeccable-check.py is not the stage
        self.assertEqual(sorted(s for s in stages if f"`{s}`" not in self.prose), [],
                         "the gate records a stage the doc never names")

    def test_the_step_that_names_a_stage_names_its_producer(self):
        # a step may otherwise name a real script belonging to another step (review of 24d907c5)
        for stage, producer in self.gate.STAGE_PRODUCERS.items():
            holder = [s for s in self.steps if f"`{stage}`" in s]
            self.assertTrue(holder, f"no step names the {stage} stage")
            self.assertTrue(any(producer in s for s in holder),
                            f"the step naming the {stage} stage does not name {producer}")

    def test_every_chain_file_and_dir_is_in_the_doc(self):
        want = set(self.gate.CHAIN_FILES) | {f"{d}/" for d in self.gate.CHAIN_DIRS} | {self.gate.CRAFT_MANIFEST}
        self.assertEqual(sorted(w for w in want if w not in self.text), [],
                         "the chain requires a file the doc never names")

    def test_every_step_names_the_executable_that_holds_it(self):
        # a step whose only holder is prose is the shape all three RCAs found: the doc asked for
        # work the gate never checked. Each step names a script, a gate subcommand, or a check
        # function the gate really has.
        # a script (with or without arguments) or a gate function, inside backticks
        holders = re.compile(r"`[A-Za-z0-9_./-]+\.(?:py|sh)(?: [^`]*)?`|`[a-z_]+\(\)`")
        loose = [s.splitlines()[0] for s in self.steps
                 if s.startswith("Step ") and not holders.search(s)]
        self.assertEqual(loose, [], "a step in the doc has no executable behind it")

    def test_the_gate_functions_the_doc_names_exist(self):
        named = sorted(set(re.findall(r"`([a-z_]+)\(\)`", self.text)))
        self.assertTrue(named, "the doc names no gate function")
        for fn in named:
            self.assertTrue(hasattr(self.gate, fn), f"the doc names {fn}(), which the gate does not have")


if __name__ == "__main__":
    unittest.main()
