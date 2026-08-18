#!/usr/bin/env bash
#
# Query a governance decision from the ledger by decision_id (arg 1), or all
# decisions if no id is given. Prints JSON on stdout.
set -e

FAB="${FAB_HOME:-/root/aiedge/fabric-samples}"
TN="$FAB/test-network"
export PATH="$FAB/bin:$PATH"
export FABRIC_CFG_PATH="$FAB/config"

export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ROOTCERT_FILE="$TN/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
export CORE_PEER_MSPCONFIGPATH="$TN/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
export CORE_PEER_ADDRESS=localhost:7051

if [ -n "$1" ]; then
  peer chaincode query --channelID governance --name governance \
    -c "{\"function\":\"GetDecision\",\"Args\":[\"$1\"]}"
else
  peer chaincode query --channelID governance --name governance \
    -c '{"function":"GetAllDecisions","Args":[]}'
fi
