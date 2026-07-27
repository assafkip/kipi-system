"""Read-only triage helper for ASK-191. Lists what Gate 1.3b now GATES on."""
import importlib.util

ROOT = "/Users/assafkipnis/.config/kipi/worktrees/ask-191"
spec = importlib.util.spec_from_file_location("vs", ROOT + "/validate-separation.py")
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

violations = vs.semantic_separation_violations(ROOT)
gating, advisory = vs.partition_semantic_violations(violations)
print("total=%d gating=%d advisory=%d" % (len(violations), len(gating), len(advisory)))
print()
for v in sorted(gating, key=lambda x: (x["path"], x["line"])):
    print("%s:%s: %s" % (v["path"], v["line"], v["fact_class"]))
