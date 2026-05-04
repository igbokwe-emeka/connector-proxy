#!/usr/bin/env bash
set -euo pipefail

# ── Windows Git Bash fix ───────────────────────────────────────────────────────
# Git Bash cannot exec the Windows App Store Python stub that gcloud's shell
# wrapper resolves to by default. Override CLOUDSDK_PYTHON with the real
# python.exe so gcloud works reliably in subshells. No-op on Linux/macOS.
if [[ "$(uname -s)" =~ ^(MINGW|MSYS) ]]; then
  export CLOUDSDK_PYTHON="$(cygpath -w "${HOME}")/AppData/Local/Microsoft/WindowsApps/python.exe"
fi
# ──────────────────────────────────────────────────────────────────────────────

# =============================================================================
# Snowflake Connector Proxy — Cloud Run + VPC Connector Setup
# =============================================================================
# Provisions GCP resources so the Gemini Enterprise connector can reach
# Snowflake through a customer-controlled static egress IP.
#
# Hardening modes (set HARDENING_MODE in .env):
#
#   A  — Secret path gate only (application layer)
#        nginx returns 404 for any URL not containing PROXY_SECRET_PATH.
#        Cloud Run is publicly accessible via its direct URL.
#        No LB, no Cloud Armor required. Low cost.
#
#        Traffic flow:
#          Gemini → Cloud Run (nginx, --ingress=all)
#                     │  secret path gate (404 on wrong path)
#                     ▼
#                   Cloud NAT → Static IP → Snowflake
#
#   B  — Cloud Armor + Global LB only (network layer)
#        Cloud Armor blocks all non-GCP source IPs at the LB edge.
#        Cloud Run ingress locked to LB — direct URL not publicly reachable.
#        Requires Cloud Armor Enterprise subscription.
#
#        Traffic flow:
#          Gemini → Cloud Armor → Global HTTPS LB → Cloud Run (open proxy)
#                                                      │  --ingress=internal-and-cloud-load-balancing
#                                                      ▼
#                                                    Cloud NAT → Static IP → Snowflake
#
#   AB — Both layers (recommended — defence-in-depth)
#        Cloud Armor filters at the network edge; secret path filters at
#        the application layer. Two independent gates must both be bypassed.
#
#        Traffic flow:
#          Gemini → Cloud Armor → Global HTTPS LB → Cloud Run (nginx, secret path gate)
#                                                      │  --ingress=internal-and-cloud-load-balancing
#                                                      ▼
#                                                    Cloud NAT → Static IP → Snowflake
#
# Gemini Enterprise connector endpoint URL (printed at end of script):
#   A only:  https://<cloud-run-url>/<PROXY_SECRET_PATH>/
#   B only:  https://<LB_DOMAIN>/
#   AB:      https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - Docker not required — image is built in the cloud via Cloud Build
#   - .env file populated (copy from .env.example), including:
#       HARDENING_MODE     — A, B, or AB (default AB)
#       PROXY_SECRET_PATH  — required for mode A or AB; openssl rand -hex 16
#       LB_DOMAIN          — required for mode B or AB; domain you control
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

# ── Validate HARDENING_MODE and set mode flags ─────────────────────────────────
HARDENING_MODE="${HARDENING_MODE:-AB}"
case "${HARDENING_MODE}" in
  A)  _USE_SECRET_PATH=true;  _USE_CLOUD_ARMOR=false ;;
  B)  _USE_SECRET_PATH=false; _USE_CLOUD_ARMOR=true  ;;
  AB) _USE_SECRET_PATH=true;  _USE_CLOUD_ARMOR=true  ;;
  *)
    echo "ERROR: HARDENING_MODE must be A, B, or AB (got: '${HARDENING_MODE}')" >&2
    echo "       Set HARDENING_MODE in .env or unset it to use the default (AB)." >&2
    exit 1
    ;;
esac

# ── Validate required .env variables ──────────────────────────────────────────
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

if [[ "${_USE_SECRET_PATH}" == "true" ]]; then
  : "${PROXY_SECRET_PATH:?PROXY_SECRET_PATH must be set when HARDENING_MODE is A or AB — run: openssl rand -hex 16}"
fi
if [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  : "${LB_DOMAIN:?LB_DOMAIN must be set when HARDENING_MODE is B or AB — domain name that will front the Global LB}"
fi
# ──────────────────────────────────────────────────────────────────────────────

_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/proxy:latest"
_PROXY_DIR="${SCRIPT_DIR}/../proxy"
_LB_IP=""

echo ""
echo "=== Snowflake Connector Proxy Setup (Cloud Run) ==="
echo "  Project:        ${PROJECT_ID}"
echo "  Region:         ${REGION}"
echo "  VPC:            ${VPC_NETWORK} (connector subnet: ${VPC_CONNECTOR_SUBNET})"
echo "  Snowflake host: ${SNOWFLAKE_HOST}:${SNOWFLAKE_PORT}"
echo "  Image:          ${_IMAGE}"
echo "  Hardening mode: ${HARDENING_MODE}"
if [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  echo "  LB domain:      ${LB_DOMAIN}"
fi
echo ""

# ── Step 1: Enable required APIs ─────────────────────────────────────────────
# compute.googleapis.com    — Cloud NAT, Cloud Router, Global LB, Cloud Armor
# run.googleapis.com        — Cloud Run service
# vpcaccess.googleapis.com  — Serverless VPC Access Connector
# artifactregistry.googleapis.com — Docker image registry
# cloudbuild.googleapis.com — builds the proxy image without local Docker
# networkservices.googleapis.com  — Global LB URL map / NEG wiring
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
#
# --ingress behaviour depends on HARDENING_MODE:
#   A  — ingress=all: Cloud Run URL is publicly reachable; security comes from
#        the nginx secret path gate (404 for any path not matching PROXY_SECRET_PATH).
#   B/AB — ingress=internal-and-cloud-load-balancing: raw Cloud Run URL is not
#        reachable from the public internet; all traffic must pass through the
#        Global LB and Cloud Armor (Steps 9-14).
#
# PROXY_SECRET_PATH is injected as an env var only when Strategy A is active;
# entrypoint.sh selects the appropriate nginx config template based on whether
# the variable is set.
echo ""
echo "=== Step 8: Deploying Cloud Run service ==="

_ENVVARS="SNOWFLAKE_HOST=${SNOWFLAKE_HOST},SNOWFLAKE_PORT=${SNOWFLAKE_PORT}"
if [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  _INGRESS="internal-and-cloud-load-balancing"
else
  _INGRESS="all"
fi
if [[ "${_USE_SECRET_PATH}" == "true" ]]; then
  _ENVVARS="${_ENVVARS},PROXY_SECRET_PATH=${PROXY_SECRET_PATH}"
fi

gcloud run deploy "${CLOUD_RUN_SERVICE_NAME}" \
    --image="${_IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --vpc-connector="${VPC_CONNECTOR_NAME}" \
    --vpc-egress=all-traffic \
    --set-env-vars="${_ENVVARS}" \
    --port=8080 \
    --cpu=1 \
    --memory=512Mi \
    --max-instances=3 \
    --ingress="${_INGRESS}" \
    --allow-unauthenticated
echo "  Deployed: ${CLOUD_RUN_SERVICE_NAME} (ingress: ${_INGRESS})"

_RUN_URL=$(gcloud run services describe "${CLOUD_RUN_SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(status.url)")

# ── Steps 9–14: Cloud Armor + Global LB (Strategy B / AB only) ───────────────
if [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then

# ── Step 9: Global static IP for the Load Balancer ───────────────────────────
# Must be --global (not regional) — Global HTTPS Load Balancers require a
# global address. Point LB_DOMAIN's DNS A record at this IP after creation;
# the managed certificate (Step 10) won't provision until DNS resolves.
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
echo "  LB IP: ${_LB_IP} → point ${LB_DOMAIN} A record here"

# ── Step 10: Google-managed SSL certificate ───────────────────────────────────
# Google provisions and auto-renews the cert once LB_DOMAIN's A record
# propagates to the LB IP (Step 9). Provisioning typically takes ~15 minutes
# after DNS is live. The cert is attached to the HTTPS proxy in Step 13.
echo ""
echo "=== Step 10: Google-managed SSL certificate ==="
if ! gcloud compute ssl-certificates describe "${CLOUD_RUN_SERVICE_NAME}-cert" \
    --global --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute ssl-certificates create "${CLOUD_RUN_SERVICE_NAME}-cert" \
      --domains="${LB_DOMAIN}" \
      --global --project="${PROJECT_ID}"
  echo "  Created: ${CLOUD_RUN_SERVICE_NAME}-cert (provisioning takes ~15 min after DNS propagates)"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-cert"
fi

# ── Step 11: Serverless NEG pointing at the Cloud Run service ─────────────────
# A Serverless NEG connects the Global LB to a Cloud Run service without
# requiring a VPC. The NEG is regional (matches the Cloud Run region) and is
# attached to the global backend service in Step 12.
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
# The backend service is the LB component that holds the NEG and will carry
# the Cloud Armor policy (attached in Step 14). It must be --global to pair
# with the Global HTTPS LB created in Step 13.
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

# ── Step 13: URL map, HTTPS proxy, forwarding rule ────────────────────────────
# Three resources wired together to form the Global HTTPS Load Balancer:
#   url-map          — routes all paths to the backend service (Step 12)
#   target-https-proxy — terminates TLS using the managed cert (Step 10)
#   forwarding-rule  — binds the global IP (Step 9) to the HTTPS proxy on :443
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
# Attached to the backend service (Step 12) so evaluation happens at the LB
# edge before requests reach Cloud Run. Two rules:
#   priority 1000        — allow only Google Cloud Platform source IPs
#                          (Gemini Enterprise runs on GCP infrastructure)
#   priority 2147483647  — default deny-403 for anything not matched above
#
# Uses evaluateThreatIntelligence('iplist-public-clouds-gcp') — the Google
# Threat Intelligence feed for GCP IP ranges. Requires Cloud Armor Enterprise
# subscription on the project (distinct from evaluatePreconfiguredExpr which
# is for WAF rules and CDN IP lists only).
echo ""
echo "=== Step 14: Cloud Armor security policy ==="
if ! gcloud compute security-policies describe "${CLOUD_RUN_SERVICE_NAME}-armor" \
    --project="${PROJECT_ID}" &>/dev/null; then
  gcloud compute security-policies create "${CLOUD_RUN_SERVICE_NAME}-armor" \
      --description="Allow GCP source IPs only via Threat Intelligence feed" \
      --project="${PROJECT_ID}"

  # Priority 1000: allow traffic from GCP IP ranges using the Threat Intelligence
  # feed — only Google Cloud source IPs (where Gemini runs) are permitted.
  gcloud compute security-policies rules create 1000 \
      --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
      --expression="evaluateThreatIntelligence('iplist-public-clouds-gcp')" \
      --action=allow \
      --project="${PROJECT_ID}"

  # Default rule (priority 2147483647): deny-403 as the fallback catch-all
  gcloud compute security-policies rules update 2147483647 \
      --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
      --action=deny-403 \
      --project="${PROJECT_ID}"

  gcloud compute backend-services update "${CLOUD_RUN_SERVICE_NAME}-backend" \
      --global \
      --security-policy="${CLOUD_RUN_SERVICE_NAME}-armor" \
      --project="${PROJECT_ID}"
  echo "  Created and attached: ${CLOUD_RUN_SERVICE_NAME}-armor"
else
  echo "  Already exists: ${CLOUD_RUN_SERVICE_NAME}-armor"
fi

fi  # end if _USE_CLOUD_ARMOR

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║               Snowflake Proxy Setup Complete                        ║"
echo "╠══════════════════════════════════════════════════════════════════════╣"
echo "║"
echo "║  Hardening mode: ${HARDENING_MODE}"
echo "║"
echo "║  Static outbound IP (allowlist in Snowflake):"
echo "║    ${NAT_IP_ADDRESS}"
echo "║"

if [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  echo "║  Point your DNS A record:"
  echo "║    ${LB_DOMAIN}  →  ${_LB_IP}"
  echo "║"
fi

echo "║  In Gemini Enterprise → connector configuration:"
if [[ "${_USE_CLOUD_ARMOR}" == "true" && "${_USE_SECRET_PATH}" == "true" ]]; then
  echo "║    Endpoint URL: https://${LB_DOMAIN}/${PROXY_SECRET_PATH}/"
elif [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  echo "║    Endpoint URL: https://${LB_DOMAIN}/"
elif [[ "${_USE_SECRET_PATH}" == "true" ]]; then
  echo "║    Endpoint URL: ${_RUN_URL}/${PROXY_SECRET_PATH}/"
else
  echo "║    Endpoint URL: ${_RUN_URL}/"
fi
echo "║"

if [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  echo "║  Direct Cloud Run URL is ingress-restricted (not publicly reachable)."
  echo "║  Cloud Armor blocks all non-Google-Cloud source IPs."
  echo "║"
fi

echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Snowflake — run to allowlist the static egress IP:"
echo "    ALTER NETWORK POLICY <your_policy_name>"
echo "      ADD ALLOWED_IP_LIST = ('${NAT_IP_ADDRESS}/32');"
echo ""

if [[ "${_USE_CLOUD_ARMOR}" == "true" && "${_USE_SECRET_PATH}" == "true" ]]; then
  echo "  Verify the proxy is forwarding correctly:"
  echo "    curl -si https://${LB_DOMAIN}/${PROXY_SECRET_PATH}/api/v2/mcp/sse \\"
  echo "        -H 'Authorization: Bearer <token>' | head -5"
  echo ""
  echo "  Verify secret path gate (expect 404):"
  echo "    curl -si https://${LB_DOMAIN}/anything | head -5"
  echo ""
elif [[ "${_USE_CLOUD_ARMOR}" == "true" ]]; then
  echo "  Verify the proxy is forwarding correctly:"
  echo "    curl -si https://${LB_DOMAIN}/api/v2/mcp/sse \\"
  echo "        -H 'Authorization: Bearer <token>' | head -5"
  echo ""
elif [[ "${_USE_SECRET_PATH}" == "true" ]]; then
  echo "  Verify the proxy is forwarding correctly:"
  echo "    curl -si ${_RUN_URL}/${PROXY_SECRET_PATH}/api/v2/mcp/sse \\"
  echo "        -H 'Authorization: Bearer <token>' | head -5"
  echo ""
  echo "  Verify secret path gate (expect 404):"
  echo "    curl -si ${_RUN_URL}/anything | head -5"
  echo ""
fi
