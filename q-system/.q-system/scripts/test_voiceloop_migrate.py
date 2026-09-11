#!/usr/bin/env python3
"""Tests for kipi-update-voiceloop-migrate.py and its call site (sp-8d55455a).

Two halves, and the second is the one that is easy to skip: the engine can be
perfectly green while nothing ever CALLS it. `test_wiring_*` mutation-checks the
call site in kipi-update.sh -- delete it and those tests go red.
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
MIGRATE = os.path.join(REPO, "kipi-update-voiceloop-migrate.py")
UPDATER = os.path.join(REPO, "kipi-update.sh")

_spec = importlib.util.spec_from_file_location("voiceloop_migrate", MIGRATE)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

OLD = "voice" + "kit"          # never a literal: this file is not exempt from
NEW = "voice" + "loop"         # its own subject when the tree is walked.


def build_instance(root, *, package=OLD, extra=()):
    """A minimal instance with the shape that matters."""
    pkg = os.path.join(root, "plugins", "kipi-core", package)
    os.makedirs(os.path.join(pkg, "tests"), exist_ok=True)
    open(os.path.join(pkg, "__init__.py"), "w").write("VERSION = 1\n")
    os.makedirs(os.path.join(root, "pipeline"), exist_ok=True)
    open(os.path.join(root, "pipeline", "voice.py"), "w").write(
        "import sys, os\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', "
        "'plugins', 'kipi-core'))\n"
        f"from {package} import __init__ as _  # noqa\n")
    for rel, body in extra:
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)
    return root


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_rewrites_imports_and_moves_the_package(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        out = mig.apply(r, commit=False)
        self.assertTrue(out["moved"])
        self.assertTrue(out["verified"], out["errors"])
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", NEW)))
        self.assertFalse(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        self.assertIn(NEW, open(os.path.join(r, "pipeline/voice.py")).read())
        self.assertNotIn(OLD, open(os.path.join(r, "pipeline/voice.py")).read())

    def test_second_run_is_a_clean_noop(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        mig.apply(r, commit=False)
        again = mig.apply(r, commit=False)
        self.assertFalse(again["moved"])
        self.assertEqual(again["rewritten"], [])
        self.assertEqual(again["renamed"], [])
        self.assertFalse(mig.plan(r)["needs_work"])

    def test_already_migrated_instance_is_untouched(self):
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW)
        self.assertFalse(mig.plan(r)["needs_work"])
        out = mig.apply(r, commit=False)
        self.assertFalse(out["moved"])
        self.assertEqual(out["rewritten"], [])

    def _skeleton_and_instance(self, *, package=NEW, instance_carries_shipped=True):
        """A fake skeleton that ships the engine init with the rename comment
        plus one q-system script, and an instance carrying the same two files
        (unless it is still on the old package: then the new package must not
        exist yet or the move is a `both_present` refusal), an instance-only
        script INSIDE q-system/, and its own pipeline import."""
        why = ('"""engine.\n\nwhy the name changed: this package was called `' + OLD
               + '` here and the\nexporter renamed it on the way out.\n"""\nVERSION = 2\n')
        tool = "import " + OLD + ".core as core  # the skeleton's own helper, code not prose\n"
        shipped = [("plugins/kipi-core/" + NEW + "/__init__.py", why),
                   ("q-system/.q-system/scripts/tool.py", tool)]
        sk = os.path.join(self.tmp, "skeleton")
        for rel, body in shipped:
            p = os.path.join(sk, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(body)
        carried = shipped if instance_carries_shipped else []
        r = build_instance(os.path.join(self.tmp, "i"), package=package, extra=carried + [
            ("q-system/.q-system/scripts/mine.py", "from " + OLD + " import x\n"),
            ("q-consult/pipeline/voice.py", "from " + OLD + " import x\n"),
        ])
        return sk, r

    def test_a_path_the_skeleton_ships_is_the_syncs_not_the_migrations(self):
        """2026-09-06: the engine's own __init__.py documents the rename in a
        why-comment that names the old package on purpose. Rewriting it made
        every sync commit churn on 22 instances and made the one instance whose
        pre-commit compares the engine to a public mirror refuse the commit, so
        the rsync never started (sp-b0389e48)."""
        sk, r = self._skeleton_and_instance()
        p = mig.plan(r, skeleton=sk)
        self.assertEqual(p["rewrite"], ["q-consult/pipeline/voice.py",
                                        "q-system/.q-system/scripts/mine.py"])
        self.assertEqual(p["delivered_by_sync"], ["plugins/kipi-core/" + NEW + "/__init__.py",
                                                    "q-system/.q-system/scripts/tool.py"])
        out = mig.apply(r, commit=False, skeleton=sk)
        self.assertTrue(out["verified"], out["errors"])
        self.assertEqual(sorted(out["rewritten"]), p["rewrite"])
        init = open(os.path.join(r, "plugins/kipi-core", NEW, "__init__.py")).read()
        self.assertIn("called `" + OLD + "` here", init)
        self.assertIn("import " + OLD + ".core", open(os.path.join(r, "q-system/.q-system/scripts/tool.py")).read())
        self.assertNotIn(OLD, open(os.path.join(r, "q-system/.q-system/scripts/mine.py")).read())
        self.assertNotIn(OLD, open(os.path.join(r, "q-consult/pipeline/voice.py")).read())
        self.assertFalse(mig.plan(r, skeleton=sk)["needs_work"])

    def test_without_the_skeleton_shipped_code_is_rewritten_and_prose_still_survives(self):
        """Negative self-test for the skeleton rule: an empty skeleton ships
        nothing, so the skeleton's CODE helper is rewritten like any instance
        file. The docstring in the init survives on the prose rule alone, which
        the next test takes away in turn."""
        _, r = self._skeleton_and_instance()
        empty = os.path.join(self.tmp, "empty-skeleton")
        os.makedirs(empty)
        p = mig.plan(r, skeleton=empty)
        self.assertEqual(p["delivered_by_sync"], [])
        self.assertIn("q-system/.q-system/scripts/tool.py", p["rewrite"])
        self.assertNotIn("plugins/kipi-core/" + NEW + "/__init__.py", p["rewrite"])
        mig.apply(r, commit=False, skeleton=empty)
        self.assertNotIn(OLD, open(os.path.join(r, "q-system/.q-system/scripts/tool.py")).read())
        init = open(os.path.join(r, "plugins/kipi-core", NEW, "__init__.py")).read()
        self.assertIn("called `" + OLD + "` here", init)

    def test_without_the_prose_rule_the_docstring_is_rewritten(self):
        """Negative self-test for the prose rule: with span detection taken
        away, the same docstring IS rewritten into an identity rename. The
        classifier is what holds the line, not the shape of the text."""
        _, r = self._skeleton_and_instance()
        empty = os.path.join(self.tmp, "empty-skeleton")
        os.makedirs(empty)
        real = mig._prose_spans
        mig._prose_spans = lambda text, lines: []
        try:
            p = mig.plan(r, skeleton=empty)
            self.assertIn("plugins/kipi-core/" + NEW + "/__init__.py", p["rewrite"])
            mig.apply(r, commit=False, skeleton=empty)
        finally:
            mig._prose_spans = real
        init = open(os.path.join(r, "plugins/kipi-core", NEW, "__init__.py")).read()
        self.assertNotIn(OLD, init)
        self.assertIn("called `" + NEW + "` here", init)

    def test_prose_in_an_instance_file_survives_and_its_code_migrates(self):
        """The exporter shape from the aborted 2026-09-06 run: a docstring and
        two # comments that document the rename, next to an import and a path
        literal that must migrate. Exact text, both directions."""
        before = ('"""Exporter.\n\nThe pair (' + OLD + ' -> ' + NEW + ') lived here until the rename.\n"""\n'
                  'import ' + OLD + '.core  # ' + OLD + ' was the name\n'
                  'RENAMES = [("' + OLD + '/validate.py", "' + NEW + '/validate.py")]\n'
                  '# test_' + OLD + '.py went with it\n')
        after = ('"""Exporter.\n\nThe pair (' + OLD + ' -> ' + NEW + ') lived here until the rename.\n"""\n'
                 'import ' + NEW + '.core  # ' + OLD + ' was the name\n'
                 'RENAMES = [("' + NEW + '/validate.py", "' + NEW + '/validate.py")]\n'
                 '# test_' + OLD + '.py went with it\n')
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW, extra=[
            ("automation/export.py", before),
        ])
        out = mig.apply(r, commit=False, skeleton=os.path.join(self.tmp, "nothing-shipped"))
        self.assertTrue(out["verified"], out["errors"])
        self.assertEqual(open(os.path.join(r, "automation/export.py")).read(), after)
        self.assertFalse(mig.plan(r, skeleton=os.path.join(self.tmp, "nothing-shipped"))["needs_work"])

    def test_a_docstring_only_file_is_not_work(self):
        """A file whose only mention is prose is not a rewrite candidate, so an
        already-migrated instance reports needs_work=False and never commits."""
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW, extra=[
            ("automation/notes.py", '"""' + OLD + ' was the old name."""\n# and ' + OLD + ' again\nX = 1\n'),
        ])
        p = mig.plan(r, skeleton=os.path.join(self.tmp, "nothing-shipped"))
        self.assertEqual(p["rewrite"], [])
        self.assertFalse(p["needs_work"])

    def test_columns_survive_non_ascii_text_before_the_docstring_end(self):
        """ast counts bytes, tokenize counts characters; the conversion is what
        keeps a docstring ending after a non-ASCII char protected while the code
        on the next line still migrates."""
        body = ('"""Résumé: café ' + OLD + ' é"""\n'
                'from ' + OLD + ' import x  # ' + OLD + '\n')
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW, extra=[("automation/u.py", body)])
        mig.apply(r, commit=False, skeleton=os.path.join(self.tmp, "nothing-shipped"))
        got = open(os.path.join(r, "automation/u.py"), encoding="utf-8").read()
        self.assertEqual(got, '"""Résumé: café ' + OLD + ' é"""\nfrom ' + NEW + ' import x  # ' + OLD + '\n')

    def test_a_file_that_cannot_be_classified_refuses_the_instance(self):
        """No blanket fallback: a .py that carries the old name and does not
        parse is reported, apply refuses, and nothing else is written."""
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW, extra=[
            ("automation/broken.py", "x = (" + OLD + "\n"),
            ("q-consult/pipeline/voice.py", "from " + OLD + " import x\n"),
        ])
        p = mig.plan(r, skeleton=os.path.join(self.tmp, "nothing-shipped"))
        self.assertEqual(len(p["unparseable"]), 1)
        self.assertTrue(p["unparseable"][0].startswith("automation/broken.py: "))
        self.assertTrue(p["needs_work"])
        out = mig.apply(r, commit=False, skeleton=os.path.join(self.tmp, "nothing-shipped"))
        self.assertFalse(out["verified"])
        self.assertTrue(any("cannot be classified" in e for e in out["errors"]), out["errors"])
        self.assertEqual(out["rewritten"], [])
        self.assertIn(OLD, open(os.path.join(r, "q-consult/pipeline/voice.py")).read())

    def test_non_python_files_keep_the_blanket_swap(self):
        """Pinned on purpose: nothing here can tell a shell comment from a shell
        string, so .sh (and the rest of REWRITE_EXTS) still swap everything."""
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW, extra=[
            ("automation/run.sh", "# " + OLD + " era\nexport PKG=" + OLD + "\n"),
        ])
        mig.apply(r, commit=False, skeleton=os.path.join(self.tmp, "nothing-shipped"))
        self.assertEqual(open(os.path.join(r, "automation/run.sh")).read(),
                         "# " + NEW + " era\nexport PKG=" + NEW + "\n")

    def test_an_instance_is_never_its_own_skeleton(self):
        """A caller passing the instance as its skeleton would exempt every file
        and report a clean no-op on an unmigrated tree. Same path resolves to
        no skeleton at all, and the migration runs in full."""
        _, r = self._skeleton_and_instance()
        p = mig.plan(r, skeleton=r)
        self.assertIsNone(p["skeleton"])
        self.assertEqual(p["delivered_by_sync"], [])
        self.assertIn("q-consult/pipeline/voice.py", p["rewrite"])

    def test_the_move_still_happens_under_a_skeleton_that_ships_the_package(self):
        """The old package name never exists in the skeleton, so the move is
        planned from pre-move paths and proceeds; after it, the init the skeleton
        ships is left for the rsync and an instance-only module inside the
        package is still migrated."""
        sk, r = self._skeleton_and_instance(package=OLD, instance_carries_shipped=False)
        core = os.path.join(r, "plugins/kipi-core", OLD, "core.py")
        open(core, "w").write("from " + OLD + " import __init__ as _\n")
        out = mig.apply(r, commit=False, skeleton=sk)
        self.assertTrue(out["moved"])
        self.assertTrue(out["verified"], out["errors"])
        self.assertFalse(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        moved_core = open(os.path.join(r, "plugins/kipi-core", NEW, "core.py")).read()
        self.assertNotIn(OLD, moved_core)
        self.assertIn("plugins/kipi-core/" + NEW + "/core.py", out["rewritten"])
        self.assertNotIn("plugins/kipi-core/" + NEW + "/__init__.py", out["rewritten"])

    def test_exclude_lists_derive_from_the_updater_and_match_bash(self):
        """The owned subtrees and plugin excludes are read from kipi-update.sh,
        the file that runs the rsync. Floor: non-empty. Bound: equal to what
        bash itself evaluates the two arrays to."""
        owned, excl = mig._updater_lists(REPO)
        self.assertTrue(owned and excl)
        script = (
            'eval "$(sed -n \'/^INSTANCE_OWNED_SUBTREES=(/,/^)/p\' "$1")"; '
            'eval "$(sed -n \'/^PLUGIN_COPY_EXCLUDES=(/,/^)/p\' "$1")"; '
            'printf "O %s\\n" "${INSTANCE_OWNED_SUBTREES[@]}"; '
            'printf "P %s\\n" "${PLUGIN_COPY_EXCLUDES[@]}"')
        out = subprocess.run(["bash", "-c", script, "_", UPDATER], capture_output=True, text=True, check=True).stdout
        bash_owned = [l[2:] for l in out.splitlines() if l.startswith("O ")]
        bash_excl = [l[2:].split("::", 1)[1] for l in out.splitlines() if l.startswith("P ")]
        self.assertEqual(owned, bash_owned)
        self.assertEqual([r.pattern for r in excl], bash_excl)
        self.assertIn("my-project", owned)

    def test_an_owned_subtree_a_root_file_and_settings_are_the_instances_even_when_the_skeleton_has_them(self):
        """Round 1 major: the sync never writes these, so a stale import there
        must still migrate. Skeleton presence is not delivery."""
        sk, r = self._skeleton_and_instance()
        cases = [
            ("q-system/memory/tools/probe.py", "from " + OLD + " import x\n"),      # owned subtree
            ("q-system/.q-system/data/hook.py", "from " + OLD + " import x\n"),     # owned subtree, dotted
            ("lefthook.py", "from " + OLD + " import x\n"),                          # skeleton root
            (".claude/settings.json", '{"hooks": ["' + OLD + '/lint.py"]}\n'),      # merged, not copied
            ("plugins/kipi-core/.env.py", "from " + OLD + " import x\n"),          # PLUGIN_COPY_EXCLUDES
        ]
        for rel, body in cases:
            for root in (sk, r):
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").write(body)
        p = mig.plan(r, skeleton=sk)
        for rel, _ in cases:
            self.assertIn(rel, p["rewrite"], rel)
            self.assertNotIn(rel, p["delivered_by_sync"], rel)
        self.assertIn("q-system/.q-system/scripts/tool.py", p["delivered_by_sync"])
        out = mig.apply(r, commit=False, skeleton=sk)
        self.assertTrue(out["verified"], out["errors"])
        for rel, _ in cases:
            self.assertNotIn(OLD, open(os.path.join(r, rel)).read(), rel)

    def test_a_null_prefix_instance_maps_the_skeleton_q_system_onto_its_root(self):
        """Round 1 minor: with subtree_prefix null the skeleton's q-system/<x>
        lands at <x>, so that is where delivery is judged, owned subtrees
        included."""
        sk = os.path.join(self.tmp, "skeleton")
        for rel, body in [("q-system/.q-system/scripts/tool.py", "import " + OLD + ".core\n"),
                          ("q-system/memory/tools/probe.py", "from " + OLD + " import x\n")]:
            path = os.path.join(sk, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(body)
        r = build_instance(os.path.join(self.tmp, "flat"), package=NEW, extra=[
            (".q-system/scripts/tool.py", "import " + OLD + ".core\n"),
            ("memory/tools/probe.py", "from " + OLD + " import x\n"),
            ("q-system/.q-system/scripts/tool.py", "import " + OLD + ".core\n"),
        ])
        p = mig.plan(r, skeleton=sk, prefix="")
        self.assertEqual(p["prefix"], "")
        self.assertEqual(p["delivered_by_sync"], [".q-system/scripts/tool.py"])
        self.assertIn("memory/tools/probe.py", p["rewrite"])
        # under a null prefix the nested q-system/ copy is NOT where the sync writes
        self.assertIn("q-system/.q-system/scripts/tool.py", p["rewrite"])

    def test_the_prefix_comes_from_the_registry_beside_the_skeleton(self):
        sk, r = self._skeleton_and_instance()
        import json
        json.dump({"instances": [{"name": "i", "path": r, "subtree_prefix": None}]},
                  open(os.path.join(sk, "instance-registry.json"), "w"))
        self.assertEqual(mig.plan(r, skeleton=sk)["prefix"], "")
        json.dump({"instances": [{"name": "i", "path": r, "subtree_prefix": "q-system"}]},
                  open(os.path.join(sk, "instance-registry.json"), "w"))
        self.assertEqual(mig.plan(r, skeleton=sk)["prefix"], "q-system")
        os.unlink(os.path.join(sk, "instance-registry.json"))
        self.assertEqual(mig.plan(r, skeleton=sk)["prefix"], mig.DEFAULT_PREFIX)

    def test_unreadable_exclude_lists_exempt_nothing_and_say_so(self):
        """Fail toward migrating: a skeleton whose updater cannot be read
        exempts no path and the plan carries a warning, so the miss is churn,
        never a stranded import."""
        sk, r = self._skeleton_and_instance()
        real = mig._updater_lists
        mig._updater_lists = lambda skeleton: (_ for _ in ()).throw(ValueError("no updater here"))
        try:
            p = mig.plan(r, skeleton=sk)
        finally:
            mig._updater_lists = real
        self.assertIsNone(p["skeleton"])
        self.assertEqual(p["delivered_by_sync"], [])
        self.assertTrue(any("no path is exempt" in w for w in p["warnings"]), p["warnings"])
        self.assertIn("q-system/.q-system/scripts/tool.py", p["rewrite"])

    def test_the_plan_line_names_every_input_to_needs_work(self):
        """kipi-update.sh --dry pipes the human-readable plan line through sed,
        so a plan that says needs_work=True has to say which input made it so;
        `unparseable` was the one it could not name (PR #312 round 2)."""
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW, extra=[
            ("automation/broken.py", "x = (" + OLD + "\n"),
        ])
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run([sys.executable, MIGRATE, "--repo", r], capture_output=True, text=True, env=env)
        line = out.stdout.strip().splitlines()[-1]
        self.assertIn("unparseable=1", line)
        self.assertIn("needs_work=True", line)
        out = subprocess.run([sys.executable, MIGRATE, "--repo", r, "--apply", "--no-commit"],
                             capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 1)
        self.assertIn("unparseable=1", out.stdout)
        self.assertIn("verified=False", out.stdout)

    def test_both_present_never_deletes_either_package(self):
        """A half-synced instance is reported, not resolved by removal.

        Deleting a package directory is a destructive op and not this script's
        call (the 2026-05-17 volume-deletion scar). The stale copy is left for
        the rsync's own --delete or a founder decision.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        os.makedirs(os.path.join(r, "plugins", "kipi-core", NEW))
        self.assertEqual(mig.plan(r)["package_action"], "both_present")
        mig.apply(r, commit=False)
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", NEW)))

    def test_records_are_counted_but_never_rewritten(self):
        """.jsonl ledgers and .md docs say what was true when written."""
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("ledger.jsonl", '{"note": "' + OLD + ' shipped"}\n'),
            ("notes/review.md", "the " + OLD + " selector\n"),
        ])
        out = mig.apply(r, commit=False)
        self.assertIn(OLD, open(os.path.join(r, "ledger.jsonl")).read())
        self.assertIn(OLD, open(os.path.join(r, "notes/review.md")).read())
        self.assertTrue(any(p.endswith("ledger.jsonl") for p in out["history_left"]))

    def test_a_fixture_copy_is_left_alone(self):
        """tests/fixtures/* mirror real artifacts byte for byte.

        The skeleton's destructive-op reference fixture records the scar line
        naming the old package. Rewriting the copy makes it stop matching the
        original it exists to compare against.
        """
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("q-system/tests/fixtures/ref.sh", "# scar: " + OLD + " deleted\n"),
        ])
        mig.apply(r, commit=False)
        self.assertIn(OLD, open(os.path.join(r, "q-system/tests/fixtures/ref.sh")).read())

    def test_nested_repo_is_another_repos_problem(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        nested = os.path.join(r, "projects", "child")
        build_instance(nested)
        os.makedirs(os.path.join(nested, ".git"))
        mig.apply(r, commit=False)
        self.assertIn(OLD, open(os.path.join(nested, "pipeline/voice.py")).read())
        self.assertTrue(os.path.isdir(os.path.join(nested, "plugins/kipi-core", OLD)))

    def test_the_script_never_rewrites_itself(self):
        """Negative self-test: without the exemption this rule erases its rule."""
        self.assertTrue(mig._exempt(MIGRATE))
        plan = mig.plan(os.path.dirname(MIGRATE)) if False else None
        # And the exemption is by identity, not by name, so a copy is still subject.
        self.assertFalse(mig._exempt(os.path.join(self.tmp, "elsewhere.py")))

    def test_a_plan_document_filename_is_not_renamed(self):
        """A dated record's NAME is part of the record; other docs cite it."""
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            (f"q-system/output/plans/ask-565-{OLD}-skew-2026-08-09.md", "history\n"),
        ])
        out = mig.apply(r, commit=False)
        self.assertEqual(out["renamed"], [])
        self.assertTrue(os.path.exists(
            os.path.join(r, f"q-system/output/plans/ask-565-{OLD}-skew-2026-08-09.md")))

    def test_a_failed_commit_is_finished_by_the_next_run(self):
        """Reading the disk cannot see that the commit never happened.

        Measured 2026-08-30 on one instance: its own commit-msg gate refused
        the migration commit, so the bytes were right and the work sat staged. The
        next run saw the new name everywhere and reported already/needs_work=
        False, walking past a dirty tree that the updater's dirty guard would
        then refuse forever.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        mig.apply(r, commit=False)          # writes, never commits: the mid state
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)

        p = mig.plan(r)
        self.assertEqual(p["package_action"], "already")   # disk looks finished
        self.assertTrue(p["staged_migration"], "staged work not detected")
        self.assertTrue(p["needs_work"], "a staged-but-uncommitted migration "
                                         "reported as finished")

        out = mig.apply(r, commit=True)
        self.assertTrue(out["committed"], out["errors"])
        left = subprocess.run(["git", "-C", r, "diff", "--cached", "--name-only"],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(left, "", "staged work survived the recovery run")

    def test_the_commit_never_absorbs_unrelated_staged_work(self):
        """Codex MAJOR on PR #292 (sp-27bbf105): the commit carried no pathspec.

        The ADD was already scoped and the COMMIT was not, so `git commit -m`
        wrote the WHOLE index. The updater's dirty guard deliberately PERMITS
        staged work outside q-system/, .claude/ and plugins/, so a founder file
        in that permitted space landed inside a migration commit.

        This is feedback_defect_class_relocates: an earlier fix in this same
        file moved the hole from `git add` to `git commit` and the suite could
        not see it, because the only commit test staged everything with
        `git add -A` and then asserted the index came back EMPTY -- an
        assertion that only passes while the commit is unscoped. That test
        pinned the defect. Both halves are asserted here: unrelated staged work
        SURVIVES staged, and the migration itself still lands.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        os.makedirs(os.path.join(r, "notes"), exist_ok=True)
        open(os.path.join(r, "notes", "founder.md"), "w").write("before\n")
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)

        # A TRACKED founder file, edited and staged.
        open(os.path.join(r, "notes", "founder.md"), "w").write("staged edit\n")
        subprocess.run(["git", "-C", r, "add", "--", "notes/founder.md"], check=True)
        # A BRAND NEW founder file, staged but never committed. The two are
        # different git paths: one is a modification in HEAD, one is an addition.
        open(os.path.join(r, "notes", "new-wip.md"), "w").write("brand new\n")
        subprocess.run(["git", "-C", r, "add", "--", "notes/new-wip.md"], check=True)

        out = mig.apply(r, commit=True)
        self.assertTrue(out["committed"], out["errors"])

        landed = subprocess.run(
            ["git", "-C", r, "show", "--name-only", "--pretty=format:", "HEAD"],
            capture_output=True, text=True).stdout.split()
        self.assertNotIn("notes/founder.md", landed,
                         "migration commit absorbed a founder's staged edit")
        self.assertNotIn("notes/new-wip.md", landed,
                         "migration commit absorbed a founder's new staged file")

        still = subprocess.run(["git", "-C", r, "diff", "--cached", "--name-only"],
                               capture_output=True, text=True).stdout.split()
        self.assertIn("notes/founder.md", still,
                      "founder's staged edit was swept out of the index")
        self.assertIn("notes/new-wip.md", still,
                      "founder's new staged file was swept out of the index")

        # Negative half: scoping the commit must not stop the migration landing.
        self.assertIn("pipeline/voice.py", landed,
                      "the rewrite this migration exists to make never committed")
        head_voice = subprocess.run(
            ["git", "-C", r, "show", "HEAD:pipeline/voice.py"],
            capture_output=True, text=True).stdout
        self.assertIn(NEW, head_voice)
        self.assertNotIn(OLD, head_voice)

    def test_a_founder_edit_in_a_file_the_migration_rewrites_abandons_it(self):
        """Codex MAJOR round 2 on PR #292: the residual the pathspec did not close.

        Scoping the commit stopped it absorbing an UNRELATED staged file. It left
        the case where the founder's staged edit is in the VERY file the token
        swap has to touch: the swap and the edit are then the same file and no
        pathspec can separate them.

        So the migration does not write at all. It reports the error, the caller
        abandons the instance BEFORE the --delete rsync, and the founder's work is
        exactly where they left it. Loud and reversible beats a migration commit
        that quietly carries somebody's work in progress. The instance stays on
        the old package name, which is inert -- the rsync that would strand its
        imports never runs.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        voice = os.path.join(r, "pipeline", "voice.py")
        before = open(voice).read()
        open(voice, "a").write("# founder work in progress\n")
        subprocess.run(["git", "-C", r, "add", "--", "pipeline/voice.py"], check=True)

        out = mig.apply(r, commit=True)
        self.assertFalse(out["verified"], "wrote over a file the founder was editing")
        self.assertTrue(out["errors"])
        self.assertFalse(out["committed"])
        self.assertFalse(out["rewritten"], "rewrote despite refusing")

        # Nothing moved, so the instance is unchanged rather than half-migrated.
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))
        # The founder's edit is byte-for-byte where they left it, still staged.
        now = open(voice).read()
        self.assertEqual(now, before + "# founder work in progress\n")
        self.assertIn(OLD, now, "the token was swapped under a refusal")
        staged = subprocess.run(["git", "-C", r, "diff", "--cached", "--name-only"],
                                capture_output=True, text=True).stdout.split()
        self.assertIn("pipeline/voice.py", staged)

    def test_an_untracked_file_in_the_rewrite_set_does_not_abandon(self):
        """Negative control for the refusal, and it pins a DELIBERATE decision.

        An untracked file in the rewrite set is somebody's WIP too, but this
        module already decided to rewrite it and leave it untracked rather than
        let it import a package that no longer exists. If the refusal above
        widened to untracked files it would silently reverse that, so the
        refusal is scoped to TRACKED files with uncommitted changes.
        """
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("scratch/wip.py", "from " + OLD + " import x\n")])
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "--", "pipeline", "plugins"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        out = mig.apply(r, commit=True)
        self.assertTrue(out["verified"], out["errors"])
        self.assertIn("scratch/wip.py", out["rewritten"])
        self.assertIn("scratch/wip.py", out["left_untracked"])

    def test_an_untracked_file_is_backed_up_before_it_is_rewritten(self):
        """Codex BLOCKER on PR #292: git cannot restore what it never tracked.

        This module deliberately rewrites untracked files rather than leave them
        importing a package that no longer exists, and deliberately leaves them
        untracked. Both halves are right. What was missing is that an untracked
        file's ORIGINAL bytes exist in exactly one place, so an in-place rewrite
        of somebody's work in progress is unrecoverable -- `git checkout` restores
        a tracked file and has nothing to offer here.

        A tracked file gets no backup, on purpose: git already is the backup, and
        a `.bak` beside every rewritten module would be 36 pieces of litter in the
        one instance this runs on.
        """
        original = "from " + OLD + " import thing\n# my work in progress\n"
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("scratch/wip.py", original)])
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "--", "pipeline", "plugins"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)

        out = mig.apply(r, commit=True)
        self.assertTrue(out["verified"], out["errors"])
        wip = os.path.join(r, "scratch", "wip.py")
        self.assertIn(NEW, open(wip).read())        # still rewritten
        self.assertIn("scratch/wip.py", out["left_untracked"])

        backups = out["backed_up"]
        self.assertTrue(backups, "an untracked file was rewritten with no backup")
        self.assertEqual(len(backups), 1, backups)
        kept = os.path.join(r, backups[0])
        self.assertTrue(os.path.isfile(kept), kept)
        self.assertEqual(open(kept).read(), original,
                         "the backup does not hold the original bytes")

        # A TRACKED file gets none, because git already holds its original.
        self.assertNotIn("pipeline/voice.py", " ".join(backups))

    def test_the_rewrite_preserves_the_executable_bit(self):
        """Codex MAJOR on PR #292: correct content, inert artifact.

        The rewrite writes a fresh temp file at the default 0644 and os.replace()s
        it over the original, so every executable it touched came back
        non-executable. A hook or launchd job invoked as a bare path stops running
        at 0644 and says nothing -- the failure is silence, not an error. This
        module rewrites .sh files by design, so it was arming exactly that.
        """
        r = build_instance(os.path.join(self.tmp, "i"), extra=[
            ("bin/run.sh", "#!/bin/bash\nexec python3 -m " + OLD + "\n")])
        script = os.path.join(r, "bin", "run.sh")
        os.chmod(script, 0o755)
        before = os.stat(script).st_mode & 0o777
        self.assertEqual(before, 0o755)

        out = mig.apply(r, commit=False)
        self.assertIn("bin/run.sh", out["rewritten"])
        self.assertIn(NEW, open(script).read())
        self.assertEqual(os.stat(script).st_mode & 0o777, 0o755,
                         "the rewrite stripped the executable bit")

    def test_a_staged_binary_file_does_not_crash_planning(self):
        """Codex MAJOR on PR #292, and this one was introduced by the previous
        round's fix rather than found in the original.

        `staged_rewrites` asks git for the HEAD and index blobs of every staged
        path so it can spot a rewrite an interrupted run left behind. It asked
        through `_git`, which runs with text=True, so a staged BINARY file made
        subprocess raise UnicodeDecodeError while merely PLANNING. The updater's
        dirty guard permits staged work outside its managed paths, so a staged
        png is ordinary and would have taken the whole migration down before it
        read a single source file.
        """
        r = build_instance(os.path.join(self.tmp, "i"))
        blob = os.path.join(r, "asset.bin")
        with open(blob, "wb") as fh:
            fh.write(bytes(range(256)) * 8)         # invalid utf-8 by construction
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        with open(blob, "wb") as fh:
            fh.write(bytes(range(255, -1, -1)) * 8)
        subprocess.run(["git", "-C", r, "add", "--", "asset.bin"], check=True)

        p = mig.plan(r)                              # must not raise
        self.assertNotIn("asset.bin", p["staged_rewrites"])
        out = mig.apply(r, commit=True)              # nor must this
        self.assertTrue(out["verified"], out["errors"])

    def test_a_finished_instance_is_still_finished(self):
        """Negative control for the test above: the new signal must not make
        every already-migrated instance look like it needs work."""
        r = build_instance(os.path.join(self.tmp, "i"), package=NEW)
        subprocess.run(["git", "-C", r, "init", "-q"], check=True)
        subprocess.run(["git", "-C", r, "add", "-A"], check=True)
        subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "base"], check=True)
        p = mig.plan(r)
        self.assertEqual(p["staged_migration"], [])
        self.assertFalse(p["needs_work"])

    def test_refuses_to_run_against_the_skeleton(self):
        r = build_instance(os.path.join(self.tmp, "i"))
        open(os.path.join(r, "instance-registry.json"), "w").write("{}")
        rc = mig.main(["--repo", r, "--apply"])
        self.assertEqual(rc, 2)
        self.assertTrue(os.path.isdir(os.path.join(r, "plugins/kipi-core", OLD)))


class WiringTest(unittest.TestCase):
    """The engine being green proves nothing about the engine being CALLED."""

    def setUp(self):
        self.src = open(UPDATER).read()

    def test_the_updater_invokes_the_migration(self):
        self.assertIn("kipi-update-voiceloop-migrate.py", self.src,
                      "the updater does not reference the migration helper")
        self.assertRegex(self.src, r'VOICELOOP_MIGRATE"\s+--repo\s+"\$path"\s+--apply',
                         "the call site does not pass --apply, so it only previews")

    def test_it_runs_before_the_plugins_rsync(self):
        """Order is the whole point: after the rsync, --delete has already
        stranded the imports it was supposed to fix."""
        call = self.src.index("VOICELOOP_MIGRATE=")
        rsync = self.src.index("Syncing $prefix/ from skeleton")
        self.assertLess(call, rsync,
                        "migration runs AFTER the sync; the imports are already stranded")

    def test_it_runs_after_the_dirty_guard_and_checkpoint(self):
        guard = self.src.index("refusing to commit unrelated work")
        ckpt = self.src.index("could not checkpoint the instance")
        call = self.src.index("VOICELOOP_MIGRATE=")
        self.assertLess(guard, call, "migration writes before the tree is proven clean")
        self.assertLess(ckpt, call, "migration writes before the checkpoint is taken")

    def test_a_failed_migration_abandons_the_instance(self):
        window = self.src[self.src.index("VOICELOOP_MIGRATE="):][:1200]
        self.assertIn("abandon_instance", window,
                      "a failed migration falls through to the --delete rsync")

    def test_the_updater_still_parses(self):
        self.assertEqual(
            0, subprocess.run(["bash", "-n", UPDATER],
                              capture_output=True).returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
