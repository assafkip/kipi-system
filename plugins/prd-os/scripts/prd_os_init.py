"""Bootstrap a repo for prd-os by writing `.prd-os/config.json`.

This is the command the runners point at when they refuse to operate without
config (`config.py` raises "Run /prd-os-init in this repo first"). It writes the
default payload from `config.default_config_payload()` so every reader resolves
the same directories.

Idempotent and non-destructive: an existing config is left untouched (exit 0,
reported) unless `--force` rewrites it with the defaults. After writing, the
config is loaded back to prove it is valid.

Exit codes:
  0  initialized, or already initialized (no --force)
  2  repo root could not be resolved, or the written config failed to load
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    CONFIG_RELPATH,
    ConfigError,
    RepoRootNotFoundError,
    default_config_payload,
    discover_repo_root,
    load as load_config,
)


IGNORE_ENTRY = ".claude/state/"
IGNORE_COMMENT = "# prd-os runtime session state (never commit)"


def ensure_state_dir_ignored(repo_root: Path) -> bool:
    """Append the runtime-state ignore entry to .gitignore, idempotently.

    SKILL.md and README.md both promised the bootstrap did this. It did not:
    the script wrote config.json and nothing else, so the stated non-negotiable
    "Runtime state is never committed" had no blocker at all. Measured in a
    virgin repo 2026-08-05 -- `git check-ignore .claude/state/active-prd.json`
    returned nothing after a successful init.

    Returns True when an entry was added, False when one was already present.
    Appends; never rewrites a .gitignore the repo already owns.
    """
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.is_file() else ""
    # Match the path, not the exact line: `.claude/state/`, `.claude/state`,
    # and `/.claude/state/` all already ignore it, and appending a fourth
    # spelling would be the duplicate this guard exists to avoid.
    for line in existing.splitlines():
        if line.split("#", 1)[0].strip().strip("/") == ".claude/state":
            return False
    prefix = "" if existing == "" or existing.endswith("\n") else "\n"
    gitignore.write_text(f"{existing}{prefix}{IGNORE_COMMENT}\n{IGNORE_ENTRY}\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", help="override repo root discovery")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing config with the defaults",
    )
    args = parser.parse_args(argv)

    try:
        repo_root = (
            Path(args.repo_root).resolve() if args.repo_root else discover_repo_root()
        )
    except RepoRootNotFoundError as exc:
        sys.stderr.write(f"prd-os init: {exc}\n")
        return 2

    # Before the config early-return on purpose: repos initialized by an older
    # version never got this entry, and skipping it there would leave exactly
    # the repos that need repairing unprotected.
    ensure_state_dir_ignored(repo_root)

    config_path = repo_root / CONFIG_RELPATH
    if config_path.is_file() and not args.force:
        print(
            json.dumps(
                {
                    "exists": str(config_path),
                    "note": "already initialized; use --force to overwrite",
                }
            )
        )
        return 0

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(default_config_payload(), indent=2) + "\n")

    # Prove what we wrote actually loads under the strict reader.
    try:
        load_config(repo_root, strict=True)
    except ConfigError as exc:  # pragma: no cover - defensive
        sys.stderr.write(f"prd-os init: wrote config but it failed to load: {exc}\n")
        return 2

    print(json.dumps({"initialized": str(config_path)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
