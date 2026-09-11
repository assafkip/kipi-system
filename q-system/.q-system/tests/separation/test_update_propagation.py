"""Updater final states must not give an injected instance fact a free ride.

`kipi update` copies generic skeleton content into every registered instance. If
a client name, a deal size, or any other instance fact is sitting in a generic
source when that happens, the update fans it out across the fleet in one shot.
This proves the failure is caught in the FINAL STATE of every layout the
registry actually registers, not just in the skeleton it came from.

The fixtures are disposable copies run under a hermetic git environment, so no
production repo and no globally configured hook can be reached from here. The
test asserts that rather than assuming it.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATOR = REPO_ROOT / "validate-separation.py"
REGISTRY = REPO_ROOT / "instance-registry.json"
UPDATER = REPO_ROOT / "kipi-update.sh"

# Files the fixture's skeleton must carry because the updater invokes them from
# its own directory and is fail-closed on each. HAND-MAINTAINED, and that is
# precisely the problem: kipi-update-deletion-guard.py arrived with the
# sp-737ce1ae work, was never added, and two tests then failed on a missing
# fixture rather than on anything they assert (ASK-608). A comment describing
# that trap already sat beside the list and did not prevent the second instance,
# because a comment is not a guard.
#
# So the list is now CHECKED against what the updater actually invokes, by
# test_the_fixture_carries_every_helper_the_updater_invokes below. Adding a new
# fail-closed dependency to kipi-update.sh without adding it here now fails a
# test instead of silently breaking the propagation model.
UPDATER_HELPERS = (
    "kipi-update-preserve-scan.py",
    "kipi-update-deletion-guard.py",
    "kipi-settings-merge.py",
    "kipi-update-gitignore-block.py",
    "kipi-update-wip-check.py",
    "kipi-update-voiceloop-migrate.py",
    # The instance-ahead describe helper (PR #316). Arrived on main with the
    # report and was not added here, so the divergence test below went red on
    # every PR merged against that main: the exact trap this list documents.
    "kipi-update-instance-ahead.py",
    "settings-template.json",
)

# The fixture writes its own registry, so the updater referencing it is not a
# copy obligation.
_HELPER_DERIVATION_EXEMPT = frozenset({"instance-registry.json"})


def updater_invoked_files():
    """Every FILE kipi-update.sh reaches for in its own directory.

    Derived from the shipping script rather than restated, so the two cannot
    drift apart quietly. Directories (.claude, plugins, q-system) are excluded:
    the fixture builds those itself.
    """
    text = UPDATER.read_text(encoding="utf-8")
    found = set(re.findall(r'\$SCRIPT_DIR/([A-Za-z0-9._-]+\.[A-Za-z0-9]+)', text))
    return found - _HELPER_DERIVATION_EXEMPT


def test_the_fixture_carries_every_helper_the_updater_invokes():
    """The divergence check the missing-file scar earned.

    Both directions. A missing helper breaks the fixture silently, which is the
    bug that happened twice. A helper listed here but no longer invoked is dead
    weight that makes the next reader trust a stale list.
    """
    invoked = updater_invoked_files()
    listed = set(UPDATER_HELPERS)
    assert invoked, "derivation found no helpers; the pattern or the script moved"
    missing = invoked - listed
    assert not missing, (
        f"kipi-update.sh invokes {sorted(missing)} from its own directory but the "
        f"fixture never copies them, so the skeleton is incomplete and the "
        f"propagation model will not run"
    )
    stale = listed - invoked
    assert not stale, (
        f"the fixture copies {sorted(stale)}, which kipi-update.sh no longer "
        f"invokes; remove them rather than leaving a stale list"
    )

UNARMED_BASELINE = """{
  "schema_version": 1,
  "blocking_classes": [
    "case_proof_gap",
    "client_identity",
    "dated_interaction",
    "pricing",
    "relationship",
    "source_identity",
    "sourced_interaction"
  ],
  "classifier_sha256": null,
  "entries": []
}
"""

# The gate's own machinery has to sit INSIDE the tree it scans -- the preflight
# resolves it at q-system/.q-system/scripts/ -- so a fixture that ships a valid
# skeleton necessarily propagates these files too. They are Python and JSON
# full of `label: value` lines, so the classifier reports them, and this file's
# assertions are about whether PROPAGATION injects a fact, not about whether
# the classifier is quiet on source code. Excluding them keeps the assertion
# strict over the content the fixture actually models.
GATE_INFRASTRUCTURE = (
    "q-system/.q-system/scripts/propagation-leak-gate.py",
    "q-system/.q-system/scripts/containment-targets.py",
    "q-system/.q-system/state/propagation-leak-baseline.json",
    "validate-separation.py",
)


def fixture_violations(validator, instance):
    """Violations in the content this fixture models, not in the gate itself."""
    return [
        violation
        for violation in validator.semantic_separation_violations(instance)
        if violation["path"] not in GATE_INFRASTRUCTURE
    ]


# A generic, propagating source: not under any instance-owned prefix, so the
# updater's rsync carries it into every subtree instance.
GENERIC_SOURCE = "marketing/templates/outreach.md"
# The updater has more than one propagation channel. q-system/ moves by
# archive+rsync, while .claude/ config and plugins/ move by cp and a separate
# rsync with their own staging and commit. A fact in any of them fans out.
CONFIG_CHANNELS = (".claude/agents/generic.md", "plugins/core/playbook.md")
# A genuinely generic template: every field is a placeholder, which is what
# makes it safe to fan out. Asserted values here would be facts, not a template.
CLEAN_BODY = "# Outreach template\n\n- Opening: {{PROBLEM_IN_ONE_LINE}}\n"
# Grammar-conformant instance facts (see fixtures/fact-grammar.json): an
# identity plus a currency value, both asserted rather than placeheld.
INJECTED_BODY = (
    "# Outreach template\n\n"
    "- Client: Northwind Trading\n"
    "- Deal size: $45,000\n"
)
# Other shapes a real leak takes. Pinning the proof to one line shape would make
# the classifier look sharper than it is.
INJECTED_VARIANTS = (
    INJECTED_BODY,
    "# Outreach template\n\n- Source: Northwind kickoff call\n"
    "- Last contact: 2026-03-14\n",
    "# Outreach template\n\n- Account owner: Dana Reeve\n",
)

# Every (type, subtree_prefix) combination the registry uses needs a fixture
# here. A new layout with no fixture fails test_every_registered_layout_has_a_fixture.
FIXTURE_LAYOUTS = (("subtree", "q-system"), ("standalone", None))


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_separation", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registered_layouts():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {
        (instance.get("type", "subtree"), instance.get("subtree_prefix") or None)
        for instance in registry["instances"]
        if not str(instance.get("status", "")).startswith("merged")
    }


def hermetic_env(home):
    """Cut the fixtures off from the machine's git configuration.

    Without this the fixture commits and the updater inherit the operator's
    global config -- including `core.hooksPath`, which on this repo points at a
    real lefthook install. Scoping the registry to a temp dir is not containment
    while a globally configured hook can still fire against it.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }
    # Routing variables are not config: `git -C` does not override GIT_DIR or
    # GIT_WORK_TREE, so an exported one would aim fixture commits straight at a
    # production repository's metadata.
    for routing in (
        "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_WORK_TREE",
        "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
        "GIT_INDEX_VERSION", "GIT_ATTR_NOSYSTEM",
    ):
        env.pop(routing, None)
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t.t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t.t",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def git(root, env, *arguments, check=True):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false"] + list(arguments),
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def tree_digest(root):
    digest = hashlib.sha256()
    for current, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in sorted(files):
            candidate = Path(current, name)
            digest.update(str(candidate.relative_to(root)).encode() + b"\0")
            digest.update(candidate.read_bytes() + b"\0")
    return digest.hexdigest()


def build_skeleton(root, env, body):
    skeleton = root / "skeleton"
    (skeleton / "q-system" / "marketing" / "templates").mkdir(parents=True)
    (skeleton / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (skeleton / ".claude" / "agents").mkdir(parents=True)
    shutil.copy(UPDATER, skeleton / "kipi-update.sh")
    # kipi-update-deletion-guard.py added 2026-08-10 (ASK-608). It arrived with
    # the sp-737ce1ae fix and was never added here, so the fixture's skeleton
    # lacked a script the updater invokes unconditionally before its rsync. The
    # run died with "can't open file '.../skeleton/kipi-update-deletion-guard.py'",
    # nothing propagated, and this file's two propagation tests failed on a
    # missing fixture rather than on anything they assert.
    #
    # Same shape as the leak-gate note below, which is the tell: the fixture
    # enumerates the updater's hard dependencies by hand, so every new
    # fail-closed dependency silently breaks it until someone adds a line.
    for helper in UPDATER_HELPERS:
        shutil.copy(REPO_ROOT / helper, skeleton / helper)
    # A valid skeleton ships the propagation leak gate. kipi-update.sh is
    # fail-closed on it by design, so a fixture without it aborts before any
    # sync and this file's propagation model never runs. See GATE_INFRASTRUCTURE
    # for why these files are then excluded from the violation assertions.
    (skeleton / "q-system" / ".q-system" / "state").mkdir(parents=True, exist_ok=True)
    for gate_file in (
        "q-system/.q-system/scripts/propagation-leak-gate.py",
        "q-system/.q-system/scripts/containment-targets.py",
        "validate-separation.py",
    ):
        shutil.copy(REPO_ROOT / gate_file, skeleton / gate_file)
    # NOT the repo's committed baseline: that one is ARMED and its permits
    # describe THIS repo's content, so loading it over a synthetic skeleton
    # refuses ("a permit cannot exceed what was reviewed").
    (skeleton / "q-system/.q-system/state/propagation-leak-baseline.json").write_text(
        UNARMED_BASELINE, encoding="utf-8")
    (skeleton / "q-system" / GENERIC_SOURCE).write_text(body, encoding="utf-8")
    # The updater treats a missing capability gate as a failed sync.
    (skeleton / "q-system" / ".q-system" / "scripts" / "capability-gate.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    for channel in CONFIG_CHANNELS:
        target = skeleton / channel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    git(skeleton, env, "init", "-q", "-b", "main")
    git(skeleton, env, "add", "-A")
    git(skeleton, env, "commit", "-qm", "skeleton")
    return skeleton


def build_instance(root, env, name, layout, body):
    """Seed the generic source at the position this layout puts it in.

    A standalone instance is not skeleton-managed, so the updater never writes
    the fact into it. It still has to carry the fact at its own layout position,
    or the injected and clean runs would be identical there and the layout would
    prove nothing.
    """
    instance_type, prefix = layout
    instance = root / name
    (instance / ".claude").mkdir(parents=True)
    source = instance / prefix / GENERIC_SOURCE if prefix else instance / GENERIC_SOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    if prefix:
        # Overwritten by the sync; the skeleton copy is what lands.
        source.write_text(
            "# Outreach template\n\n- Opening: {{OLD_PLACEHOLDER}}\n", encoding="utf-8"
        )
    else:
        source.write_text(body, encoding="utf-8")
    (instance / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    git(instance, env, "init", "-q", "-b", "main")
    git(instance, env, "add", "-A")
    git(instance, env, "commit", "-qm", "instance")
    return instance


def run_updater(skeleton, env):
    return subprocess.run(
        ["bash", str(skeleton / "kipi-update.sh")],
        capture_output=True,
        text=True,
        cwd=str(skeleton),
        env=env,
    )


def build_fleet(root, body):
    """A disposable skeleton plus one instance per registered layout."""
    env = hermetic_env(root)
    skeleton = build_skeleton(root, env, body)
    instances = {}
    entries = []
    for layout in FIXTURE_LAYOUTS:
        instance_type, prefix = layout
        name = f"{instance_type}-instance"
        instances[layout] = build_instance(root, env, name, layout, body)
        entries.append(
            {
                "name": name,
                "path": str(instances[layout]),
                "subtree_prefix": prefix,
                "type": instance_type,
            }
        )
    skeleton.joinpath("instance-registry.json").write_text(
        json.dumps({"instances": entries}) + "\n", encoding="utf-8"
    )
    return skeleton, instances, env


def source_violations(validator, instance, prefix):
    relative = f"{prefix}/{GENERIC_SOURCE}" if prefix else GENERIC_SOURCE
    return [
        finding
        for finding in validator.semantic_separation_violations(instance)
        if str(finding.get("path", "")) == relative
    ]


def test_every_registered_layout_has_a_fixture():
    """A layout with no fixture is an untested propagation path."""
    missing = registered_layouts() - set(FIXTURE_LAYOUTS)
    assert missing == set(), (
        f"registry uses layouts with no propagation fixture: {sorted(missing)}"
    )


def test_no_production_instance_is_reachable_from_the_fixtures(tmp_path):
    """Containment by construction, asserted rather than assumed."""
    before = REGISTRY.read_bytes()
    skeleton, instances, env = build_fleet(tmp_path, INJECTED_BODY)

    production = {
        instance["path"] for instance in json.loads(before.decode())["instances"]
    }
    registry = json.loads((skeleton / "instance-registry.json").read_text())
    for entry in registry["instances"]:
        assert Path(entry["path"]).is_relative_to(tmp_path)
        assert entry["path"] not in production

    # No machine-level hook and no redirected git dir can reach these repos.
    for root in [skeleton, *instances.values()]:
        probe = git(root, env, "config", "--get", "core.hooksPath", check=False)
        assert probe.returncode != 0, (
            f"an inherited core.hooksPath leaked into {root}: {probe.stdout.strip()}"
        )
        effective = git(
            root, env, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ).stdout.strip()
        assert Path(effective).is_relative_to(tmp_path), (
            f"{root} resolved its git dir outside the fixture: {effective}"
        )

    run_updater(skeleton, env)
    assert REGISTRY.read_bytes() == before
    for instance in instances.values():
        assert Path(instance).is_relative_to(tmp_path)


def test_final_state_rejects_an_injected_fact_in_every_layout(tmp_path):
    """The injected fact must be caught in the FINAL STATE, in every layout.

    A subtree instance receives the generic source, so the separation validator
    has to report the fact there. A standalone instance is not skeleton-managed:
    the updater must refuse to write into it, and the fact it already carries
    must still be reported. Neither layout gives the fact a free ride.

    Boundary, stated rather than implied: this proves the final state FAILS the
    separation gate. It does NOT prove `kipi update` blocks the propagation
    while it runs -- nothing in the updater calls the separation check, so the
    fan-out succeeds and only a later `kipi check` catches it. That gap is
    captured as spillover sp-35f9910a; closing it needs kipi-update.sh or
    capability-gate.py, both outside this issue's allowed_files.
    """
    validator = load_validator()
    skeleton, instances, env = build_fleet(tmp_path, INJECTED_BODY)
    standalone = instances[("standalone", None)]
    standalone_before = tree_digest(standalone)

    result = run_updater(skeleton, env)

    subtree = instances[("subtree", "q-system")]
    propagated = subtree / "q-system" / GENERIC_SOURCE
    assert propagated.read_text(encoding="utf-8") == INJECTED_BODY, (
        f"the fixture never modelled propagation: {result.stdout}{result.stderr}"
    )
    assert source_violations(validator, subtree, "q-system"), (
        "an injected instance fact reached a subtree final state unreported"
    )

    # Every propagation channel, not just the q-system archive: .claude config
    # and plugins move through their own copy, stage, and commit path.
    reported = {
        str(finding.get("path", ""))
        for finding in validator.semantic_separation_violations(subtree)
    }
    for channel in CONFIG_CHANNELS:
        assert (subtree / channel).read_text(encoding="utf-8") == INJECTED_BODY, (
            f"the fixture never modelled propagation through {channel}: "
            f"{result.stdout}{result.stderr}"
        )
        assert channel in reported, (
            f"a fact propagated through {channel} went unreported: {sorted(reported)}"
        )

    # standalone is not skeleton-managed, so it has NO propagation path. Its
    # contribution is that the fact is still detected there and that the updater
    # refuses to build a managed tree inside it.
    # The refusal VOCABULARY changed; the refusal did not. "SKIP: standalone"
    # became "UNDECLARED NON-PROPAGATING: standalone-instance" -- the same
    # decision reported by the check that now catches every instance with no
    # declared propagation target. Pinning the old phrase made a passing
    # behaviour read as a regression (ASK-608).
    #
    # Rebound to the property rather than the sentence, and deliberately
    # STRICTER than what it replaces: the refusal line must NAME the instance.
    # The original substring would have accepted a refusal about some other
    # instance entirely. The two assertions below are the real proof -- nothing
    # was written, and no managed tree was created -- and they could not run
    # while this line failed first.
    refusal = [line for line in result.stdout.splitlines()
               if "standalone" in line
               and ("SKIP" in line or "UNDECLARED" in line
                    or "NON-PROPAGATING" in line)]
    assert refusal, (
        "the updater did not report refusing the standalone instance: "
        f"{result.stdout}"
    )
    assert tree_digest(standalone) == standalone_before, (
        "the updater wrote into a standalone instance"
    )
    assert not (standalone / "q-system").exists(), (
        "the updater created a managed tree inside a standalone instance"
    )
    assert source_violations(validator, standalone, None), (
        "an injected instance fact in a standalone final state went unreported"
    )


def test_clean_final_state_reports_nothing(tmp_path):
    """The control. Without the injection every layout has to come back clean.

    Without this, a validator that flagged everything would pass the test above
    while proving nothing.
    """
    validator = load_validator()
    skeleton, instances, env = build_fleet(tmp_path, CLEAN_BODY)

    result = run_updater(skeleton, env)

    subtree = instances[("subtree", "q-system")]
    assert (subtree / "q-system" / GENERIC_SOURCE).read_text() == CLEAN_BODY, (
        f"the clean fixture never propagated: {result.stdout}{result.stderr}"
    )
    for layout, instance in instances.items():
        assert fixture_violations(validator, instance) == [], (
            f"the clean {layout[0]} final state reported a violation"
        )


def test_injected_fact_is_grammar_conformant():
    """The injection must be a real fact by the repo's own grammar.

    A payload the classifier ignores would make every assertion above vacuous.
    """
    validator = load_validator()
    for variant in INJECTED_VARIANTS:
        assert validator.semantic_leakage_findings(variant, GENERIC_SOURCE), (
            f"the classifier ignored this leak shape: {variant!r}"
        )
    assert validator.semantic_leakage_findings(CLEAN_BODY, GENERIC_SOURCE) == []

    with pytest.raises(TypeError):
        validator.semantic_leakage_findings(None)
