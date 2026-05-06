#!/usr/bin/env bash
set -euo pipefail

# ── Windows Git Bash fix ───────────────────────────────────────────────────────
if [[ "$(uname -s)" =~ ^(MINGW|MSYS) ]]; then
  export CLOUDSDK_PYTHON="$(cygpath -w "${HOME}")/AppData/Local/Python/bin/python.exe"
fi
# ──────────────────────────────────────────────────────────────────────────────

# =============================================================================
# Snowflake Connector Proxy — Cloud Run + Global LB + Cloud Armor
# =============================================================================
# Traffic flow:
#   Gemini Enterprise connector
#       │  HTTPS  →  https://<LB_DOMAIN>/...
#       ▼
#   Cloud Armor  (GCP IPs allowed; /oauth/token-request always allowed)
#       ▼
#   Global HTTPS Load Balancer  →  Serverless NEG
#       ▼
#   Cloud Run  (nginx — proxies all traffic to Snowflake)
#       │  --ingress=internal-and-cloud-load-balancing  (direct URL blocked)
#       │  --vpc-egress=all-traffic
#       ▼
#   Serverless VPC Access Connector
#       ▼
#   Cloud NAT  ──►  Static External IP  (allowlisted in Snowflake network policy)
#       ▼
#   Snowflake
#
# Usage:
#   bash deploy/setup_psc_proxy.sh
# =============================================================================

# ── Load .env ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: .env not found at ${ENV_FILE}" >&2
  echo "       Copy .env.example to .env and fill in your values." >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

: "${PROJECT_ID:?PROJECT_ID must be set in .env}"
: "${REGION:?REGION must be set in .env}"
: "${VPC_NETWORK:?VPC_NETWORK must be set in .env}"
: "${SNOWFLAKE_HOST:?SNOWFLAKE_HOST must be set in .env}"
: "${SNOWFLAKE_PORT:?SNOWFLAKE_PORT must be set in .env}"
: "${NAT_IP_NAME:?NAT_IP_NAME must be set in .env}"
: "${NAT_ROUTER_NAME:?NAT_ROUTER_NAME must be set in .env}"
: "${NAT_GATEWAY_NAME:?NAT_GATEWAY_NAME must be set in .env}"
: "${VPC_CONNECTOR_NAME:?VPC_CONNECTOR_NAME must be set in .env}"
: "${VPC_CONNECTOR_SUBNET:?VPC_CONNECTOR_SUBNET must be set in .env}"
: "${CLOUD_RUN_SERVICE_NAME:?CLOUD_RUN_SERVICE_NAME must be set in .env}"
: "${AR_REPO:?AR_REPO must be set in .env}"
: "${LB_DOMAIN:?LB_DOMAIN must be set in .env}"
CLOUD_DNS_ZONE="${CLOUD_DNS_ZONE:-}"
# ──────────────────────────────────────────────────────────────────────────────

_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/proxy:latest"
_PROXY_DIR="${SCRIPT_DIR}/../proxy"

echo ""
echo "=== Snowflake Connector Proxy Setup (Cloud Run + LB) ==="
echo "  Project:        ${PROJECT_ID}"
echo "  Region:         ${REGION}"
echo "  VPC:            ${VPC_NETWORK} (connector subnet: ${VPC_CONNECTOR_SUBNET})"
echo "  Snowflake host: ${SNOWFLAKE_HOST}:${SNOWFLAKE_PORT}"
echo "  Image:          ${_IMAGE}"
echo "  LB domain:      ${LB_DOMAIN}"
echo ""

# ── Step 1: Enable required APIs ─────────────────────────────────────────────
echo "=== Step 1: Enabling required GCP APIs ==="
gcloud services enable \
    compute.googleapis.com \
    run.googleapis.com \
    vpcaccess.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    networkservices.googleapis.com \
    --project="${PROJECT_ID}"
echo "  Done."

# ── Step 2: Reserve static external IP (regional, for Cloud NAT) ─────────────
echo ""
echo "=== Step 2: Reserving static external IP (egress — for Snowflake allowlist) ==="
if ! gcloud compute addresses describe "${NAT_IP_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute addresses create "${NAT_IP_NAME}" \
      --region="${REGION}" --project="${PROJECT_ID}" --network-tier=PREMIUM
  echo "  Created: ${NAT_IP_NAME}"
else
  echo "  Already exists: ${NAT_IP_NAME}"
fi
NAT_IP_ADDRESS=$(gcloud compute addresses describe "${NAT_IP_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(address)")
echo "  Static IP: ${NAT_IP_ADDRESS}"

# ── Step 3: Cloud Router ──────────────────────────────────────────────────────
echo ""
echo "=== Step 3: Cloud Router ==="
if ! gcloud compute routers describe "${NAT_ROUTER_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute routers create "${NAT_ROUTER_NAME}" \
      --network="${VPC_NETWORK}" \
      --region="${REGION}" --project="${PROJECT_ID}"
  echo "  Created: ${NAT_ROUTER_NAME}"
else
  echo "  Already exists: ${NAT_ROUTER_NAME}"
fi

# ── Step 4: Cloud NAT ─────────────────────────────────────────────────────────
echo ""
echo "=== Step 4: Cloud NAT ==="
if ! gcloud compute routers nats describe "${NAT_GATEWAY_NAME}" \
    --router="${NAT_ROUTER_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute routers nats create "${NAT_GATEWAY_NAME}" \
      --router="${NAT_ROUTER_NAME}" \
      --region="${REGION}" --project="${PROJECT_ID}" \
      --nat-external-ip-pool="${NAT_IP_NAME}" \
      --nat-custom-subnet-ip-ranges="${VPC_CONNECTOR_SUBNET}"
  echo "  Created: ${NAT_GATEWAY_NAME} (scoped to ${VPC_CONNECTOR_SUBNET})"
else
  echo "  Already exists: ${NAT_GATEWAY_NAME}"
fi

# ── Step 5: Artifact Registry repository ─────────────────────────────────────
echo ""
echo "=== Step 5: Artifact Registry repository ==="
if ! gcloud artifacts repositories describe "${AR_REPO}" \
    --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud artifacts repositories create "${AR_REPO}" \
      --repository-format=docker \
      --location="${REGION}" \
      --project="${PROJECT_ID}"
  echo "  Created: ${AR_REPO}"
else
  echo "  Already exists: ${AR_REPO}"
fi
_PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" \
    --format="value(projectNumber)")
gcloud artifacts repositories add-iam-policy-binding "${AR_REPO}" \
    --location="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${_PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
    --role="roles/artifactregistry.writer" \
    --condition=None &>/dev/null
echo "  Cloud Build has Artifact Registry write access."

# ── Step 6: Build and push Docker image ──────────────────────────────────────
echo ""
echo "=== Step 6: Building and pushing proxy image via Cloud Build ==="
gcloud builds submit "${_PROXY_DIR}" \
    --tag="${_IMAGE}" \
    --project="${PROJECT_ID}"
echo "  Image pushed: ${_IMAGE}"

# ── Step 7: Serverless VPC Access Connector ───────────────────────────────────
echo ""
echo "=== Step 7: Serverless VPC Access Connector ==="
if ! gcloud compute networks vpc-access connectors describe "${VPC_CONNECTOR_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute networks vpc-access connectors create "${VPC_CONNECTOR_NAME}" \
      --region="${REGION}" \
      --project="${PROJECT_ID}" \
      --subnet="${VPC_CONNECTOR_SUBNET}"
  echo "  Created: ${VPC_CONNECTOR_NAME} (subnet: ${VPC_CONNECTOR_SUBNET})"
else
  echo "  Already exists: ${VPC_CONNECTOR_NAME}"
fi

# ── Step 8: Deploy Cloud Run service ─────────────────────────────────────────
# --ingress=internal-and-cloud-load-balancing: raw Cloud Run URL is blocked;
#   all traffic must enter via the Global LB (and therefore Cloud Armor).
# --vpc-egress=all-traffic: every outbound byte goes through Cloud NAT so
#   Snowflake always sees the static IP.
echo ""
echo "=== Step 8: Deploying Cloud Run service ==="
gcloud run deploy "${CLOUD_RUN_SERVICE_NAME}" \
    --image="${_IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --vpc-connector="${VPC_CONNECTOR_NAME}" \
    --vpc-egress=all-traffic \
    --set-env-vars="SNOWFLAKE_HOST=${SNOWFLAKE_HOST},SNOWFLAKE_PORT=${SNOWFLAKE_PORT}" \
    --port=8080 \
    --cpu=1 \
    --memory=512Mi \
    --max-instances=3 \
    --ingress=internal-and-cloud-load-balancing \
    --allow-unauthenticated
echo "  Deployed: ${CLOUD_RUN_SERVICE_NAME}"

# ── Step 9: Global static IP for the Load Balancer ───────────────────────────
echo ""
echo "=== Step 9: Reserving global static IP for Load Balancer ==="
if ! gcloud compute addresses describe "${CLOUD_RUN_SERVICE_NAME}-lb-ip" \
    --global --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute addresses create "${CLOUD_RUN_SERVICE_NAME}-lb-ip" \
      --global --project="${PROJECT_ID}"
  echo "  Created: ${CLOUD_RUN_SERVICE_NAME}-lb-ip"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-lb-ip"
fi
_LB_IP=$(gcloud compute addresses describe "${CLOUD_RUN_SERVICE_NAME}-lb-ip" \
    --global --project="${PROJECT_ID}" --format="value(address)")
echo "  LB IP: ${_LB_IP}"

# ── Step 9b: DNS A record ─────────────────────────────────────────────────────
echo ""
echo "=== Step 9b: DNS A record for ${LB_DOMAIN} ==="
if [[ -n "${CLOUD_DNS_ZONE}" ]]; then
  _DNS_NAME="${LB_DOMAIN}."
  if gcloud dns record-sets describe "${_DNS_NAME}" \
      --zone="${CLOUD_DNS_ZONE}" --type=A \
      --project="${PROJECT_ID}" &>/dev/null; then
    echo "  Already exists: ${_DNS_NAME} A ${_LB_IP}"
  else
    gcloud dns record-sets create "${_DNS_NAME}" \
        --zone="${CLOUD_DNS_ZONE}" \
        --type=A \
        --ttl=300 \
        --rrdatas="${_LB_IP}" \
        --project="${PROJECT_ID}"
    echo "  Created: ${_DNS_NAME} A ${_LB_IP} (TTL 300)"
  fi
else
  echo "  CLOUD_DNS_ZONE not set — create DNS A record manually:"
  echo "    ${LB_DOMAIN}  →  ${_LB_IP}  (A record, TTL 300)"
fi

# ── Step 10: Google-managed SSL certificate ───────────────────────────────────
echo ""
echo "=== Step 10: Google-managed SSL certificate ==="
if ! gcloud compute ssl-certificates describe "${CLOUD_RUN_SERVICE_NAME}-cert" \
    --global --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute ssl-certificates create "${CLOUD_RUN_SERVICE_NAME}-cert" \
      --domains="${LB_DOMAIN}" \
      --global --project="${PROJECT_ID}"
  echo "  Created: ${CLOUD_RUN_SERVICE_NAME}-cert (provisioning ~15 min after DNS propagates)"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-cert"
fi

# ── Step 11: Serverless NEG ───────────────────────────────────────────────────
echo ""
echo "=== Step 11: Serverless NEG ==="
if ! gcloud compute network-endpoint-groups describe "${CLOUD_RUN_SERVICE_NAME}-neg" \
    --region="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute network-endpoint-groups create "${CLOUD_RUN_SERVICE_NAME}-neg" \
      --region="${REGION}" \
      --network-endpoint-type=serverless \
      --cloud-run-service="${CLOUD_RUN_SERVICE_NAME}" \
      --project="${PROJECT_ID}"
  echo "  Created: ${CLOUD_RUN_SERVICE_NAME}-neg"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-neg"
fi

# ── Step 12: Backend service ──────────────────────────────────────────────────
echo ""
echo "=== Step 12: Backend service ==="
if ! gcloud compute backend-services describe "${CLOUD_RUN_SERVICE_NAME}-backend" \
    --global --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute backend-services create "${CLOUD_RUN_SERVICE_NAME}-backend" \
      --global --project="${PROJECT_ID}"
  gcloud compute backend-services add-backend "${CLOUD_RUN_SERVICE_NAME}-backend" \
      --global \
      --network-endpoint-group="${CLOUD_RUN_SERVICE_NAME}-neg" \
      --network-endpoint-group-region="${REGION}" \
      --project="${PROJECT_ID}"
  echo "  Created: ${CLOUD_RUN_SERVICE_NAME}-backend"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-backend"
fi

# ── Step 13: Global HTTPS Load Balancer ──────────────────────────────────────
echo ""
echo "=== Step 13: Global HTTPS Load Balancer ==="
if ! gcloud compute url-maps describe "${CLOUD_RUN_SERVICE_NAME}-urlmap" \
    --global --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute url-maps create "${CLOUD_RUN_SERVICE_NAME}-urlmap" \
      --default-service="${CLOUD_RUN_SERVICE_NAME}-backend" \
      --global --project="${PROJECT_ID}"
  gcloud compute target-https-proxies create "${CLOUD_RUN_SERVICE_NAME}-https-proxy" \
      --url-map="${CLOUD_RUN_SERVICE_NAME}-urlmap" \
      --ssl-certificates="${CLOUD_RUN_SERVICE_NAME}-cert" \
      --global --project="${PROJECT_ID}"
  gcloud compute forwarding-rules create "${CLOUD_RUN_SERVICE_NAME}-fwd" \
      --global \
      --target-https-proxy="${CLOUD_RUN_SERVICE_NAME}-https-proxy" \
      --address="${CLOUD_RUN_SERVICE_NAME}-lb-ip" \
      --ports=443 \
      --project="${PROJECT_ID}"
  echo "  Created: URL map → HTTPS proxy → forwarding rule"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-urlmap"
fi

# ── Step 14: Cloud Armor security policy ──────────────────────────────────────
# Requires Cloud Armor Enterprise on the project.
# Rules (evaluated in priority order, lowest number first):
#   800  — allow /oauth/token-request unconditionally: Gemini's server-to-server
#           token exchange may originate from Google Workspace infrastructure
#           whose IPs are not in the GCP public cloud IP list.
#   1000 — allow all Google Cloud public IPs (iplist-public-clouds-gcp).
#   default — deny-403 everything else.
echo ""
echo "=== Step 14: Cloud Armor security policy ==="
if ! gcloud compute security-policies describe "${CLOUD_RUN_SERVICE_NAME}-armor" \
    --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute security-policies create "${CLOUD_RUN_SERVICE_NAME}-armor" \
      --description="Allow GCP source IPs; always allow OAuth token-request path" \
      --project="${PROJECT_ID}"
  # Rule 800: token endpoint must always reach Cloud Run (server-to-server exchange)
  gcloud compute security-policies rules create 800 \
      --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
      --expression="request.path.startsWith('/oauth/token-request')" \
      --action=allow \
      --project="${PROJECT_ID}"
  # Rule 1000: allow all GCP public cloud source IPs
  gcloud compute security-policies rules create 1000 \
      --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
      --expression="evaluateThreatIntelligence('iplist-public-clouds-gcp')" \
      --action=allow \
      --project="${PROJECT_ID}"
  # Default rule: deny everything else
  gcloud compute security-policies rules update 2147483647 \
      --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
      --action=deny-403 \
      --project="${PROJECT_ID}"
  echo "  Created: ${CLOUD_RUN_SERVICE_NAME}-armor (rules 800, 1000, default-deny)"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-armor"
fi
# Attach policy to backend (idempotent — safe to re-run)
gcloud compute backend-services update "${CLOUD_RUN_SERVICE_NAME}-backend" \
    --global \
    --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
    --project="${PROJECT_ID}"
echo "  Attached to backend: ${CLOUD_RUN_SERVICE_NAME}-backend"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║               Snowflake Proxy Setup Complete                        ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║"
echo "║  Static outbound IP (allowlist in Snowflake):"
echo "║    ${NAT_IP_ADDRESS}"
echo "║"
if [[ -n "${CLOUD_DNS_ZONE}" ]]; then
  echo "║  DNS A record created automatically in zone: ${CLOUD_DNS_ZONE}"
  echo "║    ${LB_DOMAIN}  →  ${_LB_IP}"
else
  echo "║  ACTION REQUIRED — create DNS A record:"
  echo "║    ${LB_DOMAIN}  →  ${_LB_IP}"
fi
echo "║"
echo "║  In Gemini Enterprise → connector configuration:"
echo "║    MCP URL:           https://${LB_DOMAIN}/"
echo "║    Authorization URL: https://${LB_DOMAIN}/oauth/authorize"
echo "║    Token URL:         https://${LB_DOMAIN}/oauth/token-request"
echo "║"
echo "║  Direct Cloud Run URL is ingress-restricted (not publicly reachable)."
echo "║  Cloud Armor: GCP IPs allowed; /oauth/token-request always allowed."
echo "║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Snowflake — run to allowlist the static egress IP:"
echo "    ALTER NETWORK POLICY <your_policy_name>"
echo "      ADD ALLOWED_IP_LIST = ('${NAT_IP_ADDRESS}/32');"
echo ""
echo "  Verify the proxy is forwarding correctly:"
echo "    curl -si https://${LB_DOMAIN}/api/v2/ping | head -10"
echo ""
