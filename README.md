# ConnectorProxy

GCP infrastructure that gives the Gemini Enterprise connector a customer-controlled static egress IP when connecting to Snowflake.

## Why this exists

The Gemini Enterprise connector requires a publicly resolvable URL and uses a dynamic IP pool. Snowflake network policies require a known, allowlisted IP. This proxy routes Gemini's traffic through a Cloud Run service whose egress is locked to a static IP via Cloud NAT.

## Architecture

```
Gemini Enterprise connector
        │  HTTPS  →  https://<cloud-run-url>/...
        ▼
Cloud Run  (nginx — proxies all traffic to Snowflake)
        │  --ingress=all
        │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
        ▼
Cloud NAT  ──►  Static External IP
        │
        ▼
Snowflake  (account.snowflakecomputing.com:443)
```

`--vpc-egress=all-traffic` forces every outbound byte from Cloud Run through the VPC connector and therefore through Cloud NAT, ensuring Snowflake always sees the static IP.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`)
- A GCP project with billing enabled
- An existing VPC network
- A dedicated `/28` subnet for the VPC connector (no other resources in it)
- A Cloud Router + NAT already configured on that subnet, **or** let the script create them
- No local Docker required — the image is built in the cloud via Cloud Build

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

2. Run the provisioning script:

   ```bash
   bash deploy/setup_psc_proxy.sh
   ```

   The script is fully idempotent — safe to re-run.

3. At completion the script prints the three URLs to configure in the Gemini Enterprise connector:

   | Field | Value |
   |---|---|
   | **MCP URL** | `https://<cloud-run-url>/` |
   | **Authorization URL** | `https://<cloud-run-url>/oauth/authorize` |
   | **Token URL** | `https://<cloud-run-url>/oauth/token-request` |

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
| Cloud Run service | nginx proxy; all egress via VPC connector |
| Serverless VPC Access Connector | Bridges Cloud Run egress into the VPC for Cloud NAT |

## Proxy files

| File | Purpose |
|---|---|
| [proxy/nginx.conf.template](proxy/nginx.conf.template) | nginx reverse proxy config; `$SNOWFLAKE_HOST` and `$SNOWFLAKE_PORT` substituted at container startup |
| [proxy/entrypoint.sh](proxy/entrypoint.sh) | Runs `envsubst` on the config template then starts nginx |
| [proxy/Dockerfile](proxy/Dockerfile) | Builds the nginx:alpine image |

## Verification

```bash
# Proxy should forward to Snowflake (any Snowflake response is a pass)
curl -si https://<cloud-run-url>/api/v2/ping | head -10

# Confirm Snowflake sees the static IP (run in Snowsight after a test query)
SELECT client_net_address, user_name, start_time
FROM TABLE(information_schema.query_history(
    daterange_start => dateadd('hour', -1, current_timestamp())))
ORDER BY start_time DESC
LIMIT 5;
```

## Security model

Security relies on two layers without requiring a Global Load Balancer:

| Layer | How it protects |
|---|---|
| Snowflake OAuth | Valid client credentials required to initiate any flow |
| Snowflake network policy | Only the static egress IP is allowlisted — requests from any other IP are rejected by Snowflake |

**Note on Global Load Balancer + Cloud Armor:** A Global HTTPS LB was evaluated and removed. When a custom LB domain is used, Gemini Enterprise's backend switches its OAuth token exchange from `POST /oauth/token-request` (correct) to `POST /oauth/authorize` (rejected by Snowflake with 405), breaking the OAuth flow. This behaviour occurs regardless of Cloud Armor rules and is caused by how Gemini's backend interprets the custom domain vs the Cloud Run URL. Using the Cloud Run URL directly avoids this entirely.
