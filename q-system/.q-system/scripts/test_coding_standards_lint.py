#!/usr/bin/env python3
"""test_coding_standards_lint: the deterministic half of `.claude/rules/coding-standards.md`.

WHY (ASK-133): the rule claimed ENFORCED and named no executable, so every line
in it was prompt-only. Four of its lines are pure regex work -- shell strictness,
JSON indent width, `var` in JS, file naming -- and nothing checked any of them.

Isolation: every case writes to a tempdir. No test touches a real repo path, and
no test invokes the hook against a live file.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_LINT = Path(__file__).resolve().parent / "coding-standards-lint.py"
_SPEC = importlib.util.spec_from_file_location("coding_standards_lint", _LINT)
lint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lint)


def check(name: str, text: str, *, subdir: str = "") -> list[dict]:
    """Write `text` to a tempfile named `name` and return its violations."""
    root = Path(tempfile.mkdtemp())
    target = root / subdir / name if subdir else root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return lint.lint_file(str(target))


def rules(violations) -> set:
    return {v["rule"] for v in violations}


class ShellStrictMode(unittest.TestCase):
    def test_shell_without_set_euo_pipefail_is_flagged(self):
        found = check("deploy.sh", "#!/usr/bin/env bash\necho hi\n")
        self.assertIn("shell-strict", rules(found))

    def test_shell_with_the_trio_is_clean(self):
        found = check("deploy.sh", "#!/usr/bin/env bash\nset -euo pipefail\necho hi\n")
        self.assertEqual(found, [])

    def test_split_set_lines_are_accepted(self):
        """`set -e` + `set -u` + `set -o pipefail` is the same guarantee."""
        found = check(
            "deploy.sh",
            "#!/bin/bash\nset -e\nset -u\nset -o pipefail\necho hi\n",
        )
        self.assertEqual(found, [])

    def test_partial_strictness_is_still_flagged(self):
        found = check("deploy.sh", "#!/bin/bash\nset -e\necho hi\n")
        self.assertIn("shell-strict", rules(found))

    def test_sourced_fragment_without_a_shebang_is_exempt(self):
        """A sourced fragment must not set -e on behalf of its caller."""
        found = check("snippet.sh", "alias k=kubectl\n")
        self.assertEqual(found, [])


class JsonIndent(unittest.TestCase):
    FOUR = '{\n    "a": {\n        "b": 1\n    }\n}\n'
    TWO = '{\n  "a": {\n    "b": 1\n  }\n}\n'

    def test_four_space_json_is_flagged(self):
        found = check("config.json", self.FOUR)
        self.assertIn("json-indent", rules(found))

    def test_two_space_json_is_clean(self):
        self.assertEqual(check("config.json", self.TWO), [])

    def test_tab_indented_json_is_flagged(self):
        found = check("config.json", '{\n\t"a": 1\n}\n')
        self.assertIn("json-indent", rules(found))

    def test_minified_json_is_clean(self):
        self.assertEqual(check("config.json", '{"a":{"b":1}}\n'), [])

    def test_compact_one_record_per_line_array_is_clean(self):
        """Documented coverage limit: under-indent is out of scope.

        `skill-evals/*.json` is a real, deliberate style in this repo (one JSON
        record per line at one space). Flagging it would be noise, so the check
        only fires at 3+ spaces or a tab.
        """
        text = '[\n {"prompt":"a","should_trigger":true},\n {"prompt":"b"}\n]\n'
        self.assertEqual(check("audhd.json", text), [])


class JsNoVar(unittest.TestCase):
    def test_var_declaration_is_flagged(self):
        found = check("app.js", "var x = 1;\n")
        self.assertIn("js-no-var", rules(found))

    def test_var_in_a_for_header_is_flagged(self):
        found = check("app.js", "for (var i = 0; i < 3; i++) {}\n")
        self.assertIn("js-no-var", rules(found))

    def test_const_and_let_are_clean(self):
        self.assertEqual(check("app.js", "const x = 1;\nlet y = 2;\n"), [])

    def test_var_inside_a_line_comment_is_ignored(self):
        self.assertEqual(check("app.js", "// var x = 1;\nconst x = 1;\n"), [])

    def test_var_inside_a_string_is_ignored(self):
        self.assertEqual(check("app.js", 'const s = "var x = 1";\n'), [])

    def test_a_word_ending_in_var_is_not_a_declaration(self):
        self.assertEqual(check("app.js", "const myvar = 1;\nconst cssvar = 2;\n"), [])


class FileNaming(unittest.TestCase):
    def test_camelcase_script_is_flagged(self):
        found = check("buildSchedule.py", "print(1)\n")
        self.assertIn("naming", rules(found))

    def test_kebab_script_is_clean(self):
        self.assertEqual(check("build-schedule.py", "print(1)\n"), [])

    def test_snake_script_is_clean(self):
        """85 kebab vs 35 snake among this repo's scripts: both are the convention."""
        self.assertEqual(check("build_schedule.py", "print(1)\n"), [])

    def test_dunder_init_is_clean(self):
        self.assertEqual(check("__init__.py", "\n"), [])

    def test_uppercase_output_file_is_flagged(self):
        found = check(
            "FABLE_ANALYSIS.md", "# notes\n", subdir="q-system/output/fable"
        )
        self.assertIn("naming", rules(found))

    def test_snake_case_output_file_is_flagged(self):
        found = check("my_report.md", "# notes\n", subdir="q-system/output")
        self.assertIn("naming", rules(found))

    def test_kebab_output_file_is_clean(self):
        self.assertEqual(
            check("my-report-2026-07-31.md", "# notes\n", subdir="q-system/output"), []
        )

    def test_a_script_under_output_keeps_script_naming(self):
        """A script is a script wherever it lives; snake there is not a violation."""
        self.assertEqual(
            check("build_docx.py", "print(1)\n", subdir="q-system/output/report"), []
        )

    def test_dotfiles_are_exempt(self):
        self.assertEqual(check(".gitkeep", "", subdir="q-system/output"), [])


class Scope(unittest.TestCase):
    def test_markdown_is_out_of_scope(self):
        self.assertEqual(check("notes.md", "var x = 1;\n"), [])

    def test_jsonl_is_out_of_scope(self):
        """JSONL is line-delimited by definition; indent rules do not apply."""
        self.assertEqual(check("ledger.jsonl", '{"a":1}\n{"a":2}\n'), [])

    def test_skip_marker_disables_the_file(self):
        text = "#!/bin/bash\n# coding-standards-lint-skip\necho hi\n"
        self.assertEqual(check("deploy.sh", text), [])


class HookContract(unittest.TestCase):
    """The wire, not just the unit: stdin payload in, exit 2 out."""

    def _run(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_LINT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def _tmp(self, name: str, text: str) -> str:
        target = Path(tempfile.mkdtemp()) / name
        target.write_text(text, encoding="utf-8")
        return str(target)

    def test_violating_write_exits_2(self):
        path = self._tmp("deploy.sh", "#!/bin/bash\necho hi\n")
        res = self._run({"tool_name": "Write", "tool_input": {"file_path": path}})
        self.assertEqual(res.returncode, 2)
        self.assertIn("shell-strict", res.stderr)

    def test_clean_write_exits_0(self):
        path = self._tmp("deploy.sh", "#!/bin/bash\nset -euo pipefail\necho hi\n")
        res = self._run({"tool_name": "Write", "tool_input": {"file_path": path}})
        self.assertEqual(res.returncode, 0)

    def test_out_of_scope_extension_exits_0(self):
        path = self._tmp("notes.md", "var x = 1;\n")
        res = self._run({"tool_name": "Write", "tool_input": {"file_path": path}})
        self.assertEqual(res.returncode, 0)

    def test_non_edit_tool_exits_0(self):
        path = self._tmp("deploy.sh", "#!/bin/bash\necho hi\n")
        res = self._run({"tool_name": "Read", "tool_input": {"file_path": path}})
        self.assertEqual(res.returncode, 0)

    def test_garbage_stdin_exits_0(self):
        res = subprocess.run(
            [sys.executable, str(_LINT)],
            input="not json",
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)

    def test_missing_file_exits_0(self):
        res = self._run(
            {"tool_name": "Write", "tool_input": {"file_path": "/nope/gone.sh"}}
        )
        self.assertEqual(res.returncode, 0)

    def test_cli_mode_exits_2_on_a_violation(self):
        path = self._tmp("deploy.sh", "#!/bin/bash\necho hi\n")
        res = subprocess.run(
            [sys.executable, str(_LINT), path], capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 2)


class Wiring(unittest.TestCase):
    """The switch, not just the script. Both settings files, or it ships dead."""

    REPO = Path(__file__).resolve().parents[3]

    def _commands(self, path: Path) -> str:
        return json.dumps(json.loads(path.read_text(encoding="utf-8")))

    def test_wired_in_settings_json(self):
        self.assertIn(
            "coding-standards-lint.py", self._commands(self.REPO / ".claude/settings.json")
        )

    def test_wired_in_settings_template(self):
        self.assertIn(
            "coding-standards-lint.py",
            self._commands(self.REPO / "settings-template.json"),
        )

    def test_registered_in_the_capability_manifest(self):
        manifest = json.loads(
            (self.REPO / "q-system/.q-system/capability-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        paths = {entry["path"] for entry in manifest["expected_tests"]}
        self.assertIn(
            "q-system/.q-system/scripts/test_coding_standards_lint.py", paths
        )

    def test_the_rule_names_its_executable(self):
        rule = (self.REPO / ".claude/rules/coding-standards.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("coding-standards-lint.py", rule)


if __name__ == "__main__":
    unittest.main(verbosity=2)
