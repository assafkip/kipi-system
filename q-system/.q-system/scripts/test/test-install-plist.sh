#!/bin/bash
# Pins install-plist.sh (ASK-191): every committed com.kipi.*.plist template
# renders to a placeholder-free, plutil-valid plist, and no template ships a
# hardcoded home directory.
#
# Includes a negative self-test: a template whose placeholder the substituter
# cannot resolve MUST make the installer exit non-zero. Without that case, a
# renderer that silently emitted garbage would still show all-green above.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALLER="$PLIST_DIR/install-plist.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILS=0
pass() { echo "  PASS $1"; }
fail() { echo "  FAIL $1"; FAILS=$((FAILS + 1)); }

[ -f "$INSTALLER" ] || { echo "FAIL install-plist.sh missing at $INSTALLER"; exit 1; }

echo "test-install-plist.sh"

TEMPLATE_COUNT=0
for template in "$PLIST_DIR"/com.kipi.*.plist; do
  [ -e "$template" ] || continue
  TEMPLATE_COUNT=$((TEMPLATE_COUNT + 1))
  label="$(basename "$template" .plist)"

  # 1. No template hardcodes a user home. This is validate-separation's Full
  #    skeleton sweep rule, expressed as a unit test so it fails here first.
  if grep -q "/Users/[a-zA-Z]" "$template"; then
    fail "$label: template hardcodes a /Users/<name> path"
  else
    pass "$label: no hardcoded home in template"
  fi

  # 2. It renders with no placeholder left.
  out="$TMP/$label.plist"
  if bash "$INSTALLER" "$label" --render-only "$out" >/dev/null 2>&1; then
    if grep -q "__KIPI_REPO__\|__HOME__" "$out"; then
      fail "$label: placeholder survived the render"
    else
      pass "$label: renders placeholder-free"
    fi
    # 3. The render is a plist launchd can actually load.
    if command -v plutil >/dev/null 2>&1; then
      if plutil -lint "$out" >/dev/null 2>&1; then
        pass "$label: rendered plist is valid XML plist"
      else
        fail "$label: rendered plist fails plutil -lint"
      fi
    fi
  else
    fail "$label: --render-only failed"
  fi
done

if [ "$TEMPLATE_COUNT" -lt 3 ]; then
  fail "expected at least 3 com.kipi.*.plist templates, found $TEMPLATE_COUNT"
else
  pass "found $TEMPLATE_COUNT plist templates"
fi

# 4. NEGATIVE SELF-TEST.
#    A template carrying a placeholder the substituter does not know how to
#    resolve must make the installer FAIL. Built by pointing the installer at a
#    scratch directory holding one deliberately-broken template.
NEG="$TMP/neg"
mkdir -p "$NEG/test"
cp "$INSTALLER" "$NEG/install-plist.sh"
# install-plist.sh resolves KIPI_REPO as ../../.. from its own directory, so the
# scratch copy needs that depth to exist. Content is irrelevant to this probe.
mkdir -p "$NEG/../../.." 2>/dev/null || true
cat > "$NEG/com.kipi.broken-probe.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.kipi.broken-probe</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>__KIPI_REPO__/ok.sh</string>
  </array>
  <key>StandardOutPath</key><string>__UNRESOLVED_TOKEN__/out.log</string>
</dict></plist>
PLIST

set +e
bash "$NEG/install-plist.sh" com.kipi.broken-probe --render-only "$TMP/broken.plist" >/dev/null 2>&1
BROKEN_EXIT=$?
set -e

# __UNRESOLVED_TOKEN__ used to render fine: the guard grepped for the specific
# names it substitutes, so any other spelling passed. That allowlist is how
# automation/com.kipi.voice-refresh.plist's __ROOT__ went unnoticed while the
# enumerator could not reach it. Since 2026-09-07 assert_rendered matches the
# CLASS (__ANY_TOKEN__), so an unknown token is a rejection, and this is now an
# assertion rather than the info line it was.
cat > "$NEG/com.kipi.noop-probe.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Repo</key><string>__KIPI_REPO__</string></dict></plist>
PLIST
# Neuter the substitution so the known placeholder survives the render.
sed -i.bak 's|^  sed -e .*$|  cat "$TEMPLATE"|' "$NEG/install-plist.sh"
rm -f "$NEG/install-plist.sh.bak"

set +e
bash "$NEG/install-plist.sh" com.kipi.noop-probe --render-only "$TMP/noop.plist" >/dev/null 2>&1
NOOP_EXIT=$?
set -e

if [ "$NOOP_EXIT" -eq 0 ]; then
  fail "negative self-test: a no-op renderer left __KIPI_REPO__ in place and the installer still exited 0"
else
  pass "negative self-test: no-op render rejected (exit $NOOP_EXIT)"
fi

# Sanity: the same neutered installer on a template with NO placeholder still
# passes, proving the rejection above came from the placeholder, not the sed edit.
cat > "$NEG/com.kipi.clean-probe.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Repo</key><string>/tmp/clean</string></dict></plist>
PLIST
set +e
bash "$NEG/install-plist.sh" com.kipi.clean-probe --render-only "$TMP/clean.plist" >/dev/null 2>&1
CLEAN_EXIT=$?
set -e
if [ "$CLEAN_EXIT" -eq 0 ]; then
  pass "negative self-test control: placeholder-free template still passes"
else
  fail "negative self-test control: placeholder-free template failed (exit $CLEAN_EXIT), so the probe proves nothing"
fi

if [ "$BROKEN_EXIT" -ne 0 ]; then
  pass "an UNKNOWN placeholder is rejected too (exit $BROKEN_EXIT), so the guard covers the class"
else
  fail "unknown-token render exited 0: assert_rendered is back to an allowlist of known placeholders, which is how __ROOT__ went unnoticed"
fi

echo
if [ "$FAILS" -eq 0 ]; then
  echo "test-install-plist.sh: PASS"
  exit 0
fi
echo "test-install-plist.sh: FAIL ($FAILS)"
exit 1
