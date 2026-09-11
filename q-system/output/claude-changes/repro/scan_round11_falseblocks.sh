#!/usr/bin/env bash
# Print the ACTUAL block reason for the three permanent-suite cases that went
# red after round-11 pass 2, plus the per-token reach verdict. Measuring beats
# reasoning about it: pass 1 was wrong in a way I had reasoned was right.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/q-system/.q-system/scripts/claude-path-write-guard.py"

python3 - "$GUARD" "$ROOT" <<'PY'
import importlib.util, shlex, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
cwd = sys.argv[2]
cases = [
    ("D1 base64 substitution",
     'P=$(printf %s Y2xhdWRl | base64 --decode); printf pwned > ".$P/settings.json"'),
    ("temp-dir fixture beside nothing",
     'D=$(mktemp -d); mkdir -p "$D/.claude/rules"'),
    ("escape hatch: pipe into awk",
     'cat .claude/settings.json | awk \'{print $1}\''),
]
base = g.os.path.normpath(g.os.path.join(cwd, g.LAYER2_BASELINE_REL))
for name, cmd in cases:
    print("=== %s" % name)
    print("   voids =", g._voids_layer2(cmd, cwd))
    print("   reason=", repr(g.analyse(cmd, cwd)))
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
                        print("   REACHES via %r  (stage %r)" % (t, stage))
PY
