# ConnectorProxy

GCP infrastructure that gives the Gemini Enterprise connector a customer-controlled static egress IP when connecting to Snowflake.

## Why this exists

The Gemini Enterprise connector requires a publicly resolvable URL and uses a dynamic IP pool. Snowflake network policies require a known, allowlisted IP. This proxy routes Gemini's traffic through a Cloud Run service whose egress is locked to a static IP via Cloud NAT.

## Architecture

```
Gemini Enterprise connector
        │  HTTPS  →  https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/...
        ▼
Cloud Armor  (blocks non-Google-Cloud source IPs)
        ▼
Global HTTPS Load Balancer  →  Serverless NEG
        ▼
Cloud Run  (nginx — secret path gate, rewrites Host header, proxies to Snowflake)
        │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
        ▼
Cloud NAT  ──►  Static External IP
        │
        ▼
Snowflake  (account.snowflakecomputing.com:443)
```

`--vpc-egress=all-traffic` forces every outbound byte from Cloud Run through the VPC connector and therefore through Cloud NAT, ensuring Snowflake always sees the static IP. Cloud Run ingress is restricted to `internal-and-cloud-load-balancing` — the raw Cloud Run URL is not publicly reachable.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`)
- A GCP project with billing enabled
- An existing VPC network
- A dedicated `/28` subnet for the VPC connector (no other resources in it)
- A Cloud Router + NAT already configured on that subnet, **or** let the script create them
- No local Docker required — the image is built in the cloud via Cloud Build
- A domain name you control for `LB_DOMAIN`. If the domain is managed by a **Cloud DNS zone in the same project**, set `CLOUD_DNS_ZONE` and the script creates the A record automatically. Otherwise create the A record manually.

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
   | `PROXY_SECRET_PATH` | Secret URL path segment — generate with `openssl rand -hex 16` |
   | `LB_DOMAIN` | Domain name that will front the Global Load Balancer |
   | `CLOUD_DNS_ZONE` | *(Optional)* Cloud DNS managed zone name for `LB_DOMAIN`. If set, the script creates the DNS A record automatically. |

2. Run the provisioning script:

   ```bash
   bash deploy/setup_psc_proxy.sh
   ```

   The script is fully idempotent — safe to re-run.

3. At completion the script prints:

   | Output | Where to use it |
   |---|---|
   | **LB endpoint URL** (`https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/`) | Gemini Enterprise connector → Endpoint URL |
   | **DNS status** | If `CLOUD_DNS_ZONE` is set, the A record is created automatically. Otherwise create it manually. |
   | **Static egress IP** | Snowflake network policy (see below) |

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
| Cloud Armor security policy | Blocks all source IPs that are not Google Cloud infrastructure |

The VPC connector is created using `--subnet` (a named `/28` subnet you provide). This is required so Cloud NAT can scope to that subnet — connectors created with `--range` produce an anonymous range that NAT cannot target by name.

## Proxy files

| File | Purpose |
|---|---|
| [proxy/nginx.conf.template](proxy/nginx.conf.template) | nginx reverse proxy config; `$SNOWFLAKE_HOST`, `$SNOWFLAKE_PORT`, and `$PROXY_SECRET_PATH` substituted at container startup |
| [proxy/entrypoint.sh](proxy/entrypoint.sh) | Runs `envsubst` on the config template then starts nginx |
| [proxy/Dockerfile](proxy/Dockerfile) | Builds the nginx:alpine image |

## Verification

```bash
# Secret path gate: wrong path must return 404
curl -si https://<LB_DOMAIN>/anything | head -5

# Secret path gate: correct path should reach Snowflake (any Snowflake response is correct)
curl -si https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/api/v2/ping | head -10

# Cloud Armor gate: direct Cloud Run URL must be unreachable (403 or connection refused)
curl -si https://<cloud-run-url>/  | head -5

# Confirm Snowflake sees the static IP (run in Snowsight after a test query through the connector)
SELECT client_net_address, user_name, start_time
FROM TABLE(information_schema.query_history(
    daterange_start => dateadd('hour', -1, current_timestamp())))
ORDER BY start_time DESC
LIMIT 5;
```

## Security hardening

Two independent gates protect the proxy:

### Strategy B — Cloud Armor (network layer)

A Cloud Armor policy is attached to the Global Load Balancer backend. It uses the Google Threat Intelligence feed `iplist-public-clouds-gcp` to allow only GCP source IPs and denies everything else with HTTP 403. The Cloud Run service ingress is set to `internal-and-cloud-load-balancing`, so the raw Cloud Run URL is unreachable from the public internet — all traffic must pass through the LB.

To tighten the rule further, inspect Cloud Run logs for Gemini-specific headers (e.g. `X-Goog-Api-Client`) and add a header-match rule at priority 999.

### Strategy C — Secret path (application layer)

`PROXY_SECRET_PATH` (a random hex string) is embedded in the endpoint URL. nginx returns `404` for any request that does not begin with that path segment, preventing automated scanners from identifying what the service does. The secret is stripped before forwarding to Snowflake.

**Generate a secret path:**
```bash
openssl rand -hex 16
```

**Rotate secrets:** Update `PROXY_SECRET_PATH` in `.env`, update the Gemini connector endpoint URL, then re-run `bash deploy/setup_psc_proxy.sh`.
