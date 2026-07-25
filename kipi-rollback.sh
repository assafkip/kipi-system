#!/bin/bash
set -euo pipefail

# kipi rollback [instance] -- revert the last skeleton-sync commit in one or all
# registered instances. (H3 from the claudesidian harvest brief.)
#
# Safe by construction (these are the load-bearing correctness rules, not polish):
#   - Finds the sync commit by MESSAGE-PREFIX (git log --grep), never `git revert HEAD`.
#     A later content commit may sit on top of the sync; reverting HEAD would undo the
#     WRONG commit. (PRD finding-1.)
#   - Uses `git revert` (non-destructive). Never a hard reset -- the founder's
#     destructive-op hook blocks that anyway, and revert is the correct primitive.
#   - Refuses on a dirty working tree (don't bury uncommitted work). (PRD finding-1.)
#   - On a revert CONFLICT, aborts cleanly (`git revert --abort`) and reports FAIL --
#     never leaves a half-applied revert (REVERT_HEAD + conflict markers). (PRD finding-7.)
#
# Instance-content safety holds BECAUSE kipi-update.sh's rsync --delete EXCLUDES
# my-project/, canonical/, memory/, output/, and bus/ -- so the sync commit never
# touched those dirs and reverting it cannot disturb founder state. (PRD finding-3.)
# If a future kipi-update.sh drops one of those --exclude lines, revisit this safety.

KIPI_HOME="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
REGISTRY="${KIPI_REGISTRY:-$KIPI_HOME/instance-registry.json}"
SYNC_PREFIX='^chore: sync q-system from skeleton'
ONLY="${1:-}"   # optional: scope rollback to a single instance by name

PASS=0; SKIP=0; FAIL=0

latest_receipt() {
  local path="$1" dir
  dir="${KIPI_UPDATER_RECEIPT_DIR:-$path/q-system/.q-system/state/updater-receipts}"
  [ -d "$dir" ] || return 0
  python3 - "$dir" <<'PY'
import json
import pathlib
import sys

# Newest updater APPLY receipt wins: created_at first, filename as the
# tie-break. A dry-run receipt describes a model that never touched the
# instance, so it can never authorize a restore.
#
# An unreadable receipt is NOT skipped. Skipping one would silently promote an
# OLDER receipt to authority and roll back the wrong update.
best = None
for candidate in sorted(pathlib.Path(sys.argv[1]).glob("*.json")):
    try:
        receipt = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERR\t{candidate.name} is unreadable: {error}")
        raise SystemExit(0)
    if not isinstance(receipt, dict):
        print(f"ERR\t{candidate.name} is not a receipt object")
        raise SystemExit(0)
    if receipt.get("producer") != "updater" or receipt.get("mode") != "apply":
        continue
    key = (str(receipt.get("created_at") or ""), candidate.name)
    if best is None or key > best[0]:
        best = (key, candidate)
if best is not None:
    print(f"OK\t{best[1]}")
PY
}

# Restore ONLY what the receipt lists, and only while every listed path still
# holds exactly what the updater left there. Reverting the whole sync commit
# would also undo founder edits that landed on those files afterwards, and
# restoring unlisted paths would undo work the updater never made.
receipt_rollback() {
  local path="$1" receipt="$2"
  python3 - "$path" "$receipt" <<'PY'
import hashlib
import json
import pathlib
import re
import subprocess
import sys

instance = pathlib.Path(sys.argv[1]).resolve()
receipt_path = pathlib.Path(sys.argv[2])

REFUSED = 2
BROKEN = 1


def refuse(reason):
    print(f"  REFUSED ({reason})")
    raise SystemExit(REFUSED)


def broken(reason):
    print(f"  FAIL ({reason})")
    raise SystemExit(BROKEN)


try:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    broken(f"unreadable receipt {receipt_path.name}: {error}")
if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
    broken(f"receipt {receipt_path.name} is not a schema_version 1 receipt")

rollback = receipt.get("rollback")
if not isinstance(rollback, dict):
    broken(f"receipt {receipt_path.name} carries no rollback block")
# Ineligibility is answered first so the receipt's own reason reaches the
# operator, before the stricter structural checks below can mask it.
if rollback.get("eligible") is not True:
    refuse(rollback.get("refusal_reason") or "receipt is not rollback-eligible")

HASH = re.compile(r"^[a-f0-9]{64}$")
MODE = re.compile(r"^[0-7]{4}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")

CHANGE_SHAPES = {
    "create": {"operation", "before_sha256", "after_sha256"},
    "update": {"operation", "before_sha256", "after_sha256"},
    "delete": {"operation", "before_sha256", "after_sha256"},
    "mode-change": {"operation", "content_sha256", "before_mode", "after_mode"},
}


def structural(condition, reason):
    # Eligibility is only worth acting on when the whole receipt conforms. A
    # receipt claiming eligible=true beside status=failed is corrupt, not an
    # authorization, so anything off-contract refuses instead of mutating.
    if not condition:
        refuse(f"receipt {receipt_path.name} is off-contract: {reason}")


structural(receipt.get("producer") == "updater", "producer is not the updater")
structural(receipt.get("mode") == "apply", "mode is not apply")
structural(receipt.get("status") == "complete", "status is not complete")
structural(
    isinstance(receipt.get("receipt_id"), str)
    and re.match(r"^ur-[a-f0-9]{16}$", receipt["receipt_id"]) is not None,
    "receipt_id is malformed",
)
structural(rollback.get("refusal_reason") is None, "eligible receipt carries a refusal")
structural(rollback.get("target_receipt_id") is None, "eligible receipt targets another")
structural(
    isinstance(rollback.get("required_head"), str)
    and COMMIT.match(rollback["required_head"]) is not None,
    "required_head is malformed",
)
structural(
    isinstance(rollback.get("required_worktree_sha256"), str)
    and HASH.match(rollback["required_worktree_sha256"]) is not None,
    "required_worktree_sha256 is malformed",
)

before = receipt.get("before")
structural(isinstance(before, dict), "before state is missing")
before_head = before.get("head")
structural(
    isinstance(before_head, str) and COMMIT.match(before_head) is not None,
    "before.head is not a commit to restore from",
)
required_head = rollback["required_head"]
for label, commit in (("before.head", before_head), ("required_head", required_head)):
    if subprocess.run(
        ["git", "-C", str(instance), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
    ).returncode != 0:
        refuse(f"{label} {commit[:8]} is not in this instance")

changes = receipt.get("changes")
structural(isinstance(changes, dict) and bool(changes), "changes is empty")
for name, change in changes.items():
    structural(isinstance(change, dict), f"change for {name} is not an object")
    operation = change.get("operation")
    structural(operation in CHANGE_SHAPES, f"change for {name} has operation {operation!r}")
    structural(
        set(change) == CHANGE_SHAPES[operation],
        f"change for {name} has the wrong fields for {operation}",
    )
    if operation == "mode-change":
        structural(HASH.match(change["content_sha256"] or "") is not None,
                   f"change for {name} has a malformed content hash")
        structural(MODE.match(change["before_mode"] or "") is not None,
                   f"change for {name} has a malformed before_mode")
        structural(MODE.match(change["after_mode"] or "") is not None,
                   f"change for {name} has a malformed after_mode")
        continue
    expected_before = None if operation == "create" else HASH
    expected_after = None if operation == "delete" else HASH
    for field, rule in (("before_sha256", expected_before), ("after_sha256", expected_after)):
        value = change[field]
        if rule is None:
            structural(value is None, f"change for {name} must have a null {field}")
        else:
            structural(
                isinstance(value, str) and rule.match(value) is not None,
                f"change for {name} has a malformed {field}",
            )


def safe_relative(name):
    if not isinstance(name, str) or not name or name.startswith("/"):
        return None
    parts = pathlib.PurePosixPath(name).parts
    if any(part in ("..", ".") for part in parts):
        return None
    return name


def content_hash(candidate):
    return hashlib.sha256(candidate.read_bytes()).hexdigest()


def committed_bytes(commit, name):
    shown = subprocess.run(
        ["git", "-C", str(instance), "show", f"{commit}:{name}"],
        capture_output=True,
    )
    if shown.returncode != 0:
        return None
    return shown.stdout


def committed_mode(commit, name):
    """Git file mode at `commit`, or None when the path is not there.

    Only 100644 and 100755 can be restored byte-for-byte; symlinks and
    submodule links are refused rather than silently rewritten as files.
    """
    listed = subprocess.run(
        ["git", "-C", str(instance), "ls-tree", commit, "--", name],
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0 or not listed.stdout.strip():
        return None
    mode = listed.stdout.split()[0]
    if mode not in ("100644", "100755"):
        refuse(f"{name} is a {mode} entry in {commit[:8]}; rollback handles files only")
    return mode


def is_executable(candidate):
    return bool(candidate.stat().st_mode & 0o111)


# The tracked-dirt guard upstream cannot see an UNTRACKED file sitting at a
# listed path -- a founder who deleted a synced file from git and recreated it
# by hand. Rolling that back would delete their file for good.
listed = sorted(changes)
status = subprocess.run(
    ["git", "-C", str(instance), "status", "--porcelain", "--untracked-files=all", "--"]
    + listed,
    capture_output=True,
    text=True,
)
if status.returncode != 0:
    broken(f"could not read instance status: {status.stderr.strip()}")
if status.stdout.strip():
    refuse(
        "receipt-listed paths carry uncommitted state: "
        + ", ".join(sorted(line[3:] for line in status.stdout.splitlines() if line[3:]))
    )

# Pass one: prove nothing drifted. No file is touched until every listed path
# is confirmed to still hold the updater's own output.
drift = []
for name in sorted(changes):
    relative = safe_relative(name)
    if relative is None:
        refuse(f"receipt lists an unsafe path: {name!r}")
    change = changes[name]
    if not isinstance(change, dict):
        broken(f"receipt change for {name} is not an object")
    operation = change.get("operation")
    candidate = instance / relative
    if operation in ("update", "create"):
        if candidate.is_symlink() or not candidate.is_file():
            drift.append(f"{name} (missing)")
        elif content_hash(candidate) != change.get("after_sha256"):
            drift.append(f"{name} (edited since the update)")
        else:
            # The receipt carries no mode for update/create, so the tree the
            # updater actually left (required_head) is the mode reference.
            left_mode = committed_mode(required_head, relative)
            if left_mode is None:
                drift.append(f"{name} (not in the post-update commit)")
            elif is_executable(candidate) != (left_mode == "100755"):
                drift.append(f"{name} (mode changed since the update)")
    elif operation == "delete":
        if candidate.exists():
            drift.append(f"{name} (recreated since the update)")
    elif operation == "mode-change":
        if not candidate.is_file():
            drift.append(f"{name} (missing)")
        else:
            mode = f"{candidate.stat().st_mode & 0o7777:04o}"
            if mode != change.get("after_mode"):
                drift.append(f"{name} (mode changed since the update)")
            elif content_hash(candidate) != change.get("content_sha256"):
                drift.append(f"{name} (edited since the update)")
    else:
        broken(f"receipt change for {name} has unknown operation {operation!r}")

if drift:
    refuse("later edits on receipt-listed paths: " + ", ".join(drift))

# Pass two: resolve every byte and mode the restore will write, and verify each
# against the receipt, BEFORE touching the worktree. A refusal discovered
# halfway through a mutating loop is a half-rolled-back instance.
plan = []
for name in sorted(changes):
    change = changes[name]
    operation = change["operation"]
    candidate = instance / name
    if operation == "create":
        plan.append((name, candidate, "remove", None, None))
        continue
    if operation == "mode-change":
        # A mode-change receipt is only trustworthy if git agrees with both of
        # its ends; otherwise its before_mode would be applied on faith.
        for commit, label, claimed in (
            (before_head, "before.head", change["before_mode"]),
            (required_head, "required_head", change["after_mode"]),
        ):
            recorded = committed_mode(commit, name)
            if recorded is None:
                refuse(f"{name} is not in {label} {commit[:8]}")
            if (recorded == "100755") != bool(int(claimed, 8) & 0o111):
                refuse(f"{name} mode {claimed} disagrees with {label} {commit[:8]}")
        blob = committed_bytes(before_head, name)
        if blob is None or hashlib.sha256(blob).hexdigest() != change["content_sha256"]:
            refuse(f"{name} content in {before_head[:8]} does not match the receipt hash")
        plan.append((name, candidate, "chmod", None, int(change["before_mode"], 8)))
        continue
    payload = committed_bytes(before_head, name)
    if payload is None:
        refuse(f"{name} is not in pre-update commit {before_head[:8]}")
    if hashlib.sha256(payload).hexdigest() != change["before_sha256"]:
        refuse(f"{name} in {before_head[:8]} does not match the receipt hash")
    original_mode = committed_mode(before_head, name)
    if original_mode is None:
        refuse(f"{name} has no file mode in {before_head[:8]}")
    # Git only records the executable bit. Forcing a full 0644/0755 would bury a
    # founder's own permission choice (0600, say), so keep the current
    # permission bits and restore only the bit git actually tracked.
    executable = original_mode == "100755"
    if candidate.is_file():
        base = candidate.stat().st_mode & 0o7777
    else:
        base = 0o644
    target_mode = (base & ~0o111) | (0o111 if executable else 0)
    plan.append((name, candidate, "write", payload, target_mode))

# Pass three: mutate, remembering enough to put every touched path back if the
# stage or the commit fails. A rollback that dies mid-write is worse than one
# that never started.
undo = []
restored = []


def unwind():
    for candidate, existed, payload, mode in reversed(undo):
        if not existed:
            if candidate.exists():
                candidate.unlink()
            continue
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(payload)
        candidate.chmod(mode)


try:
    for name, candidate, action, payload, mode in plan:
        existed = candidate.is_file()
        undo.append(
            (
                candidate,
                existed,
                candidate.read_bytes() if existed else b"",
                candidate.stat().st_mode & 0o7777 if existed else 0o644,
            )
        )
        if action == "remove":
            candidate.unlink()
        elif action == "chmod":
            candidate.chmod(mode)
        else:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(payload)
            candidate.chmod(mode)
        restored.append(name)

    staged = subprocess.run(
        ["git", "-C", str(instance), "add", "--"] + restored, capture_output=True
    )
    if staged.returncode != 0:
        raise RuntimeError(
            f"could not stage the restore: {staged.stderr.decode(errors='replace')}"
        )
    message = f"chore: roll back skeleton sync {receipt['receipt_id']}"
    committed = subprocess.run(
        ["git", "-C", str(instance), "commit", "-m", message], capture_output=True
    )
    if committed.returncode != 0:
        raise RuntimeError(
            f"could not commit the restore: {committed.stderr.decode(errors='replace')}"
        )
except Exception as error:  # noqa: BLE001 -- any failure must leave no partial state
    unwind()
    if restored:
        unstaged = subprocess.run(
            ["git", "-C", str(instance), "reset", "-q", "--"] + restored,
            capture_output=True,
        )
        if unstaged.returncode != 0:
            # Claiming "left as it was" while the index still holds the restore
            # would be the lie that hides a half-rolled-back instance.
            broken(
                f"{error}; AND the index could not be reset -- "
                f"{len(restored)} path(s) are still staged: "
                f"{unstaged.stderr.decode(errors='replace').strip()}"
            )
    broken(f"{error}; instance left as it was")

print(f"  ROLLED BACK ({len(restored)} receipt-listed path(s) from {before_head[:8]})")
PY
}

rollback_one() {
  local name="$1" path="$2" itype="${3:-subtree}"
  echo "--- $name ---"
  if [ ! -d "$path/.git" ]; then
    echo "  SKIP (not a git repo / path missing: $path)"; SKIP=$((SKIP+1)); return 0
  fi
  local receipt_line receipt
  receipt_line="$(latest_receipt "$path")"
  case "$receipt_line" in
    ERR*)
      echo "  REFUSED (updater receipt store is damaged: ${receipt_line#ERR	})"
      FAIL=$((FAIL+1)); return 0
      ;;
  esac
  receipt="${receipt_line#OK	}"
  [ "$receipt" = "$receipt_line" ] && receipt=""
  if [ -n "$receipt" ]; then
    # A receipt-driven rollback was explicitly requested and cannot be honored,
    # so it REFUSES (non-zero) rather than reporting a quiet skip-and-success.
    if ! git -C "$path" diff --quiet 2>/dev/null ||
        ! git -C "$path" diff --cached --quiet 2>/dev/null; then
      echo "  REFUSED (dirty working tree -- commit or stash first; refusing to restore over uncommitted work)"
      FAIL=$((FAIL+1)); return 0
    fi
    local rc=0
    receipt_rollback "$path" "$receipt" || rc=$?
    if [ "$rc" -eq 0 ]; then
      PASS=$((PASS+1))
    else
      FAIL=$((FAIL+1))
    fi
    return 0
  fi
  # most recent sync commit by message-prefix -- NOT HEAD
  local sync_sha
  sync_sha="$(git -C "$path" log --grep="$SYNC_PREFIX" --format=%H -n 1 2>/dev/null || true)"
  if [ -z "$sync_sha" ]; then
    if [ "$itype" = "direct-clone" ]; then
      echo "  SKIP (direct-clone: syncs via git pull from origin, no local sync commit -- roll back with git inside the instance)"
    else
      echo "  SKIP (no skeleton-sync commit to roll back)"
    fi
    SKIP=$((SKIP+1)); return 0
  fi
  # refuse over uncommitted work (tracked changes, staged or unstaged)
  if ! git -C "$path" diff --quiet 2>/dev/null || ! git -C "$path" diff --cached --quiet 2>/dev/null; then
    echo "  SKIP (dirty working tree -- commit or stash first; refusing to revert over uncommitted work)"
    SKIP=$((SKIP+1)); return 0
  fi
  local short
  short="$(git -C "$path" rev-parse --short "$sync_sha")"
  if git -C "$path" revert --no-edit "$sync_sha" >/dev/null 2>&1; then
    echo "  ROLLED BACK (reverted sync $short)"; PASS=$((PASS+1))
  else
    git -C "$path" revert --abort >/dev/null 2>&1 || true
    echo "  FAIL (revert of $short conflicted; aborted cleanly, instance left untouched)"; FAIL=$((FAIL+1))
  fi
}

while IFS='|' read -r name path itype; do
  [ -z "$name" ] && continue
  if [ -n "$ONLY" ] && [ "$name" != "$ONLY" ]; then continue; fi
  rollback_one "$name" "$path" "$itype"
  echo ""
done < <(python3 -c "
import json
d = json.load(open('$REGISTRY'))
for i in d['instances']:
    if 'status' in i and i['status'].startswith('merged'):
        continue
    print(i['name'] + '|' + i['path'] + '|' + i.get('type', 'subtree'))
")

if [ "$((PASS+SKIP+FAIL))" -eq 0 ]; then
  if [ -n "$ONLY" ]; then
    echo "No registered instance named '$ONLY'." >&2
    exit 1
  fi
  echo "No eligible instances in the registry."
  exit 0
fi

echo "=== Rollback Summary ==="
echo "  Rolled back: $PASS"
echo "  Skipped:     $SKIP"
echo "  Failed:      $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
