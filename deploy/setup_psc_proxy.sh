#!/usr/bin/env bash
set -euo pipefail

# ── Windows Git Bash fix ───────────────────────────────────────────────────────
# Git Bash cannot exec the Windows App Store Python stub that gcloud's shell
# wrapper resolves to by default. Override CLOUDSDK_PYTHON with the real
# python.exe so gcloud works reliably in subshells. No-op on Linux/macOS.
if [[ "$(uname -s)" =~ ^(MINGW|MSYS) ]]; then
  export CLOUDSDK_PYTHON="$(cygpath -w "${HOME}")/AppData/Local/Python/bin/python.exe"
fi
# ──────────────────────────────────────────────────────────────────────────────

# =============================================================================
# Snowflake Connector Proxy — Cloud Run + VPC Connector Setup
# =============================================================================
# Provisions GCP resources so the Gemini Enterprise connector can reach
# Snowflake through a customer-controlled static egress IP.
#
# Traffic flow:
#   Gemini Enterprise connector
#       │  HTTPS  →  https://<cloud-run-url>/
#       ▼
#   Cloud Run  (nginx — proxies all traffic to Snowflake)
#       │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
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
# ──────────────────────────────────────────────────────────────────────────────

_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/proxy:latest"
_PROXY_DIR="${SCRIPT_DIR}/../proxy"

echo ""
echo "=== Snowflake Connector Proxy Setup (Cloud Run) ==="
echo "  Project:        ${PROJECT_ID}"
echo "  Region:         ${REGION}"
echo "  VPC:            ${VPC_NETWORK} (connector subnet: ${VPC_CONNECTOR_SUBNET})"
echo "  Snowflake host: ${SNOWFLAKE_HOST}:${SNOWFLAKE_PORT}"
echo "  Image:          ${_IMAGE}"
echo ""

# ── Step 1: Enable required APIs ─────────────────────────────────────────────
echo "=== Step 1: Enabling required GCP APIs ==="
gcloud services enable \
    compute.googleapis.com \
    run.googleapis.com \
    vpcaccess.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    --project="${PROJECT_ID}"
echo "  Done."

# ── Step 2: Reserve static external IP (regional, for Cloud NAT) ─────────────
# This is the egress IP that Snowflake's network policy allowlists.
# Must be regional (NOT --global) — Cloud NAT does not accept global addresses.
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
# Scoped to VPC_CONNECTOR_SUBNET so only connector egress picks up the static
# IP. Using --nat-custom-subnet-ip-ranges requires the connector to be created
# with --subnet (a named subnet), not --range (an anonymous CIDR).
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

# Grant Cloud Build write access to the repo
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
# Bridges Cloud Run's egress into the VPC so traffic exits through Cloud NAT
# with the static IP. VPC_CONNECTOR_SUBNET must be a dedicated /28 with no
# other resources — required so Cloud NAT can scope to it by name (Step 4).
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
# --vpc-egress=all-traffic: forces ALL outbound traffic through the VPC
#   connector and therefore through Cloud NAT — without this only RFC-1918
#   traffic uses the connector and Snowflake would see a dynamic Google IP.
# --ingress=all: the Cloud Run URL is publicly accessible so Gemini Enterprise
#   can reach it directly.
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
    --ingress=all \
    --allow-unauthenticated
echo "  Deployed: ${CLOUD_RUN_SERVICE_NAME}"

_RUN_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(status.url)")

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║               Snowflake Proxy Setup Complete                        ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║"
echo "║  Static outbound IP (allowlist in Snowflake):"
echo "║    ${NAT_IP_ADDRESS}"
echo "║"
echo "║  In Gemini Enterprise → connector configuration:"
echo "║    MCP URL:  ${_RUN_URL}/"
echo "║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Snowflake — run to allowlist the static egress IP:"
echo "    ALTER NETWORK POLICY <your_policy_name>"
echo "      ADD ALLOWED_IP_LIST = ('${NAT_IP_ADDRESS}/32');"
echo ""
echo "  Verify the proxy is forwarding correctly:"
echo "    curl -si ${_RUN_URL}/api/v2/ping | head -10"
echo ""
