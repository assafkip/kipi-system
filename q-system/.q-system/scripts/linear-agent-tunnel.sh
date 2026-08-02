#!/usr/bin/env bash
# Cloudflare Tunnel for the Sana Linear agent: a STABLE public URL for the webhook.
#
# WHY A NAMED TUNNEL AND NOT NGROK / A QUICK TUNNEL
# ------------------------------------------------
# The webhook URL is registered INTO the OAuth app. A URL that churns means
# re-registering it, and re-registering spends the founder's authorization clicks
# again. Those clicks are the scarce resource this whole design optimises around, so
# the URL must be stable for free and forever. ngrok's free tier churns. Cloudflare
# QUICK tunnels (trycloudflare.com) also churn on every restart -- they are NOT an
# acceptable substitute here even though they need no domain.
#
# A relay on existing hardware was the other option and was rejected: it adds a
# component we then have to watch, and launchd-health-check.py exists precisely
# because things nobody watches die quietly.
#
# THE PRECONDITION NOBODY MENTIONS
# --------------------------------
# A NAMED tunnel requires a domain already onboarded to Cloudflare (nameservers
# pointed at Cloudflare). Without one, `cloudflared tunnel login` has nothing to
# select and the named-tunnel path is simply unavailable. This script CHECKS that
# rather than assuming it, because discovering it halfway through setup is how a
# ten-minute task becomes an afternoon.
#
# Usage:
#   linear-agent-tunnel.sh check      # preconditions; changes nothing
#   linear-agent-tunnel.sh install    # install cloudflared (no founder action)
#   linear-agent-tunnel.sh create <hostname>   # after founder login
#   linear-agent-tunnel.sh status     # is the tunnel up and serving?
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"
TUNNEL_NAME="${KIPI_TUNNEL_NAME:-sana-linear}"
LOCAL_PORT="${KIPI_LINEAR_AGENT_PORT:-8787}"
CF_DIR="$HOME/.cloudflared"

ok()   { echo "  [ok]   $*"; }
miss() { echo "  [MISS] $*"; }
act()  { echo "  [YOU]  $*"; }

cmd_check() {
  local blockers=0
  echo "=== Sana tunnel preconditions ==="

  if command -v cloudflared >/dev/null 2>&1; then
    ok "cloudflared installed ($(cloudflared --version 2>&1 | head -1))"
  else
    miss "cloudflared not installed -- run: $0 install   (no founder action needed)"
    blockers=$((blockers+1))
  fi

  if [ -f "$CF_DIR/cert.pem" ]; then
    ok "cloudflared logged in (cert.pem present)"
  else
    miss "not logged in to Cloudflare"
    act "cloudflared tunnel login   <- opens a browser, pick the domain. FOUNDER STEP."
    blockers=$((blockers+1))
  fi

  # The precondition that silently decides whether any of this is possible.
  if [ -f "$CF_DIR/cert.pem" ]; then
    if cloudflared tunnel list >/dev/null 2>&1; then
      ok "Cloudflare account reachable; zones available"
    else
      miss "logged in but cannot list tunnels -- check the account has a zone"
      blockers=$((blockers+1))
    fi
  else
    # PROBE, do not warn. A prose caveat about "you'll need a domain on Cloudflare"
    # gets read past; a resolver answer does not. This is read-only DNS -- it changes
    # nothing and needs no credentials, so there is no excuse for guessing instead.
    local found=0
    for d in ${KIPI_TUNNEL_DOMAINS:-ktlystlabs.com kipi.dev}; do
      local ns
      ns="$(dig +short NS "$d" 2>/dev/null | head -1)"
      # Match the cloudflare.com SUFFIX, not an assumed `ns.` prefix. The first
      # version grepped 'ns.cloudflare.com' and read cloudflare.com itself -- whose
      # NS is ns6.cloudflare.com -- as NOT on Cloudflare. A detector that returns a
      # false negative on the most obvious positive case in existence is one a
      # negative self-test catches and a green run never does.
      if echo "$ns" | grep -qiE 'cloudflare\.com\.?$'; then
        ok "$d is on Cloudflare ($ns) -- named tunnel available"
        found=1
      elif [ -n "$ns" ]; then
        miss "$d is NOT on Cloudflare (NS: $ns)"
      fi
    done
    if [ "$found" -eq 0 ]; then
      echo "  [BLOCKER] no probed domain is delegated to Cloudflare."
      echo "            A NAMED tunnel needs a zone on Cloudflare. Without one the"
      echo "            only cloudflared option is a QUICK tunnel, whose URL churns"
      echo "            on every restart -- which respends the founder's OAuth"
      echo "            clicks and is the exact cost this choice was making."
      echo "            Decide the domain BEFORE anyone clicks anything."
      blockers=$((blockers+1))
    fi
  fi

  if lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    ok "receiver listening on :$LOCAL_PORT"
  else
    miss "nothing listening on :$LOCAL_PORT (start linear-agent-receiver.py serve)"
  fi

  echo "=== $blockers blocker(s) ==="
  return $blockers
}

cmd_install() {
  if command -v cloudflared >/dev/null 2>&1; then
    echo "cloudflared already installed"; return 0
  fi
  command -v brew >/dev/null 2>&1 || { echo "homebrew not found"; return 1; }
  echo "installing cloudflared via homebrew..."
  brew install cloudflared
}

cmd_create() {
  local hostname="${1:-}"
  [ -n "$hostname" ] || { echo "usage: $0 create <hostname>"; return 1; }
  [ -f "$CF_DIR/cert.pem" ] || { echo "not logged in -- founder must run: cloudflared tunnel login"; return 1; }

  cloudflared tunnel create "$TUNNEL_NAME" 2>/dev/null || echo "(tunnel may already exist)"

  local uuid
  uuid="$(cloudflared tunnel list --output json 2>/dev/null \
          | python3 -c "import json,sys;print(next((t['id'] for t in json.load(sys.stdin) if t['name']=='$TUNNEL_NAME'),''))" 2>/dev/null)"
  [ -n "$uuid" ] || { echo "could not resolve tunnel id"; return 1; }

  cat > "$CF_DIR/config.yml" <<EOF
tunnel: $uuid
credentials-file: $CF_DIR/$uuid.json

ingress:
  - hostname: $hostname
    service: http://localhost:$LOCAL_PORT
  # Catch-all is REQUIRED by cloudflared; without it the config is rejected.
  - service: http_status:404
EOF

  cloudflared tunnel route dns "$TUNNEL_NAME" "$hostname"
  echo "config written: $CF_DIR/config.yml"
  echo "webhook URL to register in the OAuth app:  https://$hostname/"
}

cmd_status() {
  # A tunnel that is DOWN must be noticed. Silence here is the same failure class as
  # a silently-expired token: the board looks calm while nothing can reach us.
  local hostname="${1:-}"
  if ! pgrep -f "cloudflared.*tunnel.*run" >/dev/null 2>&1; then
    echo "DOWN: no cloudflared tunnel process"
    "$NOTIFY" "Linear agent: Cloudflare tunnel is DOWN. Delegations to Sana cannot reach this machine." 2>/dev/null
    return 1
  fi
  echo "UP: cloudflared running"
  [ -n "$hostname" ] && curl -fsS -o /dev/null -w "  public probe: HTTP %{http_code}\n" "https://$hostname/" 2>/dev/null
  return 0
}

case "${1:-check}" in
  check)   cmd_check ;;
  install) cmd_install ;;
  create)  shift; cmd_create "$@" ;;
  status)  shift; cmd_status "$@" ;;
  *) sed -n '1,30p' "$0"; exit 1 ;;
esac
