#!/usr/bin/env bash
# Why does the permanent suite's D1 case (base64 command substitution) now block
# at Layer 1, when it is PINNED as a miss that proves Layer 2 is load-bearing?
# Print the verdict and the _voids_layer2 decision separately.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"
D="$(mktemp -d)"

python3 - "$GUARD" "$D" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
cwd = sys.argv[2]
cmd = 'P=$(printf %s Y2xhdWRl | base64 --decode); printf pwned > ".$P/settings.json"'
print("voids_layer2 =", g._voids_layer2(cmd, cwd))
print("analyse      =", repr(g.analyse(cmd, cwd)))
import shlex
base = g.os.path.normpath(g.os.path.join(cwd, g.LAYER2_BASELINE_REL))
for text in [cmd] + g.extract_substitutions(cmd):
    for stmt in g.split_outside_quotes(g.strip_heredocs(text), g.STATEMENT_OPS):
        for stage in g.split_outside_quotes(stmt, ("|",)):
            try:
                toks = shlex.split(stage, comments=True)
            except ValueError:
                toks = stage.split()
            assigns = dict(a.groups() for a in (g.ASSIGN.match(t) for t in toks) if a)
            for t in toks:
                if g._could_name_baseline(t, cwd, assigns, base):
                    print("  REACHES via token %r in stage %r" % (t, stage))
PY
