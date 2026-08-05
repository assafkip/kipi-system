"""Virgin-repo lifecycle: prove prd-os delivers what it PROMISES, by running it.

Every other check in this plugin reads a diff, a spec, or this repo's own tree
with fixtures that presume the kipi layout. A promise with NO implementation
behind it appears in none of them, so it is structurally invisible: mutation
testing cannot kill a check that does not exist, and a diff reviewer cannot see
code that was never written.

This file is the missing layer. It installs the plugin's scripts into a fresh
`git init` repo containing one README, drives the documented lifecycle with
subprocess calls, and asserts on exit codes and on-disk effects. Deliberately
NOT using the shared fixtures: importing them would re-introduce the assumption
this file exists to break.

Provenance: every assertion below is derived from a defect found by executing
prd-os 0.16.6 this way (PRD `prd-prd-os-e2e-gaps-2026-08-05.md`). Each one was
observed RED before the fix landed; the PRD records the transcript.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
    )


def _run(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    """Run a plugin script AS A USER WOULD: subprocess, inside the repo.

    Env is scrubbed of the vars that would let the script resolve paths from
    the developer's own checkout instead of the virgin repo.
    """
    env = dict(os.environ)
    for leak in ("CLAUDE_PROJECT_DIR", "KIPI_HOME", "QROOT"):
        env.pop(leak, None)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=repo, capture_output=True, text=True, env=env,
    )


@pytest.fixture()
def virgin(tmp_path: Path) -> Path:
    """A repo with one README and nothing else. No kipi layout, no .prd-os."""
    repo = tmp_path / "virgin"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("# virgin\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _init(repo: Path) -> None:
    proc = _run(repo, "prd_os_init.py")
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# T-1: the bootstrap must deliver the protection it claims
# ---------------------------------------------------------------------------

def test_init_makes_runtime_state_ignored(virgin: Path):
    """SKILL.md: "Runtime state is never committed. The bootstrap command adds
    the state directory to .gitignore." Before the fix, prd_os_init.py wrote
    config.json and nothing else, so the claim had no blocker at all."""
    _init(virgin)
    probe = virgin / ".claude/state/active-prd.json"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("{}")
    checked = _git(virgin, "check-ignore", "-v", str(probe.relative_to(virgin)))
    assert checked.returncode == 0, (
        "runtime state is NOT gitignored after init; the documented "
        f"non-negotiable has no enforcement. git said: {checked.stdout!r}"
    )


def test_init_is_idempotent_and_does_not_duplicate_the_ignore_entry(virgin: Path):
    """Negative-fire: running init twice must not append a second entry, and
    must not clobber a .gitignore the repo already had."""
    (virgin / ".gitignore").write_text("node_modules/\n")
    _init(virgin)
    _init(virgin)
    body = (virgin / ".gitignore").read_text()
    assert "node_modules/" in body, "init clobbered the repo's existing .gitignore"
    assert body.count(".claude/state") == 1, (
        f"init appended a duplicate ignore entry:\n{body}"
    )


# ---------------------------------------------------------------------------
# T-3: the "portable core" must stay inside its documented split
# ---------------------------------------------------------------------------

def test_full_lifecycle_creates_nothing_outside_the_documented_split(virgin: Path):
    """SKILL.md "Portable core vs repo-local split" names .prd-os/ and
    .claude/state/ as the repo-local surface. Before the fix, archiving any PRD
    wrote q-system/output/skeptic-proposals/ into whatever repo you were in --
    the founder's "my projects are giant for no reason" complaint, found in a
    repo whose entire content was one README."""
    _init(virgin)
    created = _run(virgin, "prd_runner.py", "new", "lifecycle", "--title", "T")
    assert created.returncode == 0, created.stderr
    assert _run(virgin, "prd_runner.py", "advance", "draft").returncode == 0
    assert _run(virgin, "prd_runner.py", "archive").returncode == 0

    # `.gitignore` is a DOCUMENTED write (the runtime-state entry SKILL.md
    # promises), not incidental sprawl. Everything else outside .prd-os/ and
    # .claude/state/ is the sprawl this test exists to catch.
    allowed = {".git", ".gitignore", ".prd-os", ".claude", "README.md"}
    actual = {p.name for p in virgin.iterdir()}
    assert actual <= allowed, (
        f"lifecycle created paths outside the documented split: {actual - allowed}"
    )


# ---------------------------------------------------------------------------
# T-2: archive must not succeed while the standing gate is RED
# ---------------------------------------------------------------------------

def test_archive_refuses_while_a_spillover_item_is_open(virgin: Path):
    """no-orphan-findings.md: "gates run fails while any item is open (the
    enforcement of last resort)" and the item "cannot be forgotten". Before the
    fix, `gates run` exited 1 GATE RED and `archive` exited 0 on the same repo
    in the same moment -- the only thing holding the line was prose in
    commands/prd-archive.md asking the model to check."""
    _init(virgin)
    assert _run(virgin, "prd_runner.py", "new", "gated", "--title", "T").returncode == 0
    assert _run(virgin, "prd_runner.py", "advance", "draft").returncode == 0
    # Blocking severity so the `gates run` precondition below still holds:
    # since 2026-08-05 the standing gate blocks only on blocker/major/high.
    # ARCHIVE is deliberately stricter and refuses on ANY open item -- it is a
    # terminal closeout, and no-orphan-findings.md requires every item the work
    # touched to be reported there. Two different jobs, two different bars.
    added = _run(virgin, "prd_runner.py", "spillover", "add",
                 "--source", "gated", "--desc", "an open item",
                 "--severity", "major")
    assert added.returncode == 0, added.stderr

    gates = _run(virgin, "prd_runner.py", "gates", "run")
    assert gates.returncode != 0, "precondition failed: gates should be RED here"

    archived = _run(virgin, "prd_runner.py", "archive")
    assert archived.returncode != 0, (
        "archive succeeded while the standing gate was RED -- the ledger CAN "
        "be forgotten"
    )
    assert "spillover" in (archived.stderr + archived.stdout).lower(), (
        "archive refused but did not name spillover as the reason"
    )


def test_archive_still_succeeds_with_no_open_items(virgin: Path):
    """Negative-fire: the new gate must not break the ordinary path."""
    _init(virgin)
    assert _run(virgin, "prd_runner.py", "new", "clean", "--title", "T").returncode == 0
    assert _run(virgin, "prd_runner.py", "advance", "draft").returncode == 0
    archived = _run(virgin, "prd_runner.py", "archive")
    assert archived.returncode == 0, archived.stderr


# ---------------------------------------------------------------------------
# T-4: one id contract across every script
# ---------------------------------------------------------------------------

def test_slug_that_already_starts_with_prd_is_not_double_prefixed(virgin: Path):
    _init(virgin)
    created = _run(virgin, "prd_runner.py", "new", "prd-thing", "--title", "T")
    assert created.returncode == 0, created.stderr
    prd_id = json.loads(created.stdout)["created"]
    assert not prd_id.startswith("prd-prd-"), f"double-prefixed id: {prd_id}"


def test_the_id_new_reports_is_the_id_every_other_script_accepts(virgin: Path):
    """Found live: `new advtest` reported an id, and findings_writer refused it
    with "PRD spec not found" because the caller reused the slug. The contract
    is only honest if the reported id round-trips."""
    _init(virgin)
    created = _run(virgin, "prd_runner.py", "new", "roundtrip", "--title", "T")
    prd_id = json.loads(created.stdout)["created"]
    assert _run(virgin, "prd_runner.py", "advance", "draft").returncode == 0

    added = subprocess.run(
        [sys.executable, str(SCRIPTS / "findings_writer.py"),
         "add", prd_id, "--source", "claude-review"],
        cwd=virgin, capture_output=True, text=True,
        input='[{"severity":"minor","body":"round-trip probe"}]',
    )
    assert added.returncode == 0, (
        f"the id `new` reported ({prd_id!r}) was rejected downstream: "
        f"{added.stderr}"
    )


# ---------------------------------------------------------------------------
# T-5: the skill must not describe a system that no longer exists
# ---------------------------------------------------------------------------

def test_every_prd_command_on_disk_is_documented_in_the_skill():
    """Stronger than a stale-string grep, and self-maintaining: the skill's
    command list and the commands/ directory are one fact, so this fails when
    either side drifts. The original defect listed `/prd-revise` (never
    shipped) and omitted four commands that had.

    Only the /prd-* commands: issue-side commands ship in the kipi-dsse plugin
    and are named here, not enumerated.
    """
    body = (SCRIPTS.parent / "skills/prd-os/SKILL.md").read_text()
    on_disk = {p.stem for p in (SCRIPTS.parent / "commands").glob("prd-*.md")}
    assert on_disk, "no prd-* commands found; the glob or the layout moved"
    missing = {c for c in on_disk if f"/{c}" not in body}
    assert not missing, f"commands ship but the skill never mentions them: {missing}"


# Both files make promises to a reader. Checking only one is how the
# "registers hooks" claim survived to 0.18.0: the PRD listed README.md in its
# own Files Modified table, never touched it, and no test read it (ASK-402).
PROMISE_DOCS = ("skills/prd-os/SKILL.md", "README.md")


@pytest.mark.parametrize("doc", PROMISE_DOCS)
@pytest.mark.parametrize("stale", [
    "Scaffold only",
    "not yet wired",
    "does not exist yet",
    "must-fix",
    ".claude/commands/issue-",
    "No hooks wired yet",
    "No runner scripts yet",
    "No command files yet",
    # The exact promise phrasings, not the bare words: the corrected docs say
    # "does NOT register hooks", which must stay legal.
    "and register hooks",
    "registers hooks in",
])
def test_docs_do_not_carry_scaffold_era_text(doc: str, stale: str):
    """These shipped through 0.1.0 -> 0.17.0 telling every model the plugin was
    unwired, listing a command that never shipped, teaching a disposition enum
    findings_writer.DISPOSITIONS rejects, and promising a hook registration
    `prd_os_init.py` has never contained."""
    body = (SCRIPTS.parent / doc).read_text()
    assert stale not in body, f"{doc} still carries scaffold-era text: {stale!r}"


def test_promised_bootstrap_behavior_exists_in_the_bootstrap_script():
    """The docs may only promise what the script can do.

    Kept as an executable pairing rather than a prose rule: `.gitignore` IS
    implemented, hook registration is NOT, and the two claims sat one clause
    apart in the same sentence."""
    src = (SCRIPTS / "prd_os_init.py").read_text()
    body = "\n".join((SCRIPTS.parent / d).read_text() for d in PROMISE_DOCS)
    if "settings.json" not in src:
        assert "settings.json` idempotently" not in body, (
            "docs promise idempotent settings.json hook registration; "
            "prd_os_init.py has no settings.json code"
        )
    # The half that IS real must stay real.
    assert "ensure_state_dir_ignored" in src
    assert ".gitignore" in body


def test_skill_disposition_vocabulary_matches_the_writer(virgin: Path):
    """The enum in the doc and the enum in the chokepoint are one fact."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        from findings_writer import DISPOSITIONS
    finally:
        sys.path.pop(0)
    body = (SCRIPTS.parent / "skills/prd-os/SKILL.md").read_text()
    for value in DISPOSITIONS:
        assert value in body, (
            f"SKILL.md does not document the real disposition {value!r}"
        )
