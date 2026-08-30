#!/usr/bin/env python3
"""Does a UserPromptSubmit hook's additionalContext reach the model WITHOUT
hookEventName?

Codex called its absence a major on PR #277 ("the payload is discarded"). The
published docs, read back by a summarizer, say the key looks optional. Neither is
a measurement, and the claim decides whether lessons-inject has been delivering
for its whole life or not at all. So: run it.

Three arms, each a real headless session with its own project dir and its own
hook:

    nested_with_name    {"hookSpecificOutput": {"hookEventName": ..., "additionalContext": M}}
    nested_no_name      {"hookSpecificOutput": {"additionalContext": M}}      <- the disputed one
    top_level           {"additionalContext": M}                              <- the recorded scar

Each marker is unique per run, so a marker in the answer can only have come from
that arm's hook. The prompt asks the model to echo the marker or say ABSENT,
which makes a non-delivery legible instead of silent.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import uuid

ARMS = {
    "nested_with_name": '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "%s"}}',
    "nested_no_name": '{"hookSpecificOutput": {"additionalContext": "%s"}}',
    "top_level": '{"additionalContext": "%s"}',
}

PROMPT = ("Some context may have been injected into this turn. If it contains a "
          "token of the form MARKER-<letters>-<digits>, reply with that token and "
          "nothing else. If there is no such token, reply with exactly ABSENT.")


def build(root: pathlib.Path, shape: str, marker: str) -> None:
    hooks_dir = root / "hooks"
    hooks_dir.mkdir(parents=True)
    hook = hooks_dir / "emit.py"
    payload = shape % ("CONTEXT: the secret token is " + marker)
    # Sanity: the marker has to survive into the bytes the hook will print, or
    # the arm proves nothing about delivery.
    assert marker in payload, payload
    json.loads(payload)          # and it has to be valid JSON
    hook.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdin.read()\n"
        "sys.stdout.write(%r)\n" % payload)
    hook.chmod(0o755)
    cfg = root / ".claude"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text(json.dumps({
        "hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "python3 %s" % hook}]}]}
    }, indent=2))


def ask(root: pathlib.Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        r = subprocess.run(["claude", "-p", PROMPT], cwd=str(root), env=env,
                           capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "RUN-FAILED: %s" % exc
    return (r.stdout or r.stderr or "").strip()


def main() -> int:
    results = {}
    for arm, shape in ARMS.items():
        marker = "MARKER-%s-%d" % (uuid.uuid4().hex[:6].upper(),
                                   abs(hash(arm)) % 9000 + 1000)
        root = pathlib.Path(tempfile.mkdtemp(prefix="envprobe-%s-" % arm))
        build(root, shape, marker)
        answer = ask(root)
        delivered = marker in answer
        results[arm] = (marker, delivered, answer[:160].replace("\n", " "))
        print("%-18s marker=%s delivered=%-5s answer=%r"
              % (arm, marker, delivered, answer[:80].replace("\n", " ")))

    print()
    with_name = results["nested_with_name"][1]
    no_name = results["nested_no_name"][1]
    top = results["top_level"][1]
    if not with_name:
        print("INCONCLUSIVE: the KNOWN-GOOD shape did not deliver either, so this "
              "probe is not measuring what it claims. Fix the harness before "
              "reading anything into the other two arms.")
        return 2
    print("nested WITH hookEventName delivered: %s  (control, expected True)" % with_name)
    print("nested WITHOUT hookEventName delivered: %s" % no_name)
    print("top-level additionalContext delivered: %s  (recorded scar says False)" % top)
    print()
    if no_name:
        print("VERDICT: hookEventName is NOT required. Codex's major on PR #277 "
              "is WRONG, and lessons-inject HAS been delivering all along.")
    else:
        print("VERDICT: hookEventName IS required. Codex's major stands and the "
              "hook was inert until it was added.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
