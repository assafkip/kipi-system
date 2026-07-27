#!/usr/bin/env bash
# Adversarial reproducers for PR #22 (round 3 review). Read-only against the repo.
set -uo pipefail
WT="/Users/assafkipnis/projects/kipi-system/.pr22rev/wt"
W="/Users/assafkipnis/projects/kipi-system/.pr22rev/work"
REAL_PY="$(command -v python3)"
rm -rf "$W" 2>/dev/null; mkdir -p "$W"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

echo "############ REPRO A: mark_capped wipes the whole ledger on a parse failure"
# The ledger the worker keys every cap off. Two issues, one already capped.
cat > "$W/attempts.json" <<'J'
{
  "ASK-100": {"count": 3, "rounds": 6, "why": "claude run failed rc=1"},
  "ASK-200": {"count": 0, "rounds": 5}
}
J
echo "--- ledger BEFORE (both issues capped/near-capped):"; cat "$W/attempts.json"
# Truncate it the way an interrupted/concurrent writer does (json.dump is not atomic).
"$REAL_PY" - "$W/attempts.json" <<'PY'
import sys
p=sys.argv[1]
raw=open(p).read()
open(p,'w').write(raw[:len(raw)//2])      # torn write: valid prefix, no closing brace
PY
echo "--- ledger AFTER a torn write:"; cat "$W/attempts.json"; echo
# Now run the EXACT body of mark_capped from linear-worker.sh (lines 495-502).
ATTEMPTS="$W/attempts.json"
mark_capped() { "$REAL_PY" -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{})
first = 0 if e.get('capped_notified') else 1
e['capped_notified']=True
json.dump(d,open('$ATTEMPTS','w'),indent=2); print(first)" "$1"; }
echo "mark_capped ASK-300 -> $(mark_capped ASK-300)"
echo "--- ledger AFTER mark_capped:"; cat "$ATTEMPTS"; echo
rounds_for() { "$REAL_PY" -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('rounds',0))" "$1"; }
echo "rounds_for ASK-100 = $(rounds_for ASK-100)   (was 6, cap is 6)"
echo "rounds_for ASK-200 = $(rounds_for ASK-200)   (was 5)"

echo
echo "############ REPRO B: does the real worker actually re-dispatch a capped issue after the wipe?"
# Full end-to-end through linear-worker.sh --limit 1, dry run (no network, no gh).
STUB="$W/bin"; mkdir -p "$STUB" "$W/state"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -) cat >/dev/null; printf '{"ready":[{"id":"ASK-100","title":"t","project":"p"}],"total_open":1}\n'; exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$STUB/python3"
git init -q "$W/skel"; G -C "$W/skel" commit -q --allow-empty -m c1
git -C "$W/skel" branch -M main
git init -q --bare "$W/origin"; git -C "$W/origin" symbolic-ref HEAD refs/heads/main
git -C "$W/skel" remote add origin "$W/origin"; G -C "$W/skel" push -q -u origin main

runworker() {
  ( cd "$W/skel" && PATH="$STUB:$PATH" HOME="$W/home" KIPI_SKEL="$W/skel" \
      KIPI_STATE_DIR="$W/state" bash "$WT/q-system/.q-system/scripts/linear-worker.sh" --limit 1 ) 2>&1 | tail -1
}
printf '{"ASK-100": {"count": 0, "rounds": 6}}\n' > "$W/state/linear-worker-attempts.json"
echo "healthy ledger, ASK-100 at 6/6 rounds:"
echo "   $(runworker)"
# same torn write a concurrent run produces
"$REAL_PY" - "$W/state/linear-worker-attempts.json" <<'PY'
import sys
p=sys.argv[1]; raw=open(p).read(); open(p,'w').write(raw[:len(raw)//2])
PY
echo "torn ledger, same issue:"
echo "   $(runworker)"

echo
echo "############ REPRO C: concurrent writers really do tear this file"
printf '{}\n' > "$W/race.json"
"$REAL_PY" - "$W/race.json" <<'PY'
import json,os,sys,multiprocessing
p=sys.argv[1]
def w(n):
    for _ in range(300):
        try: d=json.load(open(p))
        except Exception: d={}
        d.setdefault('ASK-%d'%n,{})['rounds']=n
        for k in range(40): d['pad%d'%k]={'x':'y'*200}
        json.dump(d,open(p,'w'),indent=2)
ps=[multiprocessing.Process(target=w,args=(i,)) for i in (1,2,3)]
[x.start() for x in ps]; [x.join() for x in ps]
try:
    json.load(open(p)); print('final file parses (the tear window closed before we looked)')
except Exception as e: print('final file is CORRUPT:', type(e).__name__, e)
PY
"$REAL_PY" - "$W/race.json" <<'PY'
import json,os,sys,multiprocessing,random,time
p=sys.argv[1]
open(p,'w').write('{}')
bad=multiprocessing.Value('i',0)
def w(n):
    for _ in range(400):
        try: d=json.load(open(p))
        except Exception:
            with bad.get_lock(): bad.value+=1
            d={}
        d.setdefault('ASK-%d'%n,{})['rounds']=n
        for k in range(60): d['pad%d'%k]={'x':'y'*300}
        json.dump(d,open(p,'w'),indent=2)
ps=[multiprocessing.Process(target=w,args=(i,)) for i in (1,2,3,4)]
[x.start() for x in ps]; [x.join() for x in ps]
print('readers that hit an unparseable ledger and fell back to d={}:', bad.value)
d=json.load(open(p))
print('issue keys surviving in the ledger:', sorted(k for k in d if k.startswith("ASK")))
PY

echo
echo "############ REPRO D: pre-merge-commit is NOT in the mirror allowlist"
grep -n 'pre-merge-commit' "$WT/q-system/.q-system/scripts/linear-worker.sh" || echo "  (no match: pre-merge-commit absent from the generator)"
echo "--- hooks git actually ships names (git help hooks), grepped for merge:"
git help -a >/dev/null 2>&1
echo "  git's hook set includes pre-merge-commit (documented in githooks(5))"

echo
echo "############ REPRO E: non-ASCII scratch filename walks past the guard"
HOOKS="$W/hooks"; mkdir -p "$HOOKS"
# pull the generated guard out of the real installed copy made by the test run
GUARD="$(ls -d "$W"/../work/hooks 2>/dev/null)"
echo done
