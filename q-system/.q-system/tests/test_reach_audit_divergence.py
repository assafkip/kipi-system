#!/usr/bin/env python3
"""The reach audit's verdict must never be more optimistic than a real dry run.

THE SCAR (ASK-831, sp-940bcf47). On 2026-08-15 `fleet-reach-audit.py` printed
"REACH: 22 of 22 would sync now". A `kipi-update.sh --dry-run` minutes later
printed "Failed: 1 / NOT UPDATED: KTLYST_strategy / ERROR: untracked WIP
collides with skeleton path". The audit modelled the dirty-tree guard and
nothing else, so an instance blocked SOLELY by a precondition it did not model
was reported green. That number was quoted all session, in commits and PR
bodies, and nobody caught it until the founder ran the updater.

WHY THIS FILE IS THE FIX AND NOT A SECOND COPY OF THE UPDATER. Teaching the
audit each precondition one at a time is the repair that rots: it drifts the
moment somebody edits the real one, and the drift is invisible in exactly the
same way. Instead the audit degrades to UNKNOWN for anything it does not model,
and THIS test is what holds that: it runs the real `kipi-update.sh --dry-run`
against each fixture instance and fails whenever the outcome disagrees with the
audit's verdict. A precondition nobody modelled shows up here as a red test
rather than as a green number.

The fixture style is `test_fleet_unblock.py`'s `world`: a real skeleton and real
instance repos in a tmpdir, running the real shipping scripts. Nothing is mocked
-- the thing under test is whether two programs agree about real git state, and
a mocked updater would agree with anything.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

SKELETON_SRC = pathlib.Path(__file__).resolve().parents[3]
AUDIT = SKELETON_SRC / "fleet-reach-audit.py"
UPDATER = SKELETON_SRC / "kipi-update.sh"

GIT_ENV = [
    "-c", "user.email=t@t.t", "-c", "user.name=t",
    "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main",
]


def git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-C", str(repo), *GIT_ENV, *args], capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} in {repo}: {proc.stderr}")
    return proc.stdout.strip()


def write(root, rel, text):
    full = pathlib.Path(root) / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text)
    return full


def build_skeleton(root):
    """A real skeleton: the shipping scripts, a real q-system tree, one commit.

    Copied rather than stubbed because the updater reads its own helpers off
    SCRIPT_DIR at run time (preserve-scan, settings-merge, the deletion guard),
    and the audit parses INSTANCE_OWNED_SUBTREES out of the real kipi-update.sh.
    """
    skel = pathlib.Path(root) / "skeleton"
    skel.mkdir(parents=True)
    shutil.copytree(SKELETON_SRC / "q-system", skel / "q-system",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for pattern in ("*.py", "*.sh", "*.json", "*.yml"):
        for src in SKELETON_SRC.glob(pattern):
            shutil.copy(src, skel / src.name)
    if (SKELETON_SRC / "plugins").is_dir():
        shutil.copytree(SKELETON_SRC / "plugins", skel / "plugins",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (skel / "kipi-update.sh").chmod(0o755)
    # The path the WIP instance will collide with. Skeleton-owned, so the
    # updater's archive carries it and the collision check has a counterpart.
    write(skel, "q-system/.q-system/scripts/skel-tool.py", "# skeleton copy\n")
    return skel


def build_instance(root, name):
    inst = pathlib.Path(root) / name
    inst.mkdir(parents=True)
    write(inst, "q-system/CLAUDE.md", "instance rules\n")
    write(inst, "q-system/.q-system/scripts/skel-tool.py", "# skeleton copy\n")
    write(inst, ".claude/settings.json", "{}\n")
    git(inst, "init", "-q", ".")
    git(inst, "add", "-A")
    git(inst, "commit", "-qm", "instance base")
    return inst


def register(skel, instances):
    write(skel, "instance-registry.json", json.dumps({
        "skeleton": str(skel),
        "instances": [
            {"name": name, "path": str(path), "subtree_prefix": "q-system",
             "instance_q_dir": f"q-{name}", "type": "subtree", "has_git": True}
            for name, path in instances
        ],
        "standalone": [],
        "eliminated": [],
    }, indent=2))
    git(skel, "init", "-q", ".")
    git(skel, "add", "-A")
    git(skel, "commit", "-qm", "skeleton base")


@pytest.fixture
def fleet(tmp_path):
    """One skeleton, three instances, each blocked (or not) a different way.

    clean  nothing dirty, nothing untracked -- the updater has no reason to
           refuse it.
    dirty  a tracked edit inside the sync's write set -- the ONE precondition
           the audit models.
    wip    an untracked file colliding with a skeleton path, carrying bytes the
           skeleton never shipped. This is the KTLYST_strategy shape: invisible
           to the audit's model, fatal to the updater.
    """
    skel = build_skeleton(tmp_path)
    clean = build_instance(tmp_path, "clean")
    dirty = build_instance(tmp_path, "dirty")
    wip = build_instance(tmp_path, "wip")

    write(dirty, "q-system/CLAUDE.md", "founder edit in the sync's write set\n")

    # Untracked, colliding, and genuinely WIP: bytes the skeleton has never held
    # at this path, so the PR #185 historical-blob exemption does not excuse it.
    write(wip, "q-system/.q-system/scripts/wip-tool.py", "# founder work in flight\n")
    write(skel, "q-system/.q-system/scripts/wip-tool.py", "# skeleton copy\n")

    register(skel, [("clean", clean), ("dirty", dirty), ("wip", wip)])
    return skel, {"clean": clean, "dirty": dirty, "wip": wip}


def audit_verdicts(skel, *extra):
    proc = subprocess.run(
        ["python3", str(skel / "fleet-reach-audit.py"), "--json",
         "--skeleton", str(skel), *extra],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return {row["name"]: row["verdict"] for row in json.loads(proc.stdout)}


def dry_run_failed(skel, name):
    """True when the real updater refuses this instance. The ground truth.

    --dry-run only, and against throwaway repos, so this never touches a real
    instance. The updater exits non-zero when any instance failed; with --only
    that is this instance.
    """
    proc = subprocess.run(
        ["bash", str(skel / "kipi-update.sh"), "--dry-run", "--only", name],
        capture_output=True, text=True, cwd=str(skel),
    )
    out = proc.stdout + proc.stderr
    assert "Failed:" in out, f"updater produced no summary for {name}:\n{out}"
    failed = int(out.split("Failed:")[1].split("\n")[0].strip())
    return failed > 0, out


# --------------------------------------------------------------------------
# The divergence guard. This is the durable one: it catches the NEXT
# unmodelled precondition without anyone remembering to model it.
# --------------------------------------------------------------------------

def check_agreement(skel, instances, verdicts):
    """WOULD-SYNC must mean it syncs; BLOCKED must mean it does not.

    UNKNOWN makes no claim and is compatible with either outcome -- that is the
    entire point of having a third bucket. It is not a free pass: an audit that
    answered UNKNOWN for everything would still fail
    `test_the_divergence_guard_goes_red_when_the_audit_overclaims`, which forces
    a WOULD-SYNC out of it and checks the guard bites.
    """
    problems = []
    for name in sorted(instances):
        verdict = verdicts[name]
        failed, out = dry_run_failed(skel, name)
        if verdict == "WOULD-SYNC" and failed:
            problems.append(
                f"{name}: audit said WOULD-SYNC, updater refused:\n{out}")
        if verdict.startswith("BLOCKED") and not failed:
            problems.append(
                f"{name}: audit said {verdict}, updater synced it:\n{out}")
    return problems


def test_audit_verdict_and_dry_run_agree_for_every_instance(fleet):
    skel, instances = fleet
    problems = check_agreement(skel, instances, audit_verdicts(skel))
    assert not problems, "\n\n".join(problems)


def test_the_untracked_wip_instance_is_not_reported_would_sync(fleet):
    """The exact 2026-08-15 claim, pinned. Named so the scar stays greppable."""
    skel, _ = fleet
    assert audit_verdicts(skel)["wip"] != "WOULD-SYNC"


def test_the_updater_really_does_refuse_the_wip_instance(fleet):
    """The control. Without it, the assertion above passes against a fixture
    that never reproduced anything."""
    skel, _ = fleet
    failed, out = dry_run_failed(skel, "wip")
    assert failed, out
    assert "untracked WIP collides" in out, out


def test_the_divergence_guard_goes_red_when_the_audit_overclaims(fleet):
    """Mutation: tell the audit it models every precondition, and it starts
    claiming WOULD-SYNC for the WIP instance again. The guard must bite.

    A test that can only pass is decoration. This names the input that makes it
    RED for the reason we care about.
    """
    skel, instances = fleet
    verdicts = audit_verdicts(skel, "--assume-full-coverage")
    assert verdicts["wip"] == "WOULD-SYNC", (
        "the mutation did not reintroduce the overclaim, so this control "
        "proves nothing")
    problems = check_agreement(skel, instances, verdicts)
    assert problems, "the divergence guard did not notice an overclaim"


# --------------------------------------------------------------------------
# The verdict set and the summary line
# --------------------------------------------------------------------------

def test_unmodelled_preconditions_land_in_the_unknown_bucket(fleet):
    skel, _ = fleet
    verdicts = audit_verdicts(skel)
    assert verdicts["clean"] == "UNKNOWN"
    assert verdicts["wip"] == "UNKNOWN"
    assert verdicts["dirty"] == "BLOCKED-FOUNDER"


def test_the_summary_reports_how_many_are_unknown(fleet):
    skel, _ = fleet
    proc = subprocess.run(
        ["python3", str(skel / "fleet-reach-audit.py"), "--skeleton", str(skel)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    reach = [line for line in out.splitlines() if line.startswith("REACH:")]
    assert len(reach) == 1, out
    # Line-exact, not a substring: the caveated line CONTAINS the bare one as a
    # prefix, so `"REACH: 0 of 3 would sync now" not in out` would pass against
    # a build that never learned the caveat.
    assert reach[0] != "REACH: 0 of 3 would sync now", (
        "a bare reach line while instances are unknown is the 22-of-22 claim "
        "again:\n" + out)
    assert "2 cannot tell from here" in reach[0], reach[0]


def test_the_unmodelled_preconditions_are_named_not_just_counted(fleet):
    """A count says "trust me less"; the names say what to go model next."""
    skel, _ = fleet
    proc = subprocess.run(
        ["python3", str(skel / "fleet-reach-audit.py"), "--skeleton", str(skel)],
        capture_output=True, text=True,
    )
    assert "untracked WIP collides with skeleton path" in proc.stdout, proc.stdout


def test_a_refusal_site_the_audit_models_is_not_counted_as_unmodelled(fleet):
    """The dirty-tree guard IS modelled, so it must not appear in the gap list.

    If it did, the coverage registry would be decorative: every site unmodelled
    forever, and the gap list would stop pointing at anything actionable.
    """
    skel, _ = fleet
    proc = subprocess.run(
        ["python3", str(skel / "fleet-reach-audit.py"), "--skeleton", str(skel)],
        capture_output=True, text=True,
    )
    assert "dirty working tree" not in proc.stdout, proc.stdout


def test_the_coverage_registry_is_derived_from_the_updater_not_transcribed(fleet):
    """Add a refusal site to the updater; it must show up as a new gap.

    This is what stops the registry from rotting the way a hand-copied list of
    preconditions would.
    """
    skel, _ = fleet
    updater = skel / "kipi-update.sh"
    text = updater.read_text()
    marker = '      abandon_instance "  ERROR: fetch failed" && continue'
    assert marker in text, "fixture assumption broke: fetch-failed site moved"
    updater.write_text(text.replace(
        marker,
        marker + '\n      abandon_instance "  ERROR: brand new precondition" '
                 '&& continue'))
    proc = subprocess.run(
        ["python3", str(skel / "fleet-reach-audit.py"), "--skeleton", str(skel)],
        capture_output=True, text=True,
    )
    assert "brand new precondition" in proc.stdout, proc.stdout
