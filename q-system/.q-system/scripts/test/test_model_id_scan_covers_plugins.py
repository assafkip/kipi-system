#!/usr/bin/env python3
"""Pins ASK-1904: Gate 1.1b only reads .claude/agents/*.md, so a plugin script
that hardcodes a model-ID literal (plugins/kipi-core/voiceloop/critic.py:
115-116, claude-sonnet-5 / claude-haiku-4-5) is invisible to it. A retired or
unknown ID in plugins/ ships fleet-wide green.

`plugin_model_id_violations()` closes that hole: it scans plugins/ (dir-
parameterized, verify-against-a-copy per fable-discipline -- never the live
tree in a test) for `claude-<tier>-<version>`-shaped literals and reports any
that fall outside the MODEL_TIERS allowlist.

Every positive case here is paired with a negative one, so the check can be
seen to distinguish compliant from non-compliant rather than just firing on
anything:
  - a current, allowed ID           -> no violation
  - a retired/unknown ID            -> a violation naming the file and the id
  - the retired ID inside test/     -> excluded on purpose (own-suite trap,
                                        same exclusion capability-gate.py uses
                                        for wiring surfaces)
  - a non-scanned extension (.png)  -> excluded on purpose
"""
from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "kipi_validate_separation_modelscan", REPO_ROOT / "validate-separation.py"
    )
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load validate-separation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VS = load_validator()


class PluginModelIdScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="plugin-model-scan-"))
        self.plugins_dir = self.tmp / "plugins"
        self.plugins_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel_path, text):
        p = self.plugins_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_current_allowed_ids_produce_no_violation(self):
        self._write(
            "kipi-core/voiceloop/critic.py",
            'MODEL_QUALITY = "claude-sonnet-5"\n'
            'MODEL_STYLE = "claude-haiku-4-5"\n',
        )
        violations = VS.plugin_model_id_violations(str(self.plugins_dir))
        self.assertEqual(violations, [])

    def test_retired_id_is_flagged_by_file_and_id(self):
        self._write(
            "kipi-core/voiceloop/critic.py",
            'MODEL_QUALITY = "claude-sonnet-4-6"\n',  # retired, not in MODEL_TIERS
        )
        violations = VS.plugin_model_id_violations(str(self.plugins_dir))
        self.assertEqual(len(violations), 1, violations)
        self.assertIn("critic.py", violations[0])
        self.assertIn("claude-sonnet-4-6", violations[0])

    def test_restoring_the_id_clears_the_violation(self):
        target = self._write(
            "kipi-core/voiceloop/critic.py",
            'MODEL_QUALITY = "claude-sonnet-4-6"\n',
        )
        self.assertTrue(VS.plugin_model_id_violations(str(self.plugins_dir)))
        target.write_text('MODEL_QUALITY = "claude-sonnet-5"\n')
        self.assertEqual(VS.plugin_model_id_violations(str(self.plugins_dir)), [])

    def test_retired_id_inside_a_test_directory_is_excluded(self):
        self._write(
            "kipi-core/voiceloop/test/fixture_critic.py",
            'MODEL_QUALITY = "claude-sonnet-4-6"\n',
        )
        violations = VS.plugin_model_id_violations(str(self.plugins_dir))
        self.assertEqual(violations, [], "test/ fixtures are excluded, same as capability-gate.py's wiring scan")

    def test_non_scanned_extension_is_excluded(self):
        self._write("kipi-core/assets/logo.png", "claude-sonnet-4-6")
        violations = VS.plugin_model_id_violations(str(self.plugins_dir))
        self.assertEqual(violations, [])

    def test_missing_plugins_dir_returns_no_violations(self):
        self.assertEqual(VS.plugin_model_id_violations(str(self.tmp / "does-not-exist")), [])


if __name__ == "__main__":
    unittest.main()
