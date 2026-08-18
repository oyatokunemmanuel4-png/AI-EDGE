#!/usr/bin/env bash
#
# Deploy the AI-EDGE governance chaincode as a SERVICE (CCaaS) to the running
# WSL Fabric network. The peer connects to a long-running chaincode container
# over gRPC and never builds an image itself — so this works with Docker's
# containerd image store (the legacy peer-build path does not). Runtime-agnostic
# and the same model used in Kubernetes/production.
#
# Org1-only endorsement (Org2's host port is remapped for the Windows reserved
# range; see wsl_network.sh). Sufficient for a prototype ledger.
#
# Usage (from Windows):
#   wsl -d Ubuntu-24.04 -u root -e bash /root/aiedge/deploy_governance_ccaas.sh
set -e

FAB="${FAB_HOME:-/root/aiedge/fabric-samples}"
TN="$FAB/test-network"
CC_SRC="${CC_SRC:-/root/aiedge/chaincode/governance}"
CC_NAME=governance
CHANNEL=governance
CC_LABEL=governance_1.0

export PATH="$FAB/bin:$PATH"
export FABRIC_CFG_PATH="$FAB/config"
ORDERER_CA="$TN/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"

ORG1_TLS="$TN/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_TLS="$TN/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"

org1() {
  export CORE_PEER_TLS_ENABLED=true
  export CORE_PEER_LOCALMSPID=Org1MSP
  export CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_TLS"
  export CORE_PEER_MSPCONFIGPATH="$TN/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
  export CORE_PEER_ADDRESS=localhost:7051
}

org2() {
  # Host port remapped 9051 -> 11051 (Windows reserved range); see wsl_network.sh.
  export CORE_PEER_TLS_ENABLED=true
  export CORE_PEER_LOCALMSPID=Org2MSP
  export CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_TLS"
  export CORE_PEER_MSPCONFIGPATH="$TN/organizations/peerOrganizations/org2.example.com/users/Admin@org2.example.com/msp"
  export CORE_PEER_ADDRESS=localhost:11051
}

# Docker network the peers run on (test-network default: fabric_test).
NET=$(docker network ls --format '{{.Name}}' | grep -E '^fabric_test$|_test$|fabric' | head -1)
echo "docker network: ${NET:?could not find the fabric docker network}"

cd "$CC_SRC"

echo "=== build CCaaS image (BuildKit — containerd-compatible) ==="
docker build -t governance-ccaas:1.0 .

# Deterministic packaging: fixed order/owner/mtime + gzip -n so the package id is
# STABLE across runs (non-deterministic tar previously produced a new id each run,
# corrupting the approval). Package id is read via calculatepackageid — a single,
# unambiguous value (never parse queryinstalled, which can list many packages).
det_tar() { local out="$1"; shift; tar --sort=name --owner=0 --group=0 --numeric-owner --mtime='2020-01-01 00:00:00' -cf - "$@" | gzip -n -c > "$out"; }

echo "=== package external (ccaas) chaincode (deterministic) ==="
rm -f code.tar.gz "${CC_NAME}.tar.gz"
det_tar code.tar.gz connection.json
det_tar "${CC_NAME}.tar.gz" metadata.json code.tar.gz

org1
PKGID=$(peer lifecycle chaincode calculatepackageid "${CC_NAME}.tar.gz")
echo "package id: ${PKGID:?could not compute package id}"

echo "=== install on org1 (idempotent) ==="
peer lifecycle chaincode install "${CC_NAME}.tar.gz" 2>&1 | tail -2 || true

# Next sequence = (current committed sequence) + 1, so a fresh definition
# supersedes any earlier (possibly corrupted) one.
SEQ=$(peer lifecycle chaincode querycommitted -C "$CHANNEL" -n "$CC_NAME" 2>/dev/null | sed -n 's/.*Sequence: \([0-9]\+\).*/\1/p' | head -1)
NEXT=$(( ${SEQ:-0} + 1 ))
echo "deploying sequence: $NEXT"

echo "=== (re)start chaincode service container ==="
docker rm -f governance_ccaas >/dev/null 2>&1 || true
docker run -d --name governance_ccaas --network "$NET" \
  -e CHAINCODE_SERVER_ADDRESS=0.0.0.0:9999 \
  -e CHAINCODE_ID="$PKGID" \
  governance-ccaas:1.0
sleep 4
docker logs governance_ccaas 2>&1 | tail -6

# The _lifecycle commit endorsement policy defaults to MAJORITY of orgs, so both
# orgs must APPROVE (approval needs neither install nor a running chaincode on
# org2). The chaincode endorsement policy for invokes stays OR('Org1MSP.member'),
# so only org1 endorses actual transactions.
echo "=== approve for org1 (seq $NEXT) ==="
org1
peer lifecycle chaincode approveformyorg -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com \
  --channelID "$CHANNEL" --name "$CC_NAME" --version 1.0 --package-id "$PKGID" --sequence "$NEXT" \
  --signature-policy "OR('Org1MSP.member')" --tls --cafile "$ORDERER_CA"

echo "=== approve for org2 (seq $NEXT) ==="
org2
peer lifecycle chaincode approveformyorg -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com \
  --channelID "$CHANNEL" --name "$CC_NAME" --version 1.0 --package-id "$PKGID" --sequence "$NEXT" \
  --signature-policy "OR('Org1MSP.member')" --tls --cafile "$ORDERER_CA"

echo "=== commit (both orgs endorse the lifecycle commit) ==="
org1
peer lifecycle chaincode commit -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com \
  --channelID "$CHANNEL" --name "$CC_NAME" --version 1.0 --sequence "$NEXT" \
  --signature-policy "OR('Org1MSP.member')" --tls --cafile "$ORDERER_CA" \
  --peerAddresses localhost:7051 --tlsRootCertFiles "$ORG1_TLS" \
  --peerAddresses localhost:11051 --tlsRootCertFiles "$ORG2_TLS"

echo "=== committed ==="
peer lifecycle chaincode querycommitted --channelID "$CHANNEL" --name "$CC_NAME" --tls --cafile "$ORDERER_CA"
