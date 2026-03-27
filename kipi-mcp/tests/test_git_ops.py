from pathlib import Path
from unittest.mock import call

from kipi_mcp.git_ops import GitOps

REMOTE = "https://github.com/example/skeleton.git"
BRANCH = "main"


def _mock_result(returncode=0, stdout="", stderr=""):
    """Build a fake subprocess.CompletedProcess."""
    class FakeResult:
        pass
    r = FakeResult()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_run_git_success(mocker):
    mocker.patch(
        "subprocess.run",
        return_value=_mock_result(0, stdout="ok\n"),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.run_git(["status"], Path("/repo"))

    assert result == {
        "success": True,
        "stdout": "ok\n",
        "stderr": "",
        "returncode": 0,
    }
    import subprocess
    subprocess.run.assert_called_once_with(
        ["git", "status"],
        capture_output=True,
        text=True,
        cwd="/repo",
    )


def test_run_git_failure(mocker):
    mocker.patch(
        "subprocess.run",
        return_value=_mock_result(1, stderr="fatal: not a repo\n"),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.run_git(["status"], Path("/bad"))

    assert result["success"] is False
    assert result["returncode"] == 1
    assert "fatal" in result["stderr"]


def test_init_repo(mocker):
    mock_run = mocker.patch(
        "subprocess.run",
        return_value=_mock_result(0, stdout="Initialized\n"),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.init_repo(Path("/new-repo"))

    assert result["success"] is True
    mock_run.assert_called_once_with(
        ["git", "init"],
        capture_output=True,
        text=True,
        cwd="/new-repo",
    )


def test_subtree_add(mocker):
    mock_run = mocker.patch(
        "subprocess.run",
        return_value=_mock_result(0),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.subtree_add(Path("/repo"), prefix="q-system")

    assert result["success"] is True
    mock_run.assert_called_once_with(
        [
            "git", "subtree", "add",
            "--prefix=q-system",
            REMOTE,
            BRANCH,
            "--squash",
        ],
        capture_output=True,
        text=True,
        cwd="/repo",
    )


def test_subtree_pull(mocker):
    mock_run = mocker.patch(
        "subprocess.run",
        return_value=_mock_result(0),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.subtree_pull(Path("/repo"))

    assert result["success"] is True
    mock_run.assert_called_once_with(
        [
            "git", "subtree", "pull",
            "--prefix=q-system",
            REMOTE,
            BRANCH,
            "--squash",
        ],
        capture_output=True,
        text=True,
        cwd="/repo",
    )


def test_subtree_push(mocker):
    mock_run = mocker.patch(
        "subprocess.run",
        return_value=_mock_result(0),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.subtree_push(Path("/repo"))

    assert result["success"] is True
    mock_run.assert_called_once_with(
        [
            "git", "subtree", "push",
            "--prefix=q-system",
            REMOTE,
            BRANCH,
        ],
        capture_output=True,
        text=True,
        cwd="/repo",
    )


def test_git_pull(mocker):
    mock_run = mocker.patch(
        "subprocess.run",
        return_value=_mock_result(0, stdout="Already up to date.\n"),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.git_pull(Path("/repo"))

    assert result["success"] is True
    mock_run.assert_called_once_with(
        ["git", "pull", "--ff-only", "origin", "main"],
        capture_output=True,
        text=True,
        cwd="/repo",
    )


def test_check_instance_content_no_matches(mocker):
    mock_run = mocker.patch(
        "subprocess.run",
        return_value=_mock_result(1, stdout=""),
    )
    ops = GitOps(REMOTE, BRANCH)
    result = ops.check_instance_content(Path("/repo/q-system"))

    assert result == []
    assert mock_run.call_count == 5  # one per default pattern


def test_check_instance_content_with_matches(mocker):
    def side_effect(args, **kwargs):
        pattern = args[2]
        if pattern == "KTLYST":
            return _mock_result(0, stdout="/repo/q-system/config.yml\n")
        if pattern == "/Users/":
            return _mock_result(0, stdout="/repo/q-system/setup.sh\n/repo/q-system/config.yml\n")
        return _mock_result(1, stdout="")

    mocker.patch("subprocess.run", side_effect=side_effect)
    ops = GitOps(REMOTE, BRANCH)
    result = ops.check_instance_content(Path("/repo/q-system"))

    assert "/repo/q-system/config.yml" in result
    assert "/repo/q-system/setup.sh" in result
    assert len(result) == 2
