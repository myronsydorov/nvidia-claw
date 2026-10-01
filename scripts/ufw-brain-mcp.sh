#!/usr/bin/env bash
# Let ONLY the brain's container reach the Warden's /mcp/ through `tailscale serve`.
#
# The brain sandbox's egress leaves its container on the openshell-docker bridge and hits the
# host's tailnet address; ufw's default "deny incoming" dropped it ([UFW BLOCK] IN=br-…
# SRC=172.18.0.2 DST=100.81.50.38 DPT=443), so the brain never reached its MCP tools.
# This keeps ufw on and adds exactly one rule: brain container IP -> tailnet IP, TCP 443, on
# that bridge. The container IP and bridge can change when the brain restarts, so this is
# idempotent and removes its own stale rules (tagged by comment). Nothing public changes.
set -euo pipefail
BRAIN="${CUSTODY_BRAIN_SANDBOX:-custody-brain}"
TAG="custody-brain-mcp"

container=$(docker ps -q --filter "name=openshell-default--${BRAIN}-" | head -1)
[ -n "$container" ] || { echo "brain container not running"; exit 1; }
network=$(docker inspect "$container" -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')
src=$(docker inspect "$container" -f "{{(index .NetworkSettings.Networks \"$network\").IPAddress}}")
bridge="br-$(docker network inspect "$network" -f '{{.Id}}' | cut -c1-12)"
dst=$(tailscale ip -4 | head -1)
[ -n "$src" ] && [ -n "$dst" ] || { echo "could not work out the brain IP or tailnet IP"; exit 1; }

want="ALLOW IN on $bridge from $src to $dst port 443 proto tcp"
# Remove our older rules that no longer match (highest number first, so numbers stay valid).
{ sudo ufw status numbered | grep "# $TAG" || true; } | while read -r line; do
  num=$(printf '%s' "$line" | sed -E 's/^\[ *([0-9]+)\].*/\1/')
  if ! printf '%s' "$line" | grep -q "$dst 443/tcp on $bridge" ||
     ! printf '%s' "$line" | grep -q "$src"; then
    echo "$num"
  fi
done | sort -rn | while read -r num; do yes | sudo ufw delete "$num" >/dev/null; done
sudo ufw allow in on "$bridge" from "$src" to "$dst" port 443 proto tcp comment "$TAG" >/dev/null
echo "ufw: $want ($TAG)"
