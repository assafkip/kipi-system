# Run the REAL kipi-dispatch.sh file-set extraction over every real ready DoR
# and bucket the outcome. This shells the actual script's fileset_for, so it
# cannot drift from what the dispatcher does.
import collections, json, os, pathlib, subprocess

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
fx = json.loads((HERE / "dor.json").read_text())

env = dict(os.environ)
env["KIPI_DISPATCH_DOR_FIXTURE"] = str(HERE / "dor.json")

# Source the script's own fileset_for by running it in a bash shell that stops
# before the top-level flow: easiest honest route is to call the function via
# `bash -c 'source ... ; fileset_for'`, but the script runs top-to-bottom. So
# drive the real script instead, one candidate at a time, and read its verdict
# off the log lines it prints.
buckets = collections.Counter()
examples = {}
for issue in fx:
    out = HERE / "sets" / issue
    out.parent.mkdir(exist_ok=True)
    proc = subprocess.run(
        ["bash", str(HERE / "one-set.sh"), issue, str(out)],
        capture_output=True, text=True, env=env)
    # fileset_known's contract: 0 = known, 1 = unknown (a DoR gap), 2 = a fault.
    # Collapsing 1 and 2 is exactly the conflation this PR round removed from
    # the script, so the measurement must not reintroduce it.
    if proc.returncode == 2:
        k = "UNREADABLE -> a fault, pages"
        detail = proc.stdout.strip()[:70]
    elif proc.returncode == 1:
        k = "unknown -> runs ALONE (was: never)"
        detail = "no usable Files list"
    else:
        paths = out.read_text().split()
        k = "KNOWN -> can run IN PARALLEL"
        detail = "%d path(s), e.g. %s" % (len(paths), paths[0])
    buckets[k] += 1
    examples.setdefault(k, (issue, detail))
    # What the PREVIOUS cut would have done: no `~/`-anchored tokens at all.
    if proc.returncode == 0 and not any(
            not p.startswith("/") for p in out.read_text().split()):
        buckets["  ...of which KNOWN only because of the ~/ fix"] += 1

total = sum(v for k, v in buckets.items() if not k.startswith("  ..."))
print("    %d real ready issues classified by the real script" % total)
for k, v in buckets.most_common():
    if k.startswith("  ..."):
        print("  %3d%s" % (v, k))
        continue
    ex = examples[k]
    print("  %3d  %-36s  e.g. %s (%s)" % (v, k, ex[0], ex[1]))
print()
print("  DISPATCHED AT ALL: %d of %d   (the previous cut: %d, and 0 once those ran out)"
      % (total - buckets["UNREADABLE -> a fault, pages"], total,
         buckets["KNOWN -> can run IN PARALLEL"]))
