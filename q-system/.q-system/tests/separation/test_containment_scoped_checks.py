import ast
import re
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
ISSUES_DIR = REPO_ROOT / ".prd-os/issues"
PARENT_PRD = "prd-skeleton-data-containment-2026-07-24"
SELF_ISSUE = "sdc-scoped-green-checks"
SELF_COMMAND = (
    "python3 -m pytest -q "
    "q-system/.q-system/tests/separation/test_containment_scoped_checks.py"
)


def scalar(frontmatter, key):
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*(.+)$",
        frontmatter,
    )
    assert match is not None
    return match.group(1).strip()


def list_value(frontmatter, key):
    match = re.search(
        rf"(?ms)^{re.escape(key)}:\s*\n(.*?)(?=^[a-z_]+:|\Z)",
        frontmatter,
    )
    assert match is not None
    values = []
    for value in re.findall(r"(?m)^  - (.+)$", match.group(1)):
        value = value.strip()
        if value[:1] in {'"', "'"}:
            value = ast.literal_eval(value)
        values.append(value)
    return values


def issue_record(path):
    content = path.read_text(encoding="utf-8")
    frontmatter = content.split("---", 2)[1]
    return {
        "id": scalar(frontmatter, "id"),
        "status": scalar(frontmatter, "status"),
        "parent_prd": scalar(frontmatter, "parent_prd"),
        "required_checks": list_value(frontmatter, "required_checks"),
    }


def scoped_commands(records):
    return [
        command
        for record in records
        if record["parent_prd"] == PARENT_PRD
        and (
            record["status"] == "closed"
            or record["id"] == SELF_ISSUE
        )
        for command in record["required_checks"]
    ]


def test_unrelated_failure_is_not_inherited():
    records = [
        {
            "id": "completed-containment",
            "parent_prd": PARENT_PRD,
            "status": "closed",
            "required_checks": ["python3 -c 'raise SystemExit(0)'"],
        },
        {
            "id": "unrelated-debt",
            "parent_prd": "prd-unrelated-existing-debt",
            "status": "closed",
            "required_checks": ["python3 -c 'raise SystemExit(1)'"],
        },
    ]

    assert scoped_commands(records) == [
        "python3 -c 'raise SystemExit(0)'"
    ]


def test_every_completed_containment_check_is_independently_green():
    records = [
        issue_record(path)
        for path in sorted(ISSUES_DIR.glob("sdc-*.md"))
    ]
    commands = scoped_commands(records)

    assert SELF_COMMAND in commands
    assert all("validate-separation.py" not in command for command in commands)

    results = {}
    for command in commands:
        if command == SELF_COMMAND:
            continue
        result = subprocess.run(
            shlex.split(command),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        results[command] = result

    # "CANNOT RUN HERE" IS NOT "IS BROKEN", and conflating them made this test
    # fail in CI for a reason no commit could fix.
    #
    # the scar (2026-08-27): several of these commands check a SIBLING INSTANCE
    # by path -- `verify-containment-export.py --instance investigations` reads
    # that instance's owner directory. On a developer machine the whole fleet is
    # checked out, so they run. A CI runner has this repo and nothing else, so
    # the checker correctly refuses with "instance owner path does not exist"
    # and this assertion read that refusal as a containment defect. It was the
    # last red on the floor's first green run.
    #
    # The checker already distinguishes the two cases in its own output, so the
    # test honours that distinction instead of flattening it.
    ABSENT_FLEET = "instance owner path does not exist"
    failures = {}
    unrunnable = {}
    for command, result in results.items():
        if result.returncode == 0:
            continue
        output = result.stdout + result.stderr
        if ABSENT_FLEET in output:
            unrunnable[command] = output
        else:
            failures[command] = output

    # THE FLOOR, so this can never degrade into a test that skips everything and
    # reports green. If the fleet is absent AND nothing else ran, the assertion
    # below would be vacuous, which is the failure mode a lenient rule invites.
    ran = [c for c, r in results.items() if r.returncode == 0]
    assert ran or not unrunnable, (
        "every containment command was unrunnable; this test proved nothing. "
        f"unrunnable={sorted(unrunnable)}")

    assert failures == {}, (
        "containment checks failed for a real reason (not an absent sibling "
        f"instance): {failures}")
