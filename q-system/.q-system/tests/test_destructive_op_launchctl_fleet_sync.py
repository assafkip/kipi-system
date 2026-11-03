"""ASK-3661: `launchctl start` of a job that runs the fleet updater is the fleet sync.

READ-ONLY on ~/.claude and on the real ~/Library/LaunchAgents. Every case drives a
COPY of the vendored hook under a fake HOME that holds fixture plists, so the real
capability-token script, audit log and launch agents are never reached (a fake HOME
has no ~/.claude/bin/capability-token.sh, so a deny cannot be consumed by accident).

THE DEFECT, measured 2026-10-31 (ASK-3574): com.kipi.lessons-daily runs a script
that runs `bash kipi-update.sh` with no --only. FLEET_DENY is anchored on the
updater's own spelling, so `launchctl start com.kipi.lessons-daily` matched nothing
and a builder triggered a fleet-wide rsync with no kipi-approve.

The fixtures mirror the live shapes: a plist whose ProgramArguments is
[/bin/bash, <script>] and a script that invokes the updater in a subshell.
"""
import json
import os
import pathlib
import plistlib
import shutil
import subprocess

import pytest

QSYS = pathlib.Path(__file__).resolve().parents[1]
HOOK = QSYS / "hooks" / "destructive-op-deny.sh"


def _plist(path, label, args):
    path.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": args}))


@pytest.fixture()
def world(tmp_path):
    home = tmp_path / "home"
    la = home / "Library" / "LaunchAgents"
    la.mkdir(parents=True)
    (home / ".claude" / "audit").mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    # Mirrors lessons-daily.sh: updater invoked inside a subshell, plus a comment
    # and an echo that merely MENTION it.
    (scripts / "fleet.sh").write_text(
        "#!/bin/bash\n# runs kipi-update.sh later\n"
        'echo "kipi-update.sh will abort"\n'
        'if ( cd "$SKEL" && bash kipi-update.sh >> "$LOG" 2>&1 ); then :; fi\n')
    # Mentions the updater in a docstring and an echo only: must stay startable.
    (scripts / "mention.py").write_text(
        '"""after a `kipi update` rsync --delete the watchdog fires"""\n'
        "print('see kipi-update.sh')\n")
    (scripts / "plain.sh").write_text("#!/bin/bash\necho hi\n")
    (scripts / "pyfleet.py").write_text(
        "import subprocess\nsubprocess.run(['bash', '/x/kipi-update.sh'])\n")
    _plist(la / "com.kipi.fleet-sync.plist", "com.kipi.fleet-sync",
           ["/bin/bash", str(scripts / "fleet.sh")])
    _plist(la / "com.kipi.mention-only.plist", "com.kipi.mention-only",
           ["/usr/bin/python3", str(scripts / "mention.py")])
    _plist(la / "com.kipi.plain.plist", "com.kipi.plain",
           ["/bin/bash", str(scripts / "plain.sh")])
    _plist(la / "com.kipi.py-fleet.plist", "com.kipi.py-fleet",
           ["/usr/bin/python3", str(scripts / "pyfleet.py")])
    _plist(la / "com.kipi.inline.plist", "com.kipi.inline",
           ["/bin/bash", "-c", "cd /x && bash kipi-update.sh"])
    hook = tmp_path / "hook.sh"
    shutil.copy2(HOOK, hook)
    return {"home": home, "hook": hook, "la": la, "tmp": tmp_path}


def decide(world, command, hook=None):
    env = dict(os.environ, HOME=str(world["home"]))
    env.pop("ALLOW_DESTRUCTIVE", None)
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"}
    proc = subprocess.run(["bash", str(hook or world["hook"])], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)
    out = proc.stdout.strip()
    if not out:
        return "allow", ""
    parsed = json.loads(out)["hookSpecificOutput"]
    return parsed.get("permissionDecision", "allow"), parsed.get("permissionDecisionReason", "")


@pytest.mark.parametrize("command", [
    "launchctl start com.kipi.fleet-sync",
    "launchctl kickstart gui/501/com.kipi.fleet-sync",
    "launchctl kickstart -k gui/501/com.kipi.fleet-sync",
    "launchctl load ~/Library/LaunchAgents/com.kipi.fleet-sync.plist",
    "launchctl bootstrap gui/501 /x/Library/LaunchAgents/com.kipi.fleet-sync.plist",
    'launchctl start "com.kipi.fleet-sync"',
    "launchctl start com.kipi.fleet-'sync'",
    "echo ok && launchctl start com.kipi.fleet-sync",
    "/bin/launchctl start com.kipi.fleet-sync",
    "launchctl start com.kipi.py-fleet",
    "launchctl start com.kipi.inline",
])
def test_starting_a_fleet_sync_job_is_denied_with_the_approval_hash_flow(world, command):
    decision, reason = decide(world, command)
    assert decision == "deny", command
    assert "fleet-wide delete" in reason and "ASK-3661" in reason
    assert "kipi-approve" in reason, "same deny message and approval flow as the updater itself"


@pytest.mark.parametrize("command", [
    "launchctl list",
    "launchctl list com.kipi.fleet-sync",
    "launchctl print gui/501/com.kipi.fleet-sync",
    "launchctl stop com.kipi.fleet-sync",
    "launchctl unload ~/Library/LaunchAgents/com.kipi.fleet-sync.plist",
    "launchctl bootout gui/501/com.kipi.fleet-sync",
    "launchctl start com.kipi.plain",
    "launchctl start com.kipi.mention-only",
    "launchctl start com.apple.something",
    "launchctl start com.kipi.not-installed",
    "echo launchctl start com.kipi.fleet-sync-notes",
    "grep -n launchctl README.md",
])
def test_everything_else_stays_open(world, command):
    decision, reason = decide(world, command)
    assert decision == "allow", (command, reason)


def test_a_shell_expansion_in_the_label_is_denied_because_it_cannot_be_read(world):
    for command in ("L=com.kipi.fleet-sync; launchctl start $L",
                    "launchctl start com.kipi.$(echo fleet-sync)"):
        decision, reason = decide(world, command)
        assert decision == "deny", command
        assert "cannot be read" in reason


def test_the_label_list_is_derived_from_the_plists_not_hardcoded(world):
    """A job added tomorrow is covered with no edit to the hook; a job whose script
    stops invoking the updater stops being denied."""
    new = world["la"] / "com.kipi.brand-new.plist"
    _plist(new, "com.kipi.brand-new", ["/bin/bash", "-c", "bash kipi-update.sh"])
    assert decide(world, "launchctl start com.kipi.brand-new")[0] == "deny"
    _plist(new, "com.kipi.brand-new", ["/bin/bash", "-c", "echo hi"])
    assert decide(world, "launchctl start com.kipi.brand-new")[0] == "allow"


def test_a_path_argument_reads_the_file_that_would_run(world):
    """load/bootstrap run the plist at the PATH, which can differ from the installed
    copy of the same label."""
    elsewhere = world["tmp"] / "com.kipi.plain.plist"
    _plist(elsewhere, "com.kipi.plain", ["/bin/bash", "-c", "bash kipi-update.sh"])
    assert decide(world, "launchctl load %s" % elsewhere)[0] == "deny"
    assert decide(world, "launchctl load ~/Library/LaunchAgents/com.kipi.plain.plist")[0] == "allow"


def test_the_fleet_updater_direct_form_still_denies(world):
    assert decide(world, "bash kipi-update.sh")[0] == "deny"
    assert decide(world, "bash kipi-update.sh --dry-run")[0] == "allow"


@pytest.mark.parametrize("mutation,why", [
    ("start|kickstart|load|bootstrap) ;;", "load|bootstrap) ;;"),
    ("start|kickstart|load|bootstrap) ;;", "kickstart|load|bootstrap) ;;"),
    ("_launchd_plist_runs_updater \"$_lplist\"", "false"),
    ("  *launchctl*)\n", "  *launchctlX*)\n"),
])
def test_mutants_of_the_new_block_are_caught(world, mutation, why):
    """Negative self-test: a hook with the check weakened must FAIL the deny case."""
    src = HOOK.read_text(encoding="utf-8")
    assert src.count(mutation) == 1, "mutation anchor must be unique: %r" % mutation
    mutant = world["tmp"] / "mutant.sh"
    mutant.write_text(src.replace(mutation, why), encoding="utf-8")
    mutant.chmod(0o755)
    decision, _ = decide(world, "launchctl start com.kipi.fleet-sync", hook=mutant)
    assert decision == "allow", "mutant %r still denied: the test cannot see this line" % why


def test_the_mutant_harness_can_fail_on_the_unmutated_hook(world):
    assert decide(world, "launchctl start com.kipi.fleet-sync")[0] == "deny"


def test_the_installer_accepts_this_hook_over_the_one_it_replaces(world):
    """The founder's landing command is install-claude-hooks.py. It refuses a source
    that is weaker than, or reads an env variable the installed hook does not (an
    earlier draft of this block used BASH_REMATCH and was refused). Pre-change hook =
    this hook with the ASK-3661 block cut out."""
    src = HOOK.read_text(encoding="utf-8")
    start = src.index("  # ASK-3661: STARTING A FLEET-SYNC JOB")
    end = src.index("  # ASK-1118: the fleet exemption is decided per STAGE")
    home = world["tmp"] / "inst"
    hooks = home / (".clau" + "de") / "hooks"
    hooks.mkdir(parents=True)
    installed = hooks / "destructive-op-deny.sh"
    installed.write_text(src[:start] + src[end:], encoding="utf-8")
    installed.chmod(0o755)
    settings = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": str(installed), "timeout": 5}]}]}}
    (home / (".clau" + "de") / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    proc = subprocess.run(["python3", str(QSYS / "scripts" / "install-claude-hooks.py"),
                           "--home", str(home), "--dry-run"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "WOULD INSTALL" in proc.stdout
