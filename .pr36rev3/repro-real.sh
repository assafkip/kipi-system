#!/usr/bin/env bash
# The reviewer's finding-1 measurement, re-run against the FIXED script.
# Real Linear DoRs, the real kipi-dispatch.sh, converge stubbed so nothing is
# actually dispatched. Only the network is replaced.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

SB="$HERE/sandbox"
rm -rf "$SB"; mkdir -p "$SB/home/.config/kipi" "$SB/repo"
export HOME="$SB/home"
export KIPI_STUB_LOG="$SB/converge.log"; : > "$KIPI_STUB_LOG"

cat > "$SB/repo/kipi" <<'STUB'
#!/usr/bin/env bash
case "${1:-}" in
  work)
    echo "worker: $KIPI_STUB_TOTAL ready issue(s) (owner:sana, has a DoR, not owner:assaf)"
    N=0
    for i in $KIPI_STUB_READY; do
      N=$((N+1)); [ "$N" -gt "${3:-99}" ] && break
      echo "[dry] would work $i (attempt 1/3)"
    done
    ;;
  converge)
    shift; ISSUE=""
    while [ $# -gt 0 ]; do case "$1" in --issue) shift; ISSUE="${1:-}" ;; esac; shift; done
    printf 'START %s\n' "$ISSUE" >> "$KIPI_STUB_LOG"
    sleep 1
    printf 'END %s\n' "$ISSUE" >> "$KIPI_STUB_LOG"
    ;;
esac
exit 0
STUB
chmod +x "$SB/repo/kipi"
printf '#!/usr/bin/env bash\nprintf "PAGE: %%s\\n" "$1"\nexit 0\n' > "$SB/notify.sh"
chmod +x "$SB/notify.sh"

export KIPI_REPO="$SB/repo"
# one-set.sh sources the script's function head through a here-string, so
# ${BASH_SOURCE[0]} cannot locate prd_split.py for it. Pin it explicitly.
export KIPI_DISPATCH_PRD_SPLIT="$ROOT/plugins/prd-os/scripts/prd_split.py"
export KIPI_NOTIFY="$SB/notify.sh"
export KIPI_DISPATCH_DOR_FIXTURE="$HERE/dor.json"
export KIPI_DISPATCH_FAKE_LIVE=""
export KIPI_STUB_READY="$(cat "$HERE/ready.txt")"
export KIPI_STUB_TOTAL="$(wc -w < "$HERE/ready.txt" | tr -d ' ')"

echo "=== A. the plist's own settings: KIPI_DISPATCH_MAX=1, heartbeat tick"
KIPI_DISPATCH_MAX=1 KIPI_DISPATCH_DAILY_MAX=4 bash "$ROOT/kipi-dispatch.sh" 2>&1 | grep -vE 'heartbeat: (STARTED|first)'
echo "--- dispatched: [$(grep '^START ' "$KIPI_STUB_LOG" | awk '{print $2}' | tr '\n' ' ')]"

echo
echo "=== B. how many of the $KIPI_STUB_TOTAL real ready issues now have a USABLE file set"
python3 "$HERE/classify.py"
