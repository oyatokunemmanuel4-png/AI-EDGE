#!/usr/bin/env bash
#
# AI-EDGE Fabric dev network control — runs INSIDE WSL2 Ubuntu.
#
# Why WSL2: Hyperledger's test-network scripts break under native Windows Git
# Bash (MSYS path translation mangles container mount paths). Ubuntu is the
# supported environment. Docker Desktop's WSL integration is enabled for the
# Ubuntu distro, so containers share the same daemon/images as Windows.
#
# Why org2 on host port 11051: Windows reserves the TCP range 9035-9134
# (Hyper-V/WSL dynamic reservation), so Docker cannot publish org2's default
# host port 9051. We remap ONLY the host side (11051 -> container 9051); the
# peer still listens on 9051 internally, so inter-peer gossip/endorsement over
# the Docker network is unchanged. Clearing the reservation instead needs admin
# (`net stop winnat && net start winnat`); the remap needs none.
#
# Usage (from Windows PowerShell):
#   wsl -d Ubuntu-24.04 -u root -e bash /root/aiedge/wsl_network.sh up
#   wsl -d Ubuntu-24.04 -u root -e bash /root/aiedge/wsl_network.sh down
#   wsl -d Ubuntu-24.04 -u root -e bash /root/aiedge/wsl_network.sh status
#
set -e

FAB_HOME="${FAB_HOME:-/root/aiedge/fabric-samples}"
CHANNEL="${CHANNEL:-governance}"
ORG2_HOST_PORT="${ORG2_HOST_PORT:-11051}"
TN="$FAB_HOME/test-network"

export PATH="$FAB_HOME/bin:$PATH"
export FABRIC_CFG_PATH="$FAB_HOME/config"

peer_env() {  # $1 = org number (1|2)
  export CORE_PEER_TLS_ENABLED=true
  if [ "$1" = "1" ]; then
    export CORE_PEER_LOCALMSPID=Org1MSP
    export CORE_PEER_ADDRESS=localhost:7051
    export CORE_PEER_TLS_ROOTCERT_FILE=$TN/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt
    export CORE_PEER_MSPCONFIGPATH=$TN/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp
  else
    export CORE_PEER_LOCALMSPID=Org2MSP
    export CORE_PEER_ADDRESS=localhost:$ORG2_HOST_PORT
    export CORE_PEER_TLS_ROOTCERT_FILE=$TN/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt
    export CORE_PEER_MSPCONFIGPATH=$TN/organizations/peerOrganizations/org2.example.com/users/Admin@org2.example.com/msp
  fi
}

cmd_up() {
  cd "$TN"
  # Ensure the org2 host-port remap is applied (idempotent).
  sed -i 's/^      - 9051:9051$/      - '"$ORG2_HOST_PORT"':9051/' compose/compose-test-net.yaml || true

  ./network.sh down >/dev/null 2>&1 || true
  # network.sh's own org2 join uses localhost:9051 and will report a failure —
  # expected because of the remap. We join org2 manually below.
  ./network.sh up createChannel -c "$CHANNEL" 2>&1 | tail -6 || true

  echo "--- joining org2 (host port $ORG2_HOST_PORT) ---"
  cd "$TN"; peer_env 2
  for i in 1 2 3 4 5 6; do
    peer channel join -b ./channel-artifacts/$CHANNEL.block 2>/dev/null && { echo "org2 joined"; break; }
    sleep 4
  done
  cmd_status
}

cmd_down() { cd "$TN"; ./network.sh down; }

cmd_status() {
  cd "$TN"
  echo "--- containers ---"
  docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -Ei 'peer|orderer' || echo 'none running'
  echo "--- org1 channels ---"; peer_env 1; peer channel list 2>/dev/null | tail -2 || true
  echo "--- org2 channels ---"; peer_env 2; peer channel list 2>/dev/null | tail -2 || true
}

case "${1:-status}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  *) echo "usage: $0 {up|down|status}"; exit 1 ;;
esac
