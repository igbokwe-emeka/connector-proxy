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

   > **Important:** All three URLs must use the exact Cloud Run URL with no typos. A wrong Token URL causes a silent failure — the browser OAuth login succeeds but the token exchange never reaches the proxy, resulting in "Failed to obtain refresh token."

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

| Layer | How it protects |
|---|---|
| Snowflake OAuth | Valid client credentials required to initiate any flow |
| Snowflake network policy | Only the static egress IP is allowlisted — requests from any other IP are rejected by Snowflake |

**Note on Global Load Balancer + Cloud Armor:** A Global HTTPS LB was evaluated and removed. When a custom LB domain is used, Gemini Enterprise's backend switches its OAuth token exchange from `POST /oauth/token-request` (correct) to `POST /oauth/authorize` (rejected by Snowflake with 405), breaking the OAuth flow. This occurs regardless of Cloud Armor rules and is caused by how Gemini's backend interprets the custom domain vs the Cloud Run URL. Using the Cloud Run URL directly avoids this entirely.

## Runbook

### "Failed to obtain refresh token"

The browser OAuth login succeeds (you see the Snowflake login page and authenticate), but the connector reports it cannot obtain a refresh token.

**Diagnosis:** Check Cloud Run logs for `POST /oauth/token-request`. If this request never appears, the token exchange is not reaching the proxy.

```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=<service-name>" \
  --project=<project-id> --limit=100 --freshness=10m \
  --format="value(timestamp, httpRequest.requestMethod, httpRequest.requestUrl, httpRequest.status)"
```

Look for `POST .../oauth/token-request`. If absent, the Token URL in the Gemini Enterprise connector is wrong.

**Fix:** In the Gemini Enterprise connector settings, verify all three URLs exactly match the Cloud Run URL:

| Field | Correct value |
|---|---|
| Authorization URL | `https://<cloud-run-url>/oauth/authorize` |
| Token URL | `https://<cloud-run-url>/oauth/token-request` |
| MCP URL | `https://<cloud-run-url>/` |

Common mistakes: typo in the domain (e.g. `.appm/` instead of `.app/`), using `/oauth/authorize` for the Token URL instead of `/oauth/token-request`.

---

### Token exchange reaches proxy but Snowflake rejects it (network policy)

`POST /oauth/token-request` appears in Cloud Run logs with a non-200 status proxied from Snowflake.

**Diagnosis:** Confirm Snowflake's network policy includes the static egress IP:

```sql
SHOW NETWORK POLICIES;
```

**Fix:** Add the static IP to the allowlist:

```sql
ALTER NETWORK POLICY <policy_name>
  ADD ALLOWED_IP_LIST = ('<static_ip>/32');
```

---

### Connector was working, stopped working after infrastructure change

1. Confirm the Cloud Run service is running: `gcloud run services describe <service> --region=<region>`
2. Check Cloud Run logs for errors in the last 30 minutes
3. Verify the static egress IP hasn't changed: `gcloud compute addresses describe <nat-ip-name> --region=<region>`
4. Confirm the Snowflake network policy still allows that IP (see above)
5. Re-check all three connector URLs in Gemini Enterprise settings
