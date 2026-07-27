"""Print the offending line for each gating Gate 1.3b finding."""
import importlib.util
import subprocess

ROOT = "/Users/assafkipnis/.config/kipi/worktrees/ask-191"
spec = importlib.util.spec_from_file_location("vs", ROOT + "/validate-separation.py")
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

violations = vs.semantic_separation_violations(ROOT)
gating, _ = vs.partition_semantic_violations(violations)

cache = {}
for v in sorted(gating, key=lambda x: (x["path"], x["line"])):
    path = v["path"]
    if path not in cache:
        out = subprocess.run(
            ["git", "show", "HEAD:" + path], cwd=ROOT,
            capture_output=True, text=True,
        )
        cache[path] = out.stdout.splitlines()
    lines = cache[path]
    idx = v["line"] - 1
    text = lines[idx].strip() if 0 <= idx < len(lines) else "<out of range>"
    print("%-70s %-20s | %s" % (path + ":" + str(v["line"]), v["fact_class"], text[:110]))
