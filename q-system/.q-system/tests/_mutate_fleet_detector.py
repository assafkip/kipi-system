#!/usr/bin/env python3
"""Mutation harness: run the finding-3 cases against the PRE-FIX detector.

Not a test. A one-shot that reverses the three things the fix changed and runs
the new cases, so "observed RED" is a command somebody else can re-run rather
than a claim in a commit message. Delete-safe; nothing imports it.

  python3 q-system/.q-system/tests/_mutate_fleet_detector.py
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_fleet_api_credit as t                      # noqa: E402

keymod = t.keymod
_real_run_once = keymod._run_once

# 1. the detector ignored the envelope entirely
_real_reads = keymod.reads_as_exhausted
keymod.reads_as_exhausted = lambda text, envelope=None: _real_reads(text, None)

# 2. a turn only failed when the PROCESS failed
keymod.declared_error = lambda envelope: False


# 3. only stdout was scanned
def _stdout_only(slot, argv, actor):
    rc, text, cost, raw, env = _real_run_once(slot, argv, actor)
    if env is not None:
        import json
        raw = json.dumps(env)
    return rc, text, cost, raw, env


keymod._run_once = _stdout_only

loader = unittest.TestLoader()
suite = unittest.TestSuite([
    loader.loadTestsFromTestCase(t.TestRefusalShapesTheProseMissed),
    loader.loadTestsFromTestCase(t.TestTheDetectorDirectly),
])
result = unittest.TextTestRunner(verbosity=2).run(suite)
print("\nMUTANT: %d of %d cases red"
      % (len(result.failures) + len(result.errors), result.testsRun))
sys.exit(0 if (result.failures or result.errors) else 1)
