# ConnectorProxy

GCP infrastructure that gives the Gemini Enterprise connector a customer-controlled static egress IP when connecting to Snowflake.

## Why this exists

The Gemini Enterprise connector requires a publicly resolvable URL and uses a dynamic IP pool. Snowflake network policies require a known, allowlisted IP. This proxy routes Gemini's traffic through a Cloud Run service whose egress is locked to a static IP via Cloud NAT.

## Hardening modes

Choose a mode based on your security requirements and budget:

| Mode | Description | LB + Cloud Armor required | Cost |
|---|---|---|---|
| `A` | **Secret path gate** — nginx returns 404 for any URL not containing `PROXY_SECRET_PATH`. Cloud Run is directly accessible; security is application-layer only. | No | No extra cost |
| `B` | **Cloud Armor + Global LB** — Cloud Armor blocks all non-GCP source IPs at the LB edge. Cloud Run ingress is locked to the LB. nginx serves an open proxy. | Yes | ~$20–40/month + Cloud Armor Enterprise |
| `AB` | **Both layers** (recommended) — Cloud Armor filters at the network edge; secret path filters at the application layer. Two independent gates. | Yes | ~$20–40/month + Cloud Armor Enterprise |

Set `HARDENING_MODE=A`, `B`, or `AB` in your `.env` file (default: `AB`).

## Architecture

### Strategy A only

```
Gemini Enterprise connector
        │  HTTPS  →  https://<cloud-run-url>/<PROXY_SECRET_PATH>/...
        ▼
Cloud Run  (nginx — secret path gate, rewrites Host header, proxies to Snowflake)
        │  --ingress=all  (direct Cloud Run URL is publicly reachable)
        │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
        ▼
Cloud NAT  ──►  Static External IP
        ▼
Snowflake
```

### Strategy B only

```
Gemini Enterprise connector
        │  HTTPS  →  https://<LB_DOMAIN>/...
        ▼
Cloud Armor  (blocks non-Google-Cloud source IPs)
        ▼
Global HTTPS Load Balancer  →  Serverless NEG
        ▼
Cloud Run  (nginx — open proxy, rewrites Host header, proxies to Snowflake)
        │  --ingress=internal-and-cloud-load-balancing
        │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
        ▼
Cloud NAT  ──►  Static External IP
        ▼
Snowflake
```

### Strategy A+B — Full hardening (recommended)

```
Gemini Enterprise connector
        │  HTTPS  →  https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/...
        ▼
Cloud Armor  (blocks non-Google-Cloud source IPs)
        ▼
Global HTTPS Load Balancer  →  Serverless NEG
        ▼
Cloud Run  (nginx — secret path gate, rewrites Host header, proxies to Snowflake)
        │  --ingress=internal-and-cloud-load-balancing
        │  --vpc-egress=all-traffic  →  Serverless VPC Access Connector
        ▼
Cloud NAT  ──►  Static External IP
        ▼
Snowflake
```

`--vpc-egress=all-traffic` forces every outbound byte from Cloud Run through the VPC connector and therefore through Cloud NAT, ensuring Snowflake always sees the static IP.

## Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`)
- A GCP project with billing enabled
- An existing VPC network
- A dedicated `/28` subnet for the VPC connector (no other resources in it)
- A Cloud Router + NAT already configured on that subnet, **or** let the script create them
- No local Docker required — the image is built in the cloud via Cloud Build
- **Strategy B / AB only**: A domain name you control for `LB_DOMAIN`, and Cloud Armor Enterprise enrollment

## Setup

1. Copy the example env file and fill in your values:

   ```bash
   cp .env.example .env
   ```

   Key values to set:

   | Variable | Description | Required for |
   |---|---|---|
   | `PROJECT_ID` | GCP project ID | All |
   | `VPC_NETWORK` | VPC network name | All |
   | `VPC_CONNECTOR_SUBNET` | Dedicated `/28` subnet name for the connector | All |
   | `NAT_ROUTER_NAME` | Cloud Router name (created if it doesn't exist) | All |
   | `NAT_GATEWAY_NAME` | Cloud NAT name (created if it doesn't exist) | All |
   | `SNOWFLAKE_HOST` | Your Snowflake account hostname | All |
   | `HARDENING_MODE` | `A`, `B`, or `AB` (default `AB`) | All |
   | `PROXY_SECRET_PATH` | Secret URL path segment — `openssl rand -hex 16` | Mode A or AB |
   | `LB_DOMAIN` | Domain that will front the Global Load Balancer | Mode B or AB |

2. Run the provisioning script:

   ```bash
   bash deploy/setup_psc_proxy.sh
   ```

   The script is fully idempotent — safe to re-run.

3. At completion the script prints the endpoint URL for your mode:

   | Mode | Endpoint URL format | Also printed |
   |---|---|---|
   | A | `https://<cloud-run-url>/<PROXY_SECRET_PATH>/` | Static egress IP |
   | B | `https://<LB_DOMAIN>/` | LB global IP, static egress IP |
   | AB | `https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/` | LB global IP, static egress IP |

4. **Mode B / AB** — Point your DNS A record:
   ```
   <LB_DOMAIN>  →  <LB IP printed by script>
   ```

5. Allowlist the static egress IP in Snowflake:

   ```sql
   ALTER NETWORK POLICY <your_policy_name>
     ADD ALLOWED_IP_LIST = ('<static_ip>/32');
   ```

## Resources provisioned

Resources marked **[B/AB]** are only created when `HARDENING_MODE` is `B` or `AB`.

| Resource | Purpose | Mode |
|---|---|---|
| Static external IP (regional) | Fixed egress address for Snowflake's allowlist | All |
| Cloud Router + NAT | Routes VPC connector egress through the static IP | All |
| Artifact Registry repo | Stores the nginx proxy Docker image | All |
| Cloud Run service | nginx proxy; all egress via VPC connector | All |
| Serverless VPC Access Connector | Bridges Cloud Run egress into the VPC for Cloud NAT | All |
| Global static IP (LB) | Front-door IP for the load balancer; point your DNS A record here | B/AB |
| Google-managed SSL certificate | TLS for `LB_DOMAIN`; auto-provisioned, auto-renewed | B/AB |
| Serverless NEG | Connects the Global LB to the Cloud Run service | B/AB |
| Global HTTPS Load Balancer | Terminates TLS; routes to Cloud Run via Serverless NEG | B/AB |
| Cloud Armor security policy | Blocks all source IPs that are not Google Cloud infrastructure | B/AB |

The VPC connector is created using `--subnet` (a named `/28` subnet you provide). This is required so Cloud NAT can scope to that subnet — connectors created with `--range` produce an anonymous range that NAT cannot target by name.

## Proxy files

| File | Purpose |
|---|---|
| [proxy/nginx.conf.template](proxy/nginx.conf.template) | nginx config with secret path gate; used when `PROXY_SECRET_PATH` is set (Strategy A or AB) |
| [proxy/nginx.conf.open.template](proxy/nginx.conf.open.template) | Open proxy nginx config (no path gate); used when `PROXY_SECRET_PATH` is not set (Strategy B only) |
| [proxy/entrypoint.sh](proxy/entrypoint.sh) | Selects the appropriate template, runs `envsubst`, then starts nginx |
| [proxy/Dockerfile](proxy/Dockerfile) | Builds the nginx:alpine image |

## Verification

```bash
# Mode A or AB — Secret path gate: wrong path must return 404
curl -si https://<endpoint>/anything | head -5

# Mode A or AB — Secret path gate: correct path should reach Snowflake
curl -si https://<endpoint>/<PROXY_SECRET_PATH>/api/v2/ping | head -10

# Mode B or AB — Cloud Armor gate: direct Cloud Run URL must be unreachable
curl -si https://<cloud-run-url>/  | head -5
# Expected: HTTP 403 (Cloud Run ingress blocks non-LB traffic)

# Confirm Snowflake sees the static IP (run in Snowsight after a test query)
SELECT client_net_address, user_name, start_time
FROM TABLE(information_schema.query_history(
    daterange_start => dateadd('hour', -1, current_timestamp())))
ORDER BY start_time DESC
LIMIT 5;
```

## Security hardening

Two independent gates are available. Enable either or both via `HARDENING_MODE`.

### Strategy A — Secret path (application layer)

`PROXY_SECRET_PATH` (a random hex string) is embedded in the endpoint URL. nginx returns `404` for any request that does not begin with that path segment, preventing automated scanners from identifying what the service does. The secret is stripped before forwarding to Snowflake.

With Strategy A only, Cloud Run ingress is `all` — the direct Cloud Run URL is publicly accessible but any path not matching the secret returns 404.

**Generate a secret path:**
```bash
openssl rand -hex 16
```

**Rotate the secret:** Update `PROXY_SECRET_PATH` in `.env`, update the Gemini connector endpoint URL, then re-run `bash deploy/setup_psc_proxy.sh`.

### Strategy B — Cloud Armor (network layer)

A Cloud Armor policy is attached to the Global Load Balancer backend. It uses the Google Threat Intelligence feed `iplist-public-clouds-gcp` to allow only GCP source IPs and denies everything else with HTTP 403. The Cloud Run service ingress is set to `internal-and-cloud-load-balancing`, so the raw Cloud Run URL is unreachable from the public internet.

**Requires:** Cloud Armor Enterprise enrollment on the project. The `evaluateThreatIntelligence()` expression is not available on the free tier.

To tighten the rule further, inspect Cloud Run logs for Gemini-specific headers (e.g. `X-Goog-Api-Client`) and add a header-match rule at priority 999.
