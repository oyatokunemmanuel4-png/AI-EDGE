#!/usr/bin/env bash
#
# Submit one governance decision to the ledger (RecordDecision) and print the
# ledger transaction id on stdout. Reads the decision JSON from stdin.
# Used by aiedge.ledger.fabric_sink.build_wsl_cli_transport.
set -e

FAB="${FAB_HOME:-/root/aiedge/fabric-samples}"
TN="$FAB/test-network"
export PATH="$FAB/bin:$PATH"
export FABRIC_CFG_PATH="$FAB/config"
ORDERER_CA="$TN/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"

export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ROOTCERT_FILE="$TN/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
export CORE_PEER_MSPCONFIGPATH="$TN/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
export CORE_PEER_ADDRESS=localhost:7051

DECISION="$(cat)"
DECISION="${DECISION#$'\xEF\xBB\xBF'}"  # strip a leading UTF-8 BOM if the caller added one
ARGS=$(jq -cn --arg d "$DECISION" '{function:"RecordDecision",Args:[$d]}')

peer chaincode invoke -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com \
  --channelID governance --name governance --tls --cafile "$ORDERER_CA" \
  --peerAddresses localhost:7051 --tlsRootCertFiles "$CORE_PEER_TLS_ROOTCERT_FILE" \
  -c "$ARGS" --waitForEvent >/tmp/aiedge_invoke.out 2>&1 || { cat /tmp/aiedge_invoke.out >&2; exit 1; }

# The chaincode returns the tx id as its payload; extract it (fallback: empty).
grep -oE 'payload:"[a-f0-9]+"' /tmp/aiedge_invoke.out | head -1 | sed 's/payload:"\(.*\)"/\1/'
