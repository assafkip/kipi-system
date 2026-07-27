#!/usr/bin/env bash
set -uo pipefail
WT="/Users/assafkipnis/projects/kipi-system/.pr22rev/wt"
W="/Users/assafkipnis/projects/kipi-system/.pr22rev/work2"
REAL_PY="$(command -v python3)"
rm -rf "$W" 2>/dev/null; mkdir -p "$W/state" "$W/bin"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

cat > "$W/bin/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -) cat >/dev/null; printf '{"ready":[{"id":"ASK-100","title":"t","project":"p"}],"total_open":1}\n'; exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$W/bin/python3"
git init -q "$W/skel" >/dev/null; G -C "$W/skel" commit -q --allow-empty -m c1
git -C "$W/skel" branch -M main
git init -q --bare "$W/origin" >/dev/null; git -C "$W/origin" symbolic-ref HEAD refs/heads/main
git -C "$W/skel" remote add origin "$W/origin"; G -C "$W/skel" push -q -u origin main >/dev/null 2>&1

runworker() {
  ( cd "$W/skel" && PATH="$W/bin:$PATH" HOME="$W/home" KIPI_SKEL="$W/skel" \
      KIPI_STATE_DIR="$W/state" bash "$WT/q-system/.q-system/scripts/linear-worker.sh" --limit 1 ) 2>&1 \
    | grep -E 'skip ASK-100|would work ASK-100'
}

echo "== B1: healthy ledger, ASK-100 already at 6/6 rounds -> the cap must refuse"
printf '{"ASK-100": {"count": 0, "rounds": 6, "capped_notified": true}}\n' > "$W/state/linear-worker-attempts.json"
runworker

echo
echo "== B2: SAME ledger, torn by a concurrent writer (valid prefix, no closing brace)"
"$REAL_PY" - "$W/state/linear-worker-attempts.json" <<'PY'
import sys
p=sys.argv[1]; raw=open(p).read(); open(p,'w').write(raw[:len(raw)//2])
PY
cat "$W/state/linear-worker-attempts.json"; echo
runworker
echo "^^ the cap is gone: the parked issue is dispatchable again, silently"

echo
echo "############ REPRO C: two concurrent worker ledger writes really do tear the file"
"$REAL_PY" - "$W/race.json" <<'PY'
import json, os, sys, time
p = sys.argv[1]
open(p, 'w').write('{}')
# Exactly the read-modify-write the worker's bump/mark_capped helpers do.
BODY = """
import json, sys
p = sys.argv[1]; who = sys.argv[2]
for _ in range(400):
    try: d = json.load(open(p))
    except Exception:
        sys.stdout.write('TORN\\n'); d = {}
    d.setdefault('ASK-' + who, {})['rounds'] = 6
    for k in range(80): d['ASK-pad%d' % k] = {'count': 3, 'rounds': 6, 'why': 'x'*200}
    json.dump(d, open(p, 'w'), indent=2)
"""
open('/tmp/_w.py', 'w') if False else None
import subprocess, tempfile
f = tempfile.NamedTemporaryFile('w', suffix='.py', delete=False); f.write(BODY); f.close()
procs = [subprocess.Popen([sys.executable, f.name, p, str(i)], stdout=subprocess.PIPE, text=True) for i in (1,2,3,4)]
torn = 0
for pr in procs:
    out, _ = pr.communicate()
    torn += out.count('TORN')
print('reads that found an UNPARSEABLE ledger and fell back to d={}:', torn)
d = json.load(open(p))
print('issue keys left in the ledger at the end:', len([k for k in d if k.startswith('ASK')]), 'of 84 written')
PY
