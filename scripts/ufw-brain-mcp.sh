#!/usr/bin/env bash
# Let ONLY the brain's container reach the Warden's /mcp/ through `tailscale serve`.
#
# The brain sandbox's egress leaves its container on the openshell-docker bridge and hits the
# host's tailnet address; ufw's default "deny incoming" dropped it ([UFW BLOCK] IN=br-…
# SRC=172.18.0.2 DST=100.81.50.38 DPT=443), so the brain never reached its MCP tools.
# This keeps ufw on and keeps exactly one rule: brain container IP -> tailnet IP, TCP 443, on
# that bridge. The container IP and bridge can change when the brain restarts, so this is
# idempotent, removes every other rule carrying its tag (exact field comparison), and runs
# from restart.sh, install-brain.sh and a 2-minute systemd timer. Nothing public changes.
set -euo pipefail
BRAIN="${CUSTODY_BRAIN_SANDBOX:-custody-brain}"
TAG="custody-brain-mcp"

src="" bridge="" dst=""
container=$(docker ps -q --filter "name=openshell-default--${BRAIN}-" | head -1)
if [ -n "$container" ]; then
  network=$(docker inspect "$container" -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}')
  src=$(docker inspect "$container" -f "{{(index .NetworkSettings.Networks \"$network\").IPAddress}}")
  bridge="br-$(docker network inspect "$network" -f '{{.Id}}' | cut -c1-12)"
  dst=$(tailscale ip -4 | head -1)
fi

# Our tagged rules, as "<number> <to> <port/proto> <iface> <from>", compared field by field.
# Any that isn't exactly the wanted rule goes, also (above all) when the brain is down.
sudo ufw status numbered |
  awk -v tag="# $TAG" '
    index($0, tag) {
      line = $0; sub(/^\[ */, "", line); num = line; sub(/\].*/, "", num)
      sub(/^[0-9]+\] */, "", line)   # "100.81.50.38 443/tcp on br-x ALLOW IN 172.18.0.2 # tag"
      split(line, f, /[ \t]+/)
      print num, f[1], f[2], f[4], f[7]
    }' |
  while read -r num to port iface from; do
    if [ -z "$src" ] || [ "$to" != "$dst" ] || [ "$port" != "443/tcp" ] ||
       [ "$iface" != "$bridge" ] || [ "$from" != "$src" ]; then
      echo "$num"
    fi
  done | sort -rn | while read -r num; do sudo ufw --force delete "$num" >/dev/null; done

if [ -z "$src" ] || [ -z "$dst" ]; then
  echo "ufw: brain not running; no $TAG rule kept"
  exit 1
fi
sudo ufw allow in on "$bridge" from "$src" to "$dst" port 443 proto tcp comment "$TAG" >/dev/null
echo "ufw: ALLOW IN on $bridge from $src to $dst port 443 proto tcp ($TAG)"
