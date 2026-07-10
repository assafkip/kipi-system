#!/usr/bin/env python3
"""publish_gate.py — PreToolUse gate: no un-converged design-room page publishes.

Postmortem DR-2026-07-04-01: the rejected deliverable escaped as an Artifact, a
surface no hook watched. PRD-A's executor records a `convergence-lead-last` receipt
in <project>/design-room/run-state.json when the Phase-6 gate clears; this hook is
the pre-publish enforcement that READS that receipt. It fires PreToolUse on the
three agent-invocable publish surfaces (Artifact, SendUserFile, Vercel deploy) and
BLOCKS (exit 2) when a design-room deliverable is being published without a
chain-valid convergence receipt.

Fail closed on every ambiguity (the incident was a fail-OPEN publish): unmappable
path, missing run-state, broken receipt chain, an unreadable deploy target, or the
enforcement core failing to import all block. Non-design-room payloads pass (exit 0)
— general public HTML is the dogfood gate's job, not this hook's.

Chain integrity is not re-implemented here: the hook imports
design_room_run._verify_chain (one source of truth). Pairs with the design-room
executor (skill-hook-pairing). Exit 0 = allow, exit 2 = block.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# plugins/kipi-design/hooks/publish_gate.py -> repo root is 3 parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]
GTM_SCRIPTS = REPO_ROOT / "gtm" / "scripts"

CONVERGENCE_STAGE = "convergence-lead-last"
PUBLISH_TOOLS = ("Artifact", "SendUserFile")
DEPLOY_TOOL_SUBSTR = "deploy_to_vercel"
# Vercel deploy input path fields (pinned; a test asserts this list). A deploy
# whose target resolves to none of these is UNMAPPABLE and fails closed.
DEPLOY_PATH_KEYS = ("cwd", "path", "root", "dir", "project_path", "projectPath")
# Path-bearing keys inspected on a SendUserFile dict element — ALL of them, not
# the first truthy (a mixed element could hide the design-room path behind a
# non-design one; codex-review finding on this issue).
FILE_ELEMENT_KEYS = ("path", "file_path", "filepath", "src")


def _forms(p: str) -> tuple[Path, Path] | None:
    """Two forms of a candidate: (lexical-absolute WITHOUT symlink resolution,
    fully resolved). Both are checked for a design-room ancestor so a symlink in
    EITHER direction (a design-room page symlinked out, or a symlinked design-room
    dir) is still recognized (codex-review blocker: resolving first hid the
    design-room ancestor of a symlinked page and failed open)."""
    try:
        expanded = os.path.expanduser(p)
        lexical = Path(os.path.abspath(expanded))  # abspath does NOT follow symlinks
        resolved = Path(expanded).resolve()
        return lexical, resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve(p: str) -> Path | None:
    try:
        return Path(p).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _candidates(tool_name: str, ti: dict) -> tuple[list[tuple[Path, Path]], bool]:
    """Return (candidate (lexical, resolved) pairs, unmappable_deploy). A deploy
    with no resolvable target sets unmappable_deploy=True (fail closed)."""
    raw: list[str] = []
    unmappable_deploy = False
    if tool_name == "Artifact":
        fp = ti.get("file_path")
        if isinstance(fp, str) and fp:
            raw.append(fp)
    elif tool_name == "SendUserFile":
        for el in ti.get("files") or []:
            if isinstance(el, str) and el:
                raw.append(el)
            elif isinstance(el, dict):
                for k in FILE_ELEMENT_KEYS:
                    v = el.get(k)
                    if isinstance(v, str) and v:
                        raw.append(v)  # ALL path-bearing keys, not the first
    elif DEPLOY_TOOL_SUBSTR in tool_name:
        found = False
        for k in DEPLOY_PATH_KEYS:
            v = ti.get(k)
            if isinstance(v, str) and v:
                raw.append(v)
                found = True
        if not found:
            unmappable_deploy = True
    forms = [f for f in (_forms(r) for r in raw) if f is not None]
    return forms, unmappable_deploy


def _design_room_dir(path: Path) -> Path | None:
    """Nearest `design-room` ancestor dir of a path (or the path itself)."""
    for anc in [path, *path.parents]:
        if anc.name == "design-room":
            return anc
    return None


def _block(msg: str) -> int:
    sys.stderr.write("PUBLISH BLOCKED (design-room): " + msg + "\n")
    return 2


def _recorded_built_html_hash(state: dict, graph) -> str | None:
    """The sha256 the run recorded for built_html at build time (schema v2
    produced_hashes, sp-7bcd3b43), or None if no receipt carries one (a legacy
    pre-content-binding run). Read from the stage that PRODUCES built_html, so a
    receipt from another stage cannot stand in."""
    producer = next((s.id for s in graph.stages if "built_html" in s.produces), None)
    for rec in state.get("receipts", []):
        if rec.get("kind") != "stage":
            continue
        if producer is not None and rec.get("stage") != producer:
            continue
        ph = rec.get("produced_hashes")
        if isinstance(ph, dict) and isinstance(ph.get("built_html"), str) and ph["built_html"]:
            return ph["built_html"]
    return None


def _check_run(dr_dir: Path, published: Path) -> int:
    """0 = allow, 2 = block. Fail closed on anything unproven."""
    run_state_path = dr_dir / "run-state.json"
    if not run_state_path.is_file():
        return _block(
            f"{published} is under {dr_dir} but there is no run-state.json — an "
            "un-tracked design page has no convergence proof. Run it through "
            "design_room_run.py start ... advance convergence-lead-last."
        )
    if str(GTM_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(GTM_SCRIPTS))
    try:
        import design_room_pipeline
        import design_room_run
    except Exception as exc:  # enforcement core unavailable -> fail closed
        return _block(f"cannot import the design-room executor ({exc}); refusing to "
                      "publish without a verifiable convergence receipt")
    try:
        state = json.loads(run_state_path.read_text())
        graph = design_room_pipeline.load()
        view = design_room_run._verify_chain(state, graph)
    except Exception as exc:
        return _block(f"run-state receipt chain did not verify ({exc}) — refusing to "
                      "publish a run whose provenance is broken")
    if CONVERGENCE_STAGE not in view["stage_done"]:
        return _block(
            f"run {dr_dir} has no `{CONVERGENCE_STAGE}` receipt — the Phase-6 gate "
            "has not cleared. Run `design_room_run.py advance convergence-lead-last "
            f"{dr_dir.parent}` before publishing."
        )
    built = state.get("built_html")
    if not isinstance(built, str) or not built:
        return _block(f"run {dr_dir} converged but records no built_html to bind the "
                      "publish to")
    built_resolved = _resolve(str(dr_dir / built))
    if built_resolved != published:
        return _block(
            f"the file being published ({published}) is not this run's converged build "
            f"({built_resolved}). Publish the built_html the run converged, not a "
            "different or stale file."
        )
    # Content binding (sp-7bcd3b43): the published PATH is right; now prove its
    # BYTES are the ones the run converged. Recompute the file's hash and bind it to
    # the produced_hash the run recorded for built_html. A post-convergence hand-edit
    # of the built page changes the bytes -> mismatch -> block (path alone missed it).
    recorded = _recorded_built_html_hash(state, graph)
    if recorded is None:
        # New field reaching the writer but not a reader must FAIL CLOSED (PRD
        # finding-1): a legacy receipt with no produced_hash cannot prove content
        # integrity, so refuse rather than fall back to the old path-only pass.
        return _block(
            f"run {dr_dir} converged but records no produced-hash for built_html "
            "(a legacy pre-content-binding receipt) — cannot prove the published bytes "
            "are the converged build. Re-run through design_room_run.py so the build "
            "receipt records produced_hashes."
        )
    try:
        current = hashlib.sha256(published.read_bytes()).hexdigest()
    except OSError as exc:
        return _block(f"cannot read {published} to verify its content hash ({exc})")
    if current != recorded:
        return _block(
            f"{published} has changed since convergence (content hash {current[:12]} != "
            f"the converged {recorded[:12]}). A post-convergence hand-edit does not "
            "publish — re-run convergence on the edited page."
        )
    return 0


def evaluate(tool_name: str, ti: dict) -> int:
    candidates, unmappable_deploy = _candidates(tool_name, ti)

    # A candidate is design-room if EITHER form (lexical or resolved) has a
    # design-room ancestor — closes the symlink fail-open in both directions.
    design_runs: list[tuple[Path, Path]] = []  # (published_resolved, design_room_dir)
    for lexical, resolved in candidates:
        dr = _design_room_dir(lexical) or _design_room_dir(resolved)
        if dr is not None:
            design_runs.append((resolved, dr))

    if not design_runs:
        if unmappable_deploy:
            return _block(
                "a Vercel deploy was requested but its target directory could not be "
                f"resolved from any of {DEPLOY_PATH_KEYS}; refusing to deploy a target "
                "that may be an un-converged design-room build. Pass the deploy dir "
                "explicitly."
            )
        return 0  # not a design-room publish — the dogfood gate handles public HTML

    for published, dr_dir in design_runs:
        rc = _check_run(dr_dir, published)
        if rc != 0:
            return rc
    return 0


def _selftest() -> int:
    import tempfile
    sys.path.insert(0, str(GTM_SCRIPTS))
    import design_room_pipeline
    import design_room_run as drr
    graph = design_room_pipeline.load()
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "proj"
        (proj / "design-room" / "build").mkdir(parents=True)
        page = proj / "design-room" / "build" / "index.html"
        page.write_text("<html><body>x</body></html>")

        built_producer = next((s.id for s in graph.stages
                                if "built_html" in s.produces), "build")

        def write_state(stages, built="build/index.html", record_hash=True):
            genesis = {"project": str(proj), "created_at": "2026-07-05T00:00:00+00:00",
                       "runner_version": "1.0"}
            state = {f: None for f in graph.run_state_artifacts}
            state["project"] = str(proj)
            state["genesis"] = genesis
            state["receipts"] = []
            prev = drr._hash(genesis)
            if built is not None:
                rec = {"kind": "record", "field": "built_html", "value": built,
                       "at": "t", "prev": prev}
                state["receipts"].append(rec); state["built_html"] = built
                prev = drr._hash(rec)
            built_path = proj / "design-room" / built if built else None
            for st in stages:
                rec = {"kind": "stage", "stage": st, "checkers": [], "exit": 0,
                       "at": "t", "prev": prev}
                # the build stage records the produced-hash of built_html (schema v2)
                if st == built_producer and record_hash and built_path and built_path.is_file():
                    rec["produced_hashes"] = {
                        "built_html": hashlib.sha256(built_path.read_bytes()).hexdigest()}
                state["receipts"].append(rec); prev = drr._hash(rec)
            (proj / "design-room" / "run-state.json").write_text(json.dumps(state))

        art = lambda: {"file_path": str(page)}
        converged = ["runtime-contract", built_producer, "convergence-lead-last"]
        write_state(["runtime-contract", built_producer])
        checks.append(("unconverged blocked", evaluate("Artifact", art()) == 2))
        write_state(converged)
        checks.append(("converged allowed", evaluate("Artifact", art()) == 0))
        # post-convergence hand-edit of the built page -> content hash mismatch -> block
        page.write_text("<html><body>TAMPERED</body></html>")
        checks.append(("post-convergence edit blocked", evaluate("Artifact", art()) == 2))
        page.write_text("<html><body>x</body></html>")  # restore
        # a converged run whose receipt carries NO produced_hash (legacy) fails closed
        write_state(converged, record_hash=False)
        checks.append(("legacy no-hash receipt blocked", evaluate("Artifact", art()) == 2))
        write_state(converged)  # back to a clean converged state
        checks.append(("non-design passes",
                       evaluate("Artifact", {"file_path": str(Path(td) / "r.html")}) == 0))
        checks.append(("unmappable deploy blocked",
                       evaluate("mcp__plugin_vercel_vercel__deploy_to_vercel", {}) == 2))
        (proj / "design-room" / "run-state.json").unlink()
        checks.append(("untracked blocked", evaluate("Artifact", art()) == 2))

    failed = [n for n, ok in checks if not ok]
    if failed:
        sys.stderr.write("SELFTEST FAILED: " + "; ".join(failed) + "\n")
        return 2
    print(f"SELFTEST OK - {len(checks)} checks: unconverged/untracked/unmappable-deploy/"
          "post-convergence-edit/legacy-no-hash block; converged + non-design pass")
    return 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return _selftest()
    try:
        data = json.load(sys.stdin)
    except Exception:
        # This hook is registered ONLY for publish surfaces, so an invocation IS a
        # publish call. Unparseable input means we cannot prove the payload is not
        # an un-converged design-room page -> fail closed (codex-review finding:
        # the fail-closed-on-ambiguity contract must cover malformed input too).
        return _block("publish tool call could not be parsed; refusing to publish "
                      "without being able to check design-room convergence")
    if not isinstance(data, dict):
        return _block("publish tool payload is not an object; fail closed")
    tool_name = data.get("tool_name") or data.get("tool") or ""
    is_publish = tool_name in PUBLISH_TOOLS or DEPLOY_TOOL_SUBSTR in tool_name
    if not is_publish:
        # Routed here but not a recognized publish tool name — not ours to judge.
        return 0
    ti = data.get("tool_input")
    if not isinstance(ti, dict):
        return _block(f"{tool_name} call has no readable tool_input; fail closed")
    return evaluate(tool_name, ti)


if __name__ == "__main__":
    raise SystemExit(main())
