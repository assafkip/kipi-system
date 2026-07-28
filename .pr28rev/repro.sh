#!/usr/bin/env bash
# Read-only reproducers against PR #28 head (9968fe4). Touches nothing in the repo.
set -uo pipefail
R="/Users/assafkipnis/projects/kipi-system/.pr28rev/root/q-system/.q-system/scripts"
. "$R/pr-verdict-lib.sh"
SHA_A="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_B="ffeeddccbbaa99887766554433221100aabbccdd"

echo "=== R1: 4-arg caller, BOTH shas unknown (pre-216 record + gh down) ==="
OUT="$(rework_gate "APPROVE" "CLEAN" "" "")"; RC=$?
echo "rc=$RC   stdout='${OUT}'"
[ "$RC" = "10" ] && [ -z "$OUT" ] \
  && echo "REPRO HIT: terminal-approve returned SILENTLY on a record with no pinned sha" \
  || echo "no repro"

echo
echo "--- control: only ONE side unknown (what the test covers) ---"
O1="$(rework_gate "APPROVE" "CLEAN" "" "$SHA_B")"; echo "rec-empty  rc=$? note='${O1}'"
O2="$(rework_gate "APPROVE" "CLEAN" "$SHA_A" "")"; echo "cur-empty  rc=$? note='${O2}'"

echo
echo "=== R2: gh cannot answer -> does the writer still write the record? ==="
W="$(mktemp -d)"; mkdir -p "$W/stub" "$W/home"
cat > "$W/stub/gh" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat > "$W/stub/claude" <<'EOF'
#!/usr/bin/env bash
printf '## VERDICT: APPROVE\n\nFINDINGS:\nEND FINDINGS\n'
EOF
chmod +x "$W/stub/gh" "$W/stub/claude"
( PATH="$W/stub:$PATH" HOME="$W/home" bash "$R/pr-review-agent.sh" 901 ) >"$W/out" 2>&1
echo "reviewer rc=$?  stdout: $(cat "$W/out")"
REC="$W/home/.config/kipi/pr-reviews/pr-901.verdict.json"
if [ -e "$REC" ]; then echo "record exists: $(cat "$REC")"
else echo "REPRO HIT: NO record written at all. The lib/writer comment claims the head_sha"
     echo "           key is 'ALWAYS written -- empty when gh could not answer'."; fi

echo
echo "=== R3: is exit 40 reachable from any production caller? ==="
grep -n 'rework_gate' "$R/linear-worker.sh" /Users/assafkipnis/projects/kipi-system/.pr28rev/converge-head.sh 2>/dev/null | grep -v '^.*#'
echo "--- replay converge.sh's exact call site with a DRIFTED approval ---"
CJ="$W/pr-777.verdict.json"
printf '{"pr":777,"verdict":"APPROVE","head_sha":"%s"}\n' "$SHA_A" > "$CJ"
VERDICT="$(verdict_from_record "$CJ")"      # converge.sh:158
SHA="$SHA_B"                                # converge.sh:159 = current head, MOVED
rework_gate "$VERDICT"; GATE=$?             # converge.sh:161, verbatim
echo "verdict='$VERDICT' recorded_sha=$SHA_A current_sha=$SHA -> GATE=$GATE"
[ "$GATE" = "10" ] && echo "REPRO HIT: converge.sh still reports DONE/terminal on an approval the head outran"
rm -rf "$W"
