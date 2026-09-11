#!/usr/bin/env python3
"""Open-loops surfacer: nothing parked falls on the ground. (AUDHD anti-drop.)

Why this exists: deferred / half-baked / waiting-on-external items left as prose
in a ledger get forgotten. This reads the explicit registry
(q-system/memory/open-loops.json) plus any genuinely-deferred prd-os findings and
re-surfaces them EVERY SessionStart via additionalContext, so doing nothing keeps
them in view instead of letting them rot. The agent relays them to the founder.

Two modes:
  - hook mode (no args): emit {"hookSpecificOutput": {...additionalContext...}} for SessionStart.
  - `--report`:  print a plain checklist for a human to read on demand.

Discipline this enforces: a parked item is an entry in open-loops.json, never a
prose "deferred / your call later" line. Close a loop by setting status:"closed".

Fail-closed + never-blocks: any error -> emit nothing, exit 0. stdlib only.
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CAP = 25

# A deferred prd-os finding is a GENUINE open loop (not closeout bookkeeping) when
# its rationale points at real future work and is NOT "folded into" an issue.
FUTURE_WORK_RE = re.compile(r"\b(v2|v3|phase\s*2|phase\s*3|revisit|backlog|deferred to|once .+ exists|when .+ )", re.IGNORECASE)
FOLDED_RE = re.compile(r"folded into|refinement, not a standalone|confirmation, no defect", re.IGNORECASE)

# A rationale that NAMES its owner ("folded into ASK-419", "owned by
# prd-foo-2026-08-14") is not a keyword guess: the named row's STATE is the
# answer. Before ASK-759 these fell to FUTURE_WORK_RE keyword luck and mostly
# landed in the "N not auto-classified" bucket, which no action can clear
# (sp-30a109ad, hit 2026-07-27 on findings 3/7/9). Pointer resolution runs BEFORE
# FOLDED_RE on purpose: "folded into <open issue>" is a live loop, not bookkeeping.
POINTER_RE = re.compile(r"\b(ASK-\d+|prd-[a-z0-9][a-z0-9-]*-\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)

# Same terminal vocabulary prd_runner.py uses for a spec (`_TERMINAL_SPEC_STATES`).
TERMINAL_STATES = frozenset({"archived", "closed", "cancelled", "canceled", "done", "abandoned"})

# Bounds on the report-mode cache refresh. Hook mode never refreshes at all.
REFRESH_ID_CAP = 10
REFRESH_TIMEOUT_SECONDS = 8

# A cached Linear state is a snapshot, not a fact -- an issue closes, or a closed
# one is REOPENED, and the cache keeps answering with whatever it saw first. So a
# record expires: past this age it is unresolvable (offline) and a refresh
# candidate (report mode). Both halves are needed. Expiring alone would strand
# every id in the catch-all; re-asking alone would keep serving a wrong answer
# until the refresh happened to run. A day is short enough that a reopened issue
# resurfaces within one heartbeat and long enough that an ordinary session never
# waits on the network. An undated record (the pre-ASK-759 shape) has no provable
# age, so it is stale: the failure direction of trusting it is a silent drop.
CACHE_TTL = timedelta(days=1)


def get_qroot(project_dir):
    nested = Path(project_dir) / "q-system" / "q-system" / "canonical"
    if nested.exists():
        return Path(project_dir) / "q-system" / "q-system"
    return Path(project_dir) / "q-system"


def project_root():
    pd = os.environ.get("CLAUDE_PROJECT_DIR")
    if pd:
        return Path(pd)
    # CLI fallback: this file is q-system/.q-system/scripts/open-loops.py
    return Path(__file__).resolve().parents[3]


def registry_loops(qroot):
    path = qroot / "memory" / "open-loops.json"
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    out = []
    for loop in data.get("loops", []):
        if str(loop.get("status", "open")).lower() == "closed":
            continue
        title = (loop.get("title") or "").strip()
        action = (loop.get("next_action") or "").strip()
        if not title:
            continue
        out.append((title, action, bool(loop.get("needs_founder"))))
    return out


def ledger_root(repo_root):
    """Directory holding the ONE spillover ledger, shared by every worktree.

    Mirrors prd_runner.py `_ledger_root`: `.gitignore` excludes `*.jsonl`, so the
    ledger never travels through git and a per-worktree root gives each worktree a
    private copy. Resolving it any other way here would make this script blind to
    captures the gate can see -- the same load-path mistake as the marketplace clone.
    Fails open to repo_root (a missed skip only over-surfaces; it never drops).
    """
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                             cwd=str(repo_root), capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            common = Path(out.stdout.strip())
            if not common.is_absolute():
                common = Path(repo_root) / common
            parent = common.resolve().parent
            if (parent / ".git").exists():
                return parent
    except Exception:
        pass
    return repo_root


def captured_finding_ids(repo_root):
    """Set of `defer-<prd-slug>-<finding-id>` ids the spillover ledger already holds.

    A `deferred` disposition AUTO-creates a spillover item (no-orphan-findings.md),
    and `gates run` stays RED until that item resolves. So a captured finding is
    TRACKED, not in limbo, whether its item is still open or already resolved --
    counting it in the catch-all below re-reported tracked work as untracked at
    every SessionStart (2026-08-14: 3 deterministic-reading findings nagged for
    weeks, 2 of them already RESOLVED). Reading is enough; this never writes.
    """
    ids = set()
    path = ledger_root(repo_root) / ".prd-os" / "spillover.jsonl"
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return ids  # no ledger -> nothing is captured -> count everything (fail open)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        rid = str(rec.get("id") or "")
        if rid.startswith("defer-"):
            ids.add(rid)
    return ids


def find_pointer(rationale):
    """The tracker id a rationale names, or None. First match wins."""
    match = POINTER_RE.search(rationale or "")
    return match.group(1) if match else None


def prd_pointer_state(repo_root, prd_id):
    """'closed' | 'open' | None for a `prd-<slug>-<date>` pointer.

    Reads the spec's `status:` frontmatter -- existing data, no network. None
    means UNRESOLVABLE (no spec on disk, unreadable, or no status line), which
    the caller must treat as "keep counting it", never as "closed".
    """
    path = Path(repo_root) / ".prd-os" / "prds" / (prd_id.lower() + ".md")
    try:
        lines = path.read_text().splitlines()
    except Exception:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("status:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'").lower()
            return "closed" if value in TERMINAL_STATES else "open"
    return None


def linear_cache_path(qroot):
    return Path(qroot) / "output" / "linear-issue-cache.json"


def _read_linear_cache(qroot):
    """{ISSUE-ID: {'state': ..., 'fetched_at': ...}} exactly as stored, no filtering.

    The raw view exists so the writer can preserve records it did not refresh
    (with their original stamps) instead of re-dating them by round-tripping
    through the fresh-only view.
    """
    try:
        data = json.loads(linear_cache_path(qroot).read_text())
    except Exception:
        return {}
    raw = {}
    for issue_id, record in (data.get("issues") or {}).items():
        if isinstance(record, dict):
            raw[str(issue_id).upper()] = record
    return raw


def _is_fresh(record, now):
    """True only if the record carries a parseable stamp newer than CACHE_TTL."""
    stamp = str((record or {}).get("fetched_at", "")).strip()
    if not stamp:
        return False  # undated -> no provable age -> stale (never trusted forever)
    try:
        fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return now - fetched <= CACHE_TTL


def linear_pointer_states(qroot):
    """{issue-id: 'open'|'closed'} for FRESH cache records only. NEVER a network call.

    open-loops.py runs as a SessionStart hook, so a live Linear lookup here would
    put an API round-trip in front of every session. The cache is the offline
    half; `refresh_linear_cache` (report mode only) is the online half. A missing,
    junk, or EXPIRED record yields no entry -> that Linear pointer is unresolvable
    -> the finding stays counted. Failing open is the whole point: a lookup miss,
    or an answer too old to trust, must never silently drop a parked item.
    """
    now = datetime.now(timezone.utc)
    states = {}
    for issue_id, record in _read_linear_cache(qroot).items():
        state = str(record.get("state", "")).lower()
        if state in ("open", "closed") and _is_fresh(record, now):
            states[issue_id] = state
    return states


def pointer_state(pointer, repo_root, linear_states):
    """'closed' | 'open' | None (unresolvable) for one pointer id."""
    if pointer.upper().startswith("ASK-"):
        return linear_states.get(pointer.upper())
    return prd_pointer_state(repo_root, pointer)


def _fetch_linear_states(issue_ids):
    """One Linear query for the given ids -> {id: 'open'|'closed'}. Raises on failure."""
    import importlib.util

    sync_path = Path(__file__).resolve().parent / "linear-sync.py"
    spec = importlib.util.spec_from_file_location("_open_loops_linear_sync", sync_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    query = "query($id:String!){ issue(id:$id){ identifier state{ type } } }"
    states = {}
    for issue_id in issue_ids:
        issue = (module.graphql(query, {"id": issue_id}) or {}).get("issue") or {}
        state_type = str((issue.get("state") or {}).get("type", "")).lower()
        if state_type:
            states[issue_id] = "closed" if state_type in ("completed", "canceled") else "open"
    return states


def refresh_linear_cache(qroot, pointers):
    """Report mode ONLY: top the cache up for pointers it cannot FRESHLY answer.

    "Cannot freshly answer" is the same test `linear_pointer_states` applies, on
    purpose and via the same function: whatever the offline half refuses to trust
    is exactly what the online half must re-ask. Skipping every id already present
    (the pre-fix rule) made an id's first answer its last one forever, so a closed
    issue kept alerting and a REOPENED one stayed silently dropped.

    Bounded three ways so a human running `--report` can never be parked on it:
    at most REFRESH_ID_CAP ids, a hard REFRESH_TIMEOUT_SECONDS wall via a daemon
    thread the caller abandons, and `KIPI_OPEN_LOOPS_OFFLINE=1` to switch it off
    entirely (the test suite pins that on). Any failure leaves the cache untouched,
    so the worst case is the pre-existing behaviour: unresolvable -> still counted.
    """
    if os.environ.get("KIPI_OPEN_LOOPS_OFFLINE") == "1":
        return
    raw = _read_linear_cache(qroot)
    fresh = linear_pointer_states(qroot)
    candidates = {p.upper() for p in pointers
                  if p.upper().startswith("ASK-") and p.upper() not in fresh}
    # Oldest answer first, so the cap rotates through a long backlog instead of
    # re-asking the alphabetically-first ten every run. Never-seen ids sort first.
    wanted = sorted(candidates,
                    key=lambda i: (str(raw.get(i, {}).get("fetched_at", "")), i))[:REFRESH_ID_CAP]
    if not wanted:
        return
    import threading

    fetched = {}
    worker = threading.Thread(target=lambda: fetched.update(_swallow(_fetch_linear_states, wanted)),
                              daemon=True)
    worker.start()
    worker.join(REFRESH_TIMEOUT_SECONDS)
    if worker.is_alive() or not fetched:
        return  # timed out or nothing came back -> leave the cache exactly as it was
    _write_linear_cache(qroot, raw, fetched)


def _swallow(fn, arg):
    try:
        return fn(arg)
    except Exception:
        return {}


def _write_linear_cache(qroot, raw, fetched):
    """Stamp what was just fetched; carry everything else through untouched.

    Only a record this run actually re-asked gets today's `fetched_at`. Re-dating
    a record the run never verified would launder a stale answer into a fresh one,
    which is the defect this whole path exists to close.
    """
    stamped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = {k: dict(v) for k, v in raw.items()}
    for issue_id, state in fetched.items():
        merged[issue_id.upper()] = {"state": state, "fetched_at": stamped_at}
    path = linear_cache_path(qroot)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"issues": dict(sorted(merged.items()))}, indent=2))
    except Exception:
        pass  # a cache we cannot write is a cache we do without


def pointers_in_findings(repo_root):
    """Every pointer id named by a still-uncaptured deferred finding."""
    found = set()
    for _, rationale in _deferred_rows(repo_root):
        pointer = find_pointer(rationale)
        if pointer:
            found.add(pointer)
    return found


def _deferred_rows(repo_root):
    """Yields (record, rationale) for each deferred, not-yet-captured finding."""
    captured = captured_finding_ids(repo_root)
    for jsonl_file in sorted(glob.glob(str(repo_root / ".prd-os" / "findings" / "*.jsonl"))):
        name = Path(jsonl_file).name
        prd_slug = name[: -len("-findings.jsonl")] if name.endswith("-findings.jsonl") else Path(jsonl_file).stem
        try:
            lines = Path(jsonl_file).read_text().splitlines()
        except Exception:
            continue
        for line in lines:
            record = _parse_deferred(line)
            if record is None:
                continue
            if f"defer-{prd_slug}-{record.get('id')}" in captured:
                continue  # the spillover ledger owns it; `gates run` is its enforcer
            rationale = (record.get("rationale") or "").strip()
            if rationale:
                yield record, rationale


def _parse_deferred(line):
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except Exception:
        return None
    if str(record.get("disposition", "")).lower() != "deferred":
        return None
    return record


def deferred_findings(repo_root, qroot=None):
    """Returns (surfaced, unclassified). surfaced = genuine future-work deferrals
    plus pointer-style deferrals whose named owner is still OPEN.
    unclassified = deferred + not resolved by a pointer + not closeout-bookkeeping
    + not keyword-matched + not already captured in the spillover ledger: COUNTED
    (never silently dropped) so a plainly-worded parked finding can't fall on the
    ground."""
    out = []
    seen = set()
    unclassified = 0
    linear_states = linear_pointer_states(qroot) if qroot else {}
    for record, rationale in _deferred_rows(repo_root):
        body = (record.get("body") or record.get("id") or "deferred item").strip()
        verdict, action = _classify(rationale, repo_root, linear_states)
        if verdict == "drop":
            continue
        if verdict == "count":
            unclassified += 1
            continue
        key = body[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append((body[:80], action, False))
    return out, unclassified


def _classify(rationale, repo_root, linear_states):
    """('drop'|'count'|'surface', action-text). Pointer resolution outranks keywords."""
    pointer = find_pointer(rationale)
    if pointer:
        state = pointer_state(pointer, repo_root, linear_states)
        if state == "closed":
            return "drop", ""  # owner is done; re-reporting it is the nag
        if state == "open":
            return "surface", f"owner {pointer} is still OPEN -- {rationale[:100]}"
        return "count", ""  # unresolvable -> fail open, keep it visible
    if FOLDED_RE.search(rationale):
        return "drop", ""  # closeout bookkeeping -> genuinely closed
    if FUTURE_WORK_RE.search(rationale):
        return "surface", rationale[:120]
    return "count", ""


def collect(project_dir, allow_refresh=False):
    repo = project_root()
    qroot = get_qroot(str(repo))  # anchor registry + findings to the same root (CLI-safe)
    loops = registry_loops(qroot)
    if allow_refresh:
        refresh_linear_cache(qroot, pointers_in_findings(repo))
    fnd, unclassified = deferred_findings(repo, qroot)
    loops += fnd
    return loops[:CAP], unclassified


def render(loops, unclassified=0):
    n = len(loops) + (1 if unclassified else 0)
    head = (f"# Open loops ({n}) -- surface these to the founder now. Nothing parked "
            f"falls on the ground.\n"
            f"# Close one: set status:\"closed\" in q-system/memory/open-loops.json.\n")
    lines = [head]
    for title, action, needs_founder in loops:
        tag = " [needs you]" if needs_founder else ""
        lines.append(f"- [ ] {title}{tag} -> {action}")
    if unclassified:
        lines.append(f"- [ ] {unclassified} deferred prd-os finding(s) not auto-classified "
                     f"-> review rationale in .prd-os/findings/ and either close (won't-do) or "
                     f"add to open-loops.json (so nothing stays in limbo)")
    return "\n".join(lines)


def main():
    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        report_mode = "--report" in sys.argv[1:]
        # Refresh is report-mode only: a human asked, so a bounded call is fair.
        # SessionStart gets the cache as-is and never waits on the network.
        loops, unclassified = collect(project_dir, allow_refresh=report_mode)
        if not loops and not unclassified:
            if report_mode:
                print("No open loops. Clean.")
            sys.exit(0)
        body = render(loops, unclassified)
        if report_mode:
            print(body)
        else:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart", "additionalContext": body}}))
        sys.exit(0)
    except Exception:
        sys.exit(0)  # never block session start


if __name__ == "__main__":
    main()
