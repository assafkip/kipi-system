#!/usr/bin/env python3
"""Stop-hook grounding guard: block the turn if my final answer asserts about a
repo file that never appeared in ANY of my tool activity this session.

WHY (founder-directed 2026-07-14): over a week I gave confident answers about code
and canonical files without reading them, and kept getting them wrong. A prompt
reminder is the banned prompt-only-enforcement anti-pattern; this script IS the
coded blocker. What the code below does: it extracts every EXISTING repo file the
final answer references, checks whether that path appeared anywhere in the
session's evidence (a tool_use input, a tool_result, or an injected file's
content), and exits 2 (block, stderr fed back) for any that appeared NOWHERE else
-- an assertion made from nothing -- so the turn cannot end until those files are
actually opened.

SECOND CHECK -- SUBSYSTEM COVERAGE (added 2026-07-28, RCA
rca-conclusions-before-evidence-2026-07-28): the paragraph that used to sit here said
this gate does NOT catch over-generalizing from a file you DID read -- "reading one
worker and declaring a whole subsystem broken" -- and called that seam behavioral.
It was then tested by exactly that failure: six conclusions reversed in one session,
two of five workflows in a chain read, claims issued about the chain, one reaching a
client email. So the seam is now coded. When the final answer NAMES a subsystem
declared in `<instance-root>/canonical/system-manifest.json`, every member of that
subsystem must appear in session evidence, not just one.

HONEST BOUNDARY (stated so this is not theater): the executable blocker is this
script's own exit 2, driven by `evaluate` (check one) and `evaluate_subsystems`
(check two), both covered by `--self-test`. Check one blocks on a file that appears
nowhere in session evidence; check two blocks on a DECLARED member of a named
subsystem that appears nowhere. Neither can tell whether a file was read carefully,
and neither can tell that the manifest lists every real member -- an incomplete
manifest passes incomplete reading. With no manifest present, check two no-ops
entirely, which is the state every instance starts in.

Contract: reads {transcript_path, stop_hook_active} JSON on stdin (Claude Code
Stop hook). exit 0 = pass, exit 2 = block. Per-answer bypass: put the literal
marker `grounding-guard-skip` in the answer for a deliberate non-content mention.
Self-test: `python3 code_claim_grounding_guard.py --self-test`.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The import failure REASON is kept, not discarded (ASK-533). The bare `except` here
# used to drop it on the floor, so a syntax error or a missing dependency inside
# system_manifest.py silently killed check two forever with no signal anywhere. A
# missing module still must not BLOCK -- an instance predating the manifest is a
# legitimate state -- but "cannot run" and "nothing to run" are different facts and
# only one of them is fine.
_MANIFEST_IMPORT_ERROR = ""
try:  # an instance that predates the manifest keeps check one and skips check two
    if os.environ.get("KIPI_GROUNDING_FORCE_IMPORT_FAILURE") == "1":
        # Test seam. Without it the unimportable-module path is unreachable from a
        # test, and an untestable branch is how it stayed broken: `except Exception`
        # around an import is invisible to every suite that imports successfully.
        raise ImportError("forced by KIPI_GROUNDING_FORCE_IMPORT_FAILURE (test seam)")
    import system_manifest as _manifest
except Exception as exc:  # pragma: no cover - exercised via the env seam above
    _manifest = None
    _MANIFEST_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

MANIFEST_UNREADABLE = "unreadable"
HEALTH_LOG = "q-system/output/grounding-manifest-health.jsonl"

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
SKIP_MARKER = "grounding-guard-skip"

# A repo file reference in prose: a path under a known top dir, OR a bare path
# ending in a known code/doc extension.
_TOPDIRS = r"gtm|q-system|\.claude|plugins|projects|products|persona|sites"
_EXTS = r"py|sh|md|json|ya?ml|js|ts|tsx|txt|html|css|toml|cfg"
REF_RE = re.compile(
    r"(?<![\w/])((?:" + _TOPDIRS + r")/[\w./-]+|[\w./-]+\.(?:" + _EXTS + r"))"
)


def _norm(path):
    path = path.strip().strip(".,:;)('\"`>*")
    path = re.sub(r":\d+(-\d+)?$", "", path)  # drop a file:line suffix
    return path


def _load_records(transcript_path):
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _final_assistant_text(records):
    text = ""
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        parts = [i.get("text", "") for i in msg.get("content", [])
                 if isinstance(i, dict) and i.get("type") == "text"]
        if parts:
            text = "\n".join(parts)  # keep the LAST assistant text block
    return text


def _session_evidence_blob(records, final_text):
    """All session content EXCEPT my final answer: tool inputs, tool results,
    user/system messages (injected file contents live here). If a path shows up
    here, I engaged with it; referencing it in the answer is grounded."""
    parts = []
    for rec in records:
        msg = rec.get("message", {})
        if not isinstance(msg, dict):
            # some transcript rows carry content at top level
            parts.append(json.dumps(rec.get("content", "")))
            continue
        for item in msg.get("content", []):
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("type")
                if t == "text":
                    parts.append(item.get("text", ""))
                elif t == "tool_use":
                    parts.append(json.dumps(item.get("input", {})))
                elif t == "tool_result":
                    c = item.get("content", "")
                    if isinstance(c, list):
                        parts.extend(s.get("text", "") for s in c
                                     if isinstance(s, dict))
                    elif isinstance(c, str):
                        parts.append(c)
    blob = "\n".join(parts)
    # Remove the final answer's own text so a self-reference can't ground itself.
    if final_text:
        blob = blob.replace(final_text, "")
    return blob


def evaluate(final_text, evidence_blob, repo=REPO):
    """Return the sorted list of ungrounded repo-file references (empty = pass)."""
    if not final_text or SKIP_MARKER in final_text:
        return []
    grounded = {_norm(m.group(1)) for m in REF_RE.finditer(evidence_blob)}
    ungrounded = []
    for m in REF_RE.finditer(final_text):
        ref = _norm(m.group(1))
        if not ref or ref in grounded:
            continue
        if not (repo / ref).exists():  # only enforce for files that really exist
            continue
        # tolerate path-tail matches (e.g. grounded has the full path, ref a suffix)
        if any(g.endswith(ref) or ref.endswith(g) for g in grounded if g):
            continue
        ungrounded.append(ref)
    return sorted(set(ungrounded))


def evaluate_subsystems(final_text, evidence_blob, repo=REPO):
    """Subsystems the answer NAMES whose declared members were not all read.

    Returns [(subsystem_id, [unread member refs])], empty when covered or when no
    manifest exists. This is the coded form of the seam this guard used to disclaim.
    """
    if not final_text or SKIP_MARKER in final_text or _manifest is None:
        return []
    try:
        named = _manifest.mentions(repo, final_text)
    except Exception:
        return []  # a malformed manifest must not block the turn; `check` reports it
    uncovered = []
    for sid in named:
        missing = _manifest.missing_members(repo, sid, evidence_blob)
        if missing:
            uncovered.append((sid, missing))
    return uncovered


def manifest_health(repo=REPO):
    """(status, detail) for the manifest the coverage check depends on.

    Folds the module-import failure into the same vocabulary as the file-level states,
    because from the operator's seat they are one fact: check two is not running.
    """
    if _manifest is None:
        return (MANIFEST_UNREADABLE,
                f"system_manifest module could not be imported "
                f"({_MANIFEST_IMPORT_ERROR or 'no reason recorded'}); the "
                f"subsystem-coverage check is DEAD, not merely idle")
    try:
        return _manifest.health(repo)
    except Exception as exc:
        return (MANIFEST_UNREADABLE,
                f"system_manifest.health() raised {type(exc).__name__}: {exc}")


def _record_health(status, detail, enforced):
    """Append one row so the warn-phase rate is MEASURABLE against real runs.

    The whole point of shipping warn-first is to learn how often this fires before
    deciding fail-closed is safe on a hook that runs every turn. A warning nobody
    counts is just noise that trains the operator to ignore the line.

    Never raises: a telemetry failure must not take down the Stop hook it observes.
    """
    try:
        import datetime
        p = REPO / HEALTH_LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "status": status, "detail": detail[:400], "enforced": bool(enforced),
                "repo": str(REPO),
            }) + "\n")
    except Exception:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("stop_hook_active"):  # loop guard: block at most once per cycle
        sys.exit(0)

    # WARN PHASE (ASK-533). Report a manifest that cannot be read; do NOT block on it
    # yet. This hook fires on every turn fleet-wide, so a fail-closed flip with one bad
    # manifest anywhere wedges every session in every instance. Measure the real rate
    # from HEALTH_LOG first, then decide. The flip is one env var, deliberately OFF.
    status, detail = manifest_health()
    if status == MANIFEST_UNREADABLE:
        enforce = os.environ.get("KIPI_GROUNDING_MANIFEST_ENFORCE") == "1"
        _record_health(status, detail, enforce)
        # AND reach the AGENT, through the one channel the docs actually define for a
        # non-blocking Stop message: exit 0 plus hookSpecificOutput.additionalContext
        # (Claude Code hooks reference, Stop event). Deliberately NOT `systemMessage`
        # or `continue` -- both appear only in the generic JSON section and are
        # undocumented for Stop, and shipping an unverified field is how you get a
        # channel that silently does nothing, which is the entire defect class here.
        # The nesting is load-bearing: a TOP-LEVEL additionalContext is silently
        # ignored, the scar recorded at token-guard.py:743.
        if not enforce:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    "GROUNDING GUARD WARNING: the subsystem-coverage check is NOT "
                    "running because the manifest is unreadable. " + detail +
                    " Say so in your answer rather than implying coverage held, and "
                    "run `python3 q-system/.q-system/scripts/system_manifest.py check`."
                )}}))
        sys.stderr.write(
            f"GROUNDING GUARD ({'blocked' if enforce else 'warning'}): the manifest "
            f"is UNREADABLE, so the subsystem-coverage check (check two) is not "
            f"running.\n  {detail}\n"
            "This is the fail-open the guard is weakest on: it goes quiet on exactly "
            "the corrupted evidence that should alarm it (ASK-533). An ABSENT manifest "
            "is fine and silent; this one is present and broken.\n"
            "Fix: `python3 q-system/.q-system/scripts/system_manifest.py check`\n"
            "Out-of-band paging is deliberately NOT wired here (ASK-534): "
            "slack-notify.sh masks curl failure and exits 0, so no exit-code check "
            "can confirm delivery, and fixing that changes a shared script every "
            "other caller depends on.\n")
        if enforce:
            sys.exit(2)
    records = _load_records(payload.get("transcript_path", ""))
    if not records:
        sys.exit(0)
    final_text = _final_assistant_text(records)
    evidence = _session_evidence_blob(records, final_text)

    uncovered = evaluate_subsystems(final_text, evidence)
    if uncovered:
        detail = "\n".join(
            f"  {sid}: {len(refs)} declared member(s) never opened this session\n" +
            "\n".join(f"    - {r}" for r in refs[:10])
            for sid, refs in uncovered[:5])
        sys.stderr.write(
            "GROUNDING GUARD (blocked): your answer names a subsystem from "
            "system-manifest.json, but you did not read all of it:\n" + detail + "\n\n"
            "Open the missing members before you characterise the subsystem, then "
            "answer again. Scar 2026-07-28: two of five workflows in a chain were "
            "read, six conclusions about the chain were issued, all six were "
            "reversed, and one reached a client email draft. Naming part of a path "
            "and describing the whole path is the exact failure. Deliberate mention "
            "with no claim attached? Add the marker '" + SKIP_MARKER + "'.\n")
        sys.exit(2)

    ungrounded = evaluate(final_text, evidence)
    if ungrounded:
        listed = "\n".join(f"  - {u}" for u in ungrounded[:20])
        sys.stderr.write(
            "GROUNDING GUARD (blocked): your answer asserts about repo files that "
            "appear NOWHERE in your tool activity this session:\n" + listed + "\n\n"
            "Open each one (Read / Grep / cat) before you claim anything about it, "
            "then answer again. Founder-directed 2026-07-14: no confident answer "
            "about code or canon without reading it. Deliberate non-content mention? "
            "Add the marker '" + SKIP_MARKER + "'.\n")
        sys.exit(2)
    sys.exit(0)


# prompt-only-enforcement-skip
# ^ the fixtures below are ASSERTIONS UNDER TEST, not enforcement claims: each is a
# sentence a model might say, fed to evaluate_subsystems to prove the gate fires. The
# blocker for this file is its own exit 2, exercised by the cases in _self_test.
# Same exception test_prompt_only_enforcement_guard.py takes on its own fixtures.
def _self_test():
    # Hermetic: build a temp repo with one real file so the test is
    # environment-independent (does not depend on any repo-specific path).
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    real = "sub/real_file.py"        # will exist under tmp
    fake = "sub/does_not_exist.py"   # will not exist
    (tmp / "sub").mkdir(parents=True, exist_ok=True)
    (tmp / real).write_text("print('x')\n", encoding="utf-8")
    cases = []

    # 1. Reference a real file that IS in the evidence -> pass.
    cases.append(("grounded real file passes",
                  evaluate(f"As {real} shows, X.", f"ran cat {real}", tmp) == []))
    # 2. Reference a real file NOT in evidence -> block.
    cases.append(("ungrounded real file blocks",
                  evaluate(f"{real} clearly does X.", "unrelated evidence", tmp) == [real]))
    # 3. Reference a non-existent path -> never blocks (can't read what's not there).
    cases.append(("nonexistent path ignored",
                  evaluate(f"I will create {fake}.", "", tmp) == []))
    # 4. Skip marker bypasses.
    cases.append(("skip marker bypasses",
                  evaluate(f"{real} does X. {SKIP_MARKER}", "nothing", tmp) == []))
    # 5. No file references -> pass.
    cases.append(("no refs passes",
                  evaluate("Just a conversational reply.", "", tmp) == []))
    # 6. file:line citation of an ungrounded real file -> block.
    cases.append(("file:line citation blocks when ungrounded",
                  evaluate(f"see {real}:42", "unrelated", tmp) == [real]))

    # --- check two: subsystem coverage (the seam this guard used to disclaim) ---
    # With no manifest, coverage must no-op -- that is every instance's starting state.
    cases.append(("no manifest -> coverage no-ops",
                  evaluate_subsystems("the ingest chain is broken", "", tmp) == []))

    canon = tmp / "q-thing" / "canonical"
    canon.mkdir(parents=True, exist_ok=True)
    (canon / "system-manifest.json").write_text(json.dumps({
        "version": 1,
        "subsystems": [{
            "id": "groupme-to-sheet",
            "name": "GroupMe order intake",
            "aliases": ["the ingest chain"],
            "members": [{"ref": "Postgres Ingest"}, {"ref": "Parse LLM"},
                        {"ref": "QA Validator"}],
        }],
    }), encoding="utf-8")

    # 7. THE reproducer: two of three members read, a claim about the chain issued.
    partial = evaluate_subsystems(
        "The ingest chain loses rows on the way to the sheet.",
        "opened Postgres Ingest and Parse LLM", tmp)
    cases.append(("partial subsystem read blocks",
                  partial == [("groupme-to-sheet", ["QA Validator"])]))
    # 8. All members read -> pass.
    cases.append(("full subsystem read passes",
                  evaluate_subsystems(
                      "The ingest chain looks healthy.",
                      "Postgres Ingest / Parse LLM / QA Validator all opened",
                      tmp) == []))
    # 9. Naming nothing from the manifest -> pass.
    cases.append(("unrelated answer passes coverage",
                  evaluate_subsystems("The build is green.", "", tmp) == []))
    # 10. Skip marker bypasses coverage too, same as check one.
    cases.append(("skip marker bypasses coverage",
                  evaluate_subsystems(
                      f"the ingest chain is broken {SKIP_MARKER}", "", tmp) == []))

    ok = True
    for name, passed in cases:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
        ok = ok and passed
    print(f"\n{sum(p for _, p in cases)}/{len(cases)} passed")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    main()
