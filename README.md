# ConnectorProxy

GCP infrastructure that gives the Gemini Enterprise connector a customer-controlled static egress IP when connecting to Snowflake.

## Why this exists

The Gemini Enterprise connector requires a publicly resolvable URL and uses a dynamic IP pool. Snowflake network policies require a known, allowlisted IP. This proxy routes Gemini's traffic through a Cloud Run service whose egress is locked to a static IP via Cloud NAT.

## Architecture

```
Gemini Enterprise connector
        │  HTTPS  →  https://<LB_DOMAIN>/...
        ▼
Global HTTPS Load Balancer  →  Serverless NEG
        ▼
Cloud Run  (nginx — proxies all traffic to Snowflake)
        │  --ingress=internal-and-cloud-load-balancing
        │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
        ▼
Cloud NAT  ──►  Static External IP
        │
        ▼
Snowflake  (account.snowflakecomputing.com:443)
```

`--vpc-egress=all-traffic` forces every outbound byte from Cloud Run through the VPC connector and therefore through Cloud NAT, ensuring Snowflake always sees the static IP. Cloud Run ingress is restricted to `internal-and-cloud-load-balancing` — the raw Cloud Run URL is not publicly reachable from the internet.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`)
- A GCP project with billing enabled
- An existing VPC network
- A dedicated `/28` subnet for the VPC connector (no other resources in it)
- A Cloud Router + NAT already configured on that subnet, **or** let the script create them
- No local Docker required — the image is built in the cloud via Cloud Build
- A domain name you control for `LB_DOMAIN`. If the domain is managed by a **Cloud DNS zone in the same project**, set `CLOUD_DNS_ZONE` and the script creates the A record automatically.

## Setup

1. Copy the example env file and fill in your values:

   ```bash
   cp .env.example .env
   ```

   Key values to set:

   | Variable | Description |
   |---|---|
   | `PROJECT_ID` | GCP project ID |
   | `VPC_NETWORK` | VPC network name |
   | `VPC_CONNECTOR_SUBNET` | Dedicated `/28` subnet name for the connector (no other resources) |
   | `NAT_ROUTER_NAME` | Cloud Router name (created if it doesn't exist) |
   | `NAT_GATEWAY_NAME` | Cloud NAT name (created if it doesn't exist) |
   | `SNOWFLAKE_HOST` | Your Snowflake account hostname (e.g. `xy12345.snowflakecomputing.com`) |
   | `LB_DOMAIN` | Domain name that will front the Global Load Balancer |
   | `CLOUD_DNS_ZONE` | *(Optional)* Cloud DNS managed zone name for `LB_DOMAIN`. If set, the script creates the DNS A record automatically. |

2. Run the provisioning script:

   ```bash
   bash deploy/setup_psc_proxy.sh
   ```

   The script is fully idempotent — safe to re-run.

3. At completion the script prints the three URLs to configure in the Gemini Enterprise connector:

   | Field | Value |
   |---|---|
   | **MCP URL** | `https://<LB_DOMAIN>/` |
   | **Authorization URL** | `https://<LB_DOMAIN>/oauth/authorize` |
   | **Token URL** | `https://<LB_DOMAIN>/oauth/token-request` |

4. Allowlist the static IP in Snowflake:

   ```sql
   ALTER NETWORK POLICY <your_policy_name>
     ADD ALLOWED_IP_LIST = ('<static_ip>/32');
   ```

## Resources provisioned

| Resource | Purpose |
|---|---|
| Static external IP (regional) | Fixed egress address for Snowflake's allowlist |
| Cloud Router + NAT | Routes VPC connector egress through the static IP |
| Artifact Registry repo | Stores the nginx proxy Docker image |
| Cloud Run service | nginx proxy; ingress locked to LB only; all egress via VPC connector |
| Serverless VPC Access Connector | Bridges Cloud Run egress into the VPC for Cloud NAT |
| Global static IP (LB) | Front-door IP for the load balancer |
| DNS A record | Maps `LB_DOMAIN` to the LB IP — created automatically if `CLOUD_DNS_ZONE` is set |
| Google-managed SSL certificate | TLS for `LB_DOMAIN`; auto-provisioned once DNS resolves, auto-renewed |
| Serverless NEG | Connects the Global LB to the Cloud Run service |
| Global HTTPS Load Balancer | Terminates TLS; routes to Cloud Run via Serverless NEG |

## Proxy files

| File | Purpose |
|---|---|
| [proxy/nginx.conf.template](proxy/nginx.conf.template) | nginx reverse proxy config; `$SNOWFLAKE_HOST` and `$SNOWFLAKE_PORT` substituted at container startup |
| [proxy/entrypoint.sh](proxy/entrypoint.sh) | Runs `envsubst` on the config template then starts nginx |
| [proxy/Dockerfile](proxy/Dockerfile) | Builds the nginx:alpine image |

## Verification

```bash
# Proxy should forward to Snowflake (any Snowflake response is a pass)
curl -si https://<LB_DOMAIN>/api/v2/ping | head -10

# Cloud Armor gate: direct Cloud Run URL must be unreachable
curl -si https://<cloud-run-url>/ | head -5

# Confirm Snowflake sees the static IP (run in Snowsight after a test query)
SELECT client_net_address, user_name, start_time
FROM TABLE(information_schema.query_history(
    daterange_start => dateadd('hour', -1, current_timestamp())))
ORDER BY start_time DESC
LIMIT 5;
```

## Security model

Cloud Armor Enterprise is **not used**. When attached to this LB, it causes Gemini Enterprise's backend to call `POST /oauth/authorize` (rejected by Snowflake with 405) instead of `POST /oauth/token-request`, breaking the OAuth token exchange. This occurs regardless of which Cloud Armor rules allow the traffic — confirmed by LB access logs comparing behaviour with and without Cloud Armor attached.

Security layers in use:

| Layer | How it protects |
|---|---|
| Cloud Run `--ingress=internal-and-cloud-load-balancing` | Direct Cloud Run URL unreachable from the public internet |
| Snowflake OAuth | Valid client credentials required to initiate any flow |
| Snowflake network policy | Only the static egress IP `34.68.22.120` is allowlisted — requests from any other IP are rejected by Snowflake |
