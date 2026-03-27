import subprocess
from pathlib import Path


class GitOps:
    def __init__(self, skeleton_remote: str, skeleton_branch: str = "main"):
        self.skeleton_remote = skeleton_remote
        self.skeleton_branch = skeleton_branch

    def run_git(self, args: list[str], cwd: Path) -> dict:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def init_repo(self, cwd: Path) -> dict:
        return self.run_git(["init"], cwd)

    def subtree_add(self, cwd: Path, prefix: str = "q-system") -> dict:
        return self.run_git(
            [
                "subtree", "add",
                f"--prefix={prefix}",
                self.skeleton_remote,
                self.skeleton_branch,
                "--squash",
            ],
            cwd,
        )

    def subtree_pull(self, cwd: Path, prefix: str = "q-system") -> dict:
        return self.run_git(
            [
                "subtree", "pull",
                f"--prefix={prefix}",
                self.skeleton_remote,
                self.skeleton_branch,
                "--squash",
            ],
            cwd,
        )

    def subtree_push(self, cwd: Path, prefix: str = "q-system") -> dict:
        return self.run_git(
            [
                "subtree", "push",
                f"--prefix={prefix}",
                self.skeleton_remote,
                self.skeleton_branch,
            ],
            cwd,
        )

    def git_pull(self, cwd: Path) -> dict:
        return self.run_git(["pull", "--ff-only", "origin", "main"], cwd)

    def check_instance_content(
        self, prefix_path: Path, patterns: list[str] | None = None
    ) -> list[str]:
        if patterns is None:
            patterns = ["KTLYST", "ktlyst", "CISO", "re-breach", "/Users/"]

        matched_files: set[str] = set()
        for pattern in patterns:
            result = subprocess.run(
                ["grep", "-ril", pattern, str(prefix_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                matched_files.update(result.stdout.strip().splitlines())

        return sorted(matched_files)
