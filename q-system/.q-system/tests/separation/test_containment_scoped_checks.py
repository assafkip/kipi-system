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

    failures = {
        command: result.stdout + result.stderr
        for command, result in results.items()
        if result.returncode != 0
    }
    assert failures == {}
