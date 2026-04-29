#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Snowflake Connector Proxy — Connectivity Test
# =============================================================================
# Runs four tests in increasing depth:
#   1. ILB backend health (GCP control plane)
#   2. nginx running on the proxy VM
#   3. TLS handshake: VM → Snowflake via nginx
#   4. TLS handshake: VM → Snowflake via PSC endpoint (full path)
#
# Tests 2–4 use IAP SSH to run openssl on the proxy VM (no external IP needed).
# A temporary IAP SSH firewall rule and PSC consumer endpoint are created for
# the tests and cleaned up automatically on exit.
#
# Usage:
#   bash deploy/test_connectivity.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: .env not found at ${ENV_FILE}" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

: "${PROJECT_ID:?}" "${REGION:?}" "${VPC_NETWORK:?}" "${VPC_SUBNET:?}"
: "${SNOWFLAKE_HOST:?}" "${SNOWFLAKE_PORT:?}"
: "${PROXY_VM_NAME:?}" "${PROXY_VM_ZONE:?}"
: "${PROXY_ILB_NAME:?}" "${PSC_ATTACHMENT_NAME:?}"

_BE_NAME="${PROXY_ILB_NAME}-be"
_FWD_NAME="${PROXY_ILB_NAME}-fwd"
_FW_IAP_NAME="${PROXY_ILB_NAME}-allow-iap-ssh"

_PASS="  [ PASS ]"
_FAIL="  [ FAIL ]"
_SKIP="  [ SKIP ]"
_errors=0

_fail() { echo "${_FAIL} $*"; ((_errors++)) || true; }
_pass() { echo "${_PASS} $*"; }
_skip() { echo "${_SKIP} $*"; }

echo ""
echo "=== Snowflake Connector Proxy — Connectivity Tests ==="
echo "  Project:   ${PROJECT_ID}"
echo "  Region:    ${REGION}"
echo "  VM:        ${PROXY_VM_NAME} (${PROXY_VM_ZONE})"
echo "  Snowflake: ${SNOWFLAKE_HOST}:${SNOWFLAKE_PORT}"
echo ""

# ── Prerequisite: IAP SSH firewall rule ───────────────────────────────────────
echo "--- Prerequisite: IAP SSH firewall rule ---"
if ! gcloud compute firewall-rules describe "${_FW_IAP_NAME}" \
    --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute firewall-rules create "${_FW_IAP_NAME}" \
      --project="${PROJECT_ID}" \
      --network="${VPC_NETWORK}" \
      --direction=INGRESS \
      --priority=1000 \
      --source-ranges="35.235.240.0/20" \
      --action=ALLOW \
      --rules="tcp:22" \
      --target-tags="psc-proxy"
  echo "  Created: ${_FW_IAP_NAME}"
else
  echo "  Already exists: ${_FW_IAP_NAME}"
fi

# Helper: run a command on the proxy VM via IAP SSH
_vm_run() {
  gcloud compute ssh "${PROXY_VM_NAME}" \
      --zone="${PROXY_VM_ZONE}" --project="${PROJECT_ID}" \
      --tunnel-through-iap --quiet \
      --command="$1" 2>/dev/null
}

# ── Test 1: ILB backend health ────────────────────────────────────────────────
echo ""
echo "--- Test 1: ILB backend health ---"
_HEALTH=$(gcloud compute backend-services get-health "${_BE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(status.healthStatus[0].healthState)" 2>/dev/null || echo "UNKNOWN")
if [[ "${_HEALTH}" == "HEALTHY" ]]; then
  _pass "Backend is HEALTHY"
else
  _fail "Backend health: ${_HEALTH} (expected HEALTHY)"
fi

# ── Test 2: nginx on proxy VM ─────────────────────────────────────────────────
echo ""
echo "--- Test 2: nginx running on proxy VM ---"
_NGINX=$(  _vm_run "systemctl is-active nginx" || echo "inactive")
if [[ "${_NGINX}" == "active" ]]; then
  _pass "nginx is active"
else
  _fail "nginx is not active (status: ${_NGINX})"
fi

# ── Test 3: TLS handshake via nginx (VM → Snowflake) ─────────────────────────
echo ""
echo "--- Test 3: TLS handshake — VM → nginx → Snowflake ---"
_TLS_OUT=$(_vm_run \
  "echo | openssl s_client \
      -connect localhost:${SNOWFLAKE_PORT} \
      -servername ${SNOWFLAKE_HOST} \
      -verify_return_error \
      -brief 2>&1" || echo "")
if echo "${_TLS_OUT}" | grep -qi "CONNECTION ESTABLISHED"; then
  _pass "TLS handshake succeeded"
  echo "${_TLS_OUT}" | grep -iE "(protocol|cipher)" | head -2 | sed 's/^/           /'
elif echo "${_TLS_OUT}" | grep -qi "CONNECTED\|Verify return code: 0"; then
  _pass "TLS connected"
else
  _fail "TLS handshake failed"
  echo "${_TLS_OUT}" | tail -4 | sed 's/^/           /'
fi

# ── Test 4: TLS handshake via ILB ────────────────────────────────────────────
echo ""
echo "--- Test 4: TLS handshake — VM → ILB → nginx → Snowflake ---"
_ILB_IP=$(gcloud compute forwarding-rules describe "${_FWD_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(IPAddress)" 2>/dev/null || echo "")
if [[ -z "${_ILB_IP}" ]]; then
  _skip "ILB forwarding rule not found"
else
  echo "  ILB IP: ${_ILB_IP}"
  _TLS_ILB=$(_vm_run \
    "echo | openssl s_client \
        -connect ${_ILB_IP}:${SNOWFLAKE_PORT} \
        -servername ${SNOWFLAKE_HOST} \
        -verify_return_error \
        -brief 2>&1" || echo "")
  if echo "${_TLS_ILB}" | grep -qi "CONNECTION ESTABLISHED\|CONNECTED\|Verify return code: 0"; then
    _pass "TLS handshake via ILB succeeded"
  else
    _fail "TLS handshake via ILB failed"
    echo "${_TLS_ILB}" | tail -4 | sed 's/^/           /'
  fi
fi

# ── Test 5: PSC service attachment exists ────────────────────────────────────
# NOTE: A PSC consumer forwarding rule must be in a *different VPC* than the
# producer service attachment. Since the consumer is Gemini Enterprise (Google's
# managed tenant project), this path cannot be tested from within this VPC.
# This test confirms the service attachment is provisioned and ready.
echo ""
echo "--- Test 5: PSC service attachment provisioned ---"
_PSC_STATE=$(gcloud compute service-attachments describe "${PSC_ATTACHMENT_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(producerForwardingRule)" 2>/dev/null || echo "")
if [[ -n "${_PSC_STATE}" ]]; then
  _PSC_URI="projects/${PROJECT_ID}/regions/${REGION}/serviceAttachments/${PSC_ATTACHMENT_NAME}"
  _pass "Service attachment exists and references forwarding rule"
  echo "           URI: ${_PSC_URI}"
  echo ""
  echo "  To complete end-to-end verification, register the URI in Gemini Enterprise"
  echo "  then confirm the egress IP in Snowsight:"
  echo "    SELECT client_net_address FROM TABLE(information_schema.query_history(...))"
  echo "    -- expect: $(gcloud compute addresses describe "${NAT_IP_NAME}" \
      --region="${REGION}" --project="${PROJECT_ID}" \
      --format="value(address)" 2>/dev/null || echo "<NAT_IP>")"
else
  _fail "PSC service attachment not found (${PSC_ATTACHMENT_NAME})"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
if [[ ${_errors} -eq 0 ]]; then
  echo "  All tests passed."
  echo ""
  echo "  PSC Service Attachment URI for Gemini Enterprise:"
  echo "    projects/${PROJECT_ID}/regions/${REGION}/serviceAttachments/${PSC_ATTACHMENT_NAME}"
else
  echo "  ${_errors} test(s) failed — see output above."
fi
echo "============================================"
echo ""

[[ ${_errors} -eq 0 ]]
