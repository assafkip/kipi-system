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

HONEST BOUNDARY (stated so this is not theater): this catches "claimed about a
file you never opened." It does NOT catch over-generalizing from a file you DID
read (e.g. reading one worker and declaring a whole subsystem broken). That seam
is behavioral; this gate is the enforceable floor.

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


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("stop_hook_active"):  # loop guard: block at most once per cycle
        sys.exit(0)
    records = _load_records(payload.get("transcript_path", ""))
    if not records:
        sys.exit(0)
    final_text = _final_assistant_text(records)
    ungrounded = evaluate(final_text, _session_evidence_blob(records, final_text))
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
