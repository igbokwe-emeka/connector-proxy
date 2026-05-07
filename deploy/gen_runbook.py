"""Generate Snowflake_Connector_Proxy_Admin_Runbook.pdf from current codebase state."""
import datetime
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, Preformatted,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUTPUT = os.path.join(os.path.dirname(__file__), "..", "Snowflake_Connector_Proxy_Admin_Runbook.pdf")

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=2.5 * cm, rightMargin=2.5 * cm,
    topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    title="Snowflake Connector Proxy — Admin Runbook",
    author="Igbokwe",
)

styles = getSampleStyleSheet()

H1    = ParagraphStyle("H1",    parent=styles["Heading1"], fontSize=16, spaceAfter=6,  spaceBefore=4,  textColor=colors.HexColor("#1a1a2e"))
H2    = ParagraphStyle("H2",    parent=styles["Heading2"], fontSize=12, spaceAfter=4,  spaceBefore=14, textColor=colors.HexColor("#16213e"))
H3    = ParagraphStyle("H3",    parent=styles["Heading3"], fontSize=10, spaceAfter=3,  spaceBefore=10, textColor=colors.HexColor("#0f3460"))
BODY  = ParagraphStyle("BODY",  parent=styles["Normal"],  fontSize=10, spaceAfter=6,  leading=15)
MONO  = ParagraphStyle("MONO",  parent=styles["Code"],    fontSize=8,  fontName="Courier", backColor=colors.HexColor("#f4f4f4"), borderPad=6, spaceAfter=8, leading=12)
NOTE  = ParagraphStyle("NOTE",  parent=styles["Normal"],  fontSize=9,  backColor=colors.HexColor("#fff8e1"), borderPad=6, spaceAfter=8, leading=13, leftIndent=8)
WARN  = ParagraphStyle("WARN",  parent=styles["Normal"],  fontSize=9,  backColor=colors.HexColor("#fce4ec"), borderPad=6, spaceAfter=8, leading=13, leftIndent=8)
TITLE = ParagraphStyle("TITLE", parent=styles["Title"],   fontSize=26, spaceAfter=8,  textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER)
SUB   = ParagraphStyle("SUB",   parent=styles["Normal"],  fontSize=12, spaceAfter=4,  textColor=colors.HexColor("#555555"), alignment=TA_CENTER)

W = A4[0] - 5 * cm  # usable body width


def tbl(data, col_widths=None, header=True):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    ts = [
        ("FONTNAME",       (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",       (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
        ("GRID",           (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
    ]
    if header:
        ts += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(ts))
    return t


def code(text):
    return Preformatted(text, MONO)


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc"), spaceAfter=6, spaceBefore=2)


story = []

# ── Title page ────────────────────────────────────────────────────────────────
story += [
    Spacer(1, 3 * cm),
    Paragraph("Snowflake Connector Proxy", TITLE),
    Paragraph("Admin Runbook", ParagraphStyle("ST2", parent=SUB, fontSize=16, textColor=colors.HexColor("#0f3460"))),
    Spacer(1, 0.5 * cm),
    hr(),
    Spacer(1, 0.3 * cm),
    Paragraph("GCP Cloud Run &nbsp;·&nbsp; nginx &nbsp;·&nbsp; Cloud NAT &nbsp;·&nbsp; Gemini Enterprise", SUB),
    Spacer(1, 0.5 * cm),
    Paragraph(f"Last updated: {datetime.date.today().strftime('%B %d, %Y')}", SUB),
    PageBreak(),
]

# ── 1. Overview ───────────────────────────────────────────────────────────────
story += [
    Paragraph("1. Overview", H1), hr(),
    Paragraph(
        "ConnectorProxy is a GCP-hosted nginx reverse proxy that gives the Gemini Enterprise "
        "Snowflake connector a customer-controlled static egress IP. Gemini Enterprise uses a "
        "dynamic IP pool; Snowflake network policies require a fixed, allowlisted IP. All traffic "
        "is routed through Cloud Run whose egress is pinned to a static address via Cloud NAT.",
        BODY),
]

# ── 2. Architecture ───────────────────────────────────────────────────────────
story += [
    Paragraph("2. Architecture", H1), hr(),
    code(
        "Gemini Enterprise connector\n"
        "        |  HTTPS  ->  https://<cloud-run-url>/...\n"
        "        v\n"
        "Cloud Run  (nginx -- proxies all traffic to Snowflake)\n"
        "        |  --ingress=all\n"
        "        |  --vpc-egress=all-traffic  ->  Serverless VPC Access Connector\n"
        "        v\n"
        "Cloud NAT  -->  Static External IP  (allowlisted in Snowflake network policy)\n"
        "        |\n"
        "        v\n"
        "Snowflake  (account.snowflakecomputing.com:443)"
    ),
    Paragraph(
        "<b>--vpc-egress=all-traffic</b> forces every outbound byte from Cloud Run through the VPC "
        "connector and Cloud NAT, ensuring Snowflake always sees the static IP.",
        BODY),
    Paragraph(
        "<b>--ingress=all</b> makes the Cloud Run URL publicly reachable — required for "
        "Gemini Enterprise to initiate the OAuth browser flow.",
        BODY),
]

# ── 3. GCP Resources ──────────────────────────────────────────────────────────
story += [
    Paragraph("3. GCP Resources Provisioned", H1), hr(),
    tbl([
        ["Resource", "Purpose"],
        ["Static external IP (regional)", "Fixed egress address for Snowflake's allowlist"],
        ["Cloud Router",                  "Manages routing within the VPC"],
        ["Cloud NAT",                     "Routes VPC connector egress through the static IP"],
        ["Artifact Registry repo",        "Stores the nginx proxy Docker image"],
        ["Cloud Run service",             "nginx proxy; all egress via VPC connector"],
        ["Serverless VPC Access Connector","Bridges Cloud Run egress into the VPC for Cloud NAT"],
    ], col_widths=[7 * cm, 11.5 * cm]),
]

# ── 4. Environment Variables ──────────────────────────────────────────────────
story += [
    Spacer(1, 0.3 * cm),
    Paragraph("4. Environment Variables (.env)", H1), hr(),
    Paragraph(
        "Copy <font face='Courier'>.env.example</font> to <font face='Courier'>.env</font> "
        "and populate before running the setup script.",
        BODY),
    tbl([
        ["Variable",              "Description"],
        ["PROJECT_ID",            "GCP project ID"],
        ["REGION",                "GCP region (e.g. us-central1)"],
        ["VPC_NETWORK",           "VPC network name"],
        ["SNOWFLAKE_HOST",        "Snowflake account hostname (e.g. xy12345.snowflakecomputing.com)"],
        ["SNOWFLAKE_PORT",        "Snowflake port (443)"],
        ["NAT_IP_NAME",           "Name for the reserved static egress IP"],
        ["NAT_ROUTER_NAME",       "Cloud Router name (created if absent)"],
        ["NAT_GATEWAY_NAME",      "Cloud NAT gateway name (created if absent)"],
        ["VPC_CONNECTOR_NAME",    "Serverless VPC Access Connector name"],
        ["VPC_CONNECTOR_SUBNET",  "Dedicated /28 subnet for the connector (no other resources)"],
        ["CLOUD_RUN_SERVICE_NAME","Cloud Run service name"],
        ["AR_REPO",               "Artifact Registry repository name"],
    ], col_widths=[6 * cm, 12.5 * cm]),
]

# ── 5. Deployment ─────────────────────────────────────────────────────────────
story += [
    Spacer(1, 0.3 * cm),
    Paragraph("5. Deployment", H1), hr(),
    Paragraph("The setup script is fully idempotent — safe to re-run at any time.", BODY),
    code("bash deploy/setup_psc_proxy.sh"),
    tbl([
        ["Step", "Action"],
        ["1", "Enable required GCP APIs (Compute, Cloud Run, VPC Access, Artifact Registry, Cloud Build)"],
        ["2", "Reserve regional static external IP for Cloud NAT egress"],
        ["3", "Create Cloud Router (if absent)"],
        ["4", "Create Cloud NAT gateway scoped to the connector subnet (if absent)"],
        ["5", "Create Artifact Registry Docker repository; grant Cloud Build write access"],
        ["6", "Build and push the nginx proxy Docker image via Cloud Build (no local Docker needed)"],
        ["7", "Create Serverless VPC Access Connector on the dedicated /28 subnet (if absent)"],
        ["8", "Deploy Cloud Run service with --ingress=all and --vpc-egress=all-traffic"],
    ], col_widths=[1.2 * cm, 17.3 * cm]),
    Spacer(1, 0.2 * cm),
    Paragraph("On completion the script prints the static egress IP and the three connector URLs.", BODY),
]

# ── 6. Gemini Enterprise Configuration ────────────────────────────────────────
story += [
    Paragraph("6. Gemini Enterprise Connector Configuration", H1), hr(),
    Paragraph("In the Gemini Enterprise console, configure the Snowflake connector with these values:", BODY),
    tbl([
        ["Field",           "Value"],
        ["MCP URL",         "https://<cloud-run-url>/api/v2/databases/<db>/schemas/<schema>/mcp-servers/<server>"],
        ["Authorization URL","https://<cloud-run-url>/oauth/authorize"],
        ["Token URL",       "https://<cloud-run-url>/oauth/token-request"],
        ["Client ID",       "OAuth client ID from the Snowflake security integration"],
        ["Client Secret",   "OAuth client secret from the Snowflake security integration"],
        ["Scopes",          "session:role:<ROLE_NAME>"],
    ], col_widths=[4.5 * cm, 14 * cm]),
    Spacer(1, 0.3 * cm),
    Paragraph(
        "<b>Critical:</b> All three URLs must use the exact Cloud Run URL with no typos. "
        "A wrong Token URL causes a silent failure — the browser OAuth login succeeds but the "
        'token exchange never reaches the proxy, resulting in "Failed to obtain refresh token".',
        WARN),
    Paragraph(
        "The Token URL must end in <font face='Courier'>/oauth/token-request</font>, "
        "not <font face='Courier'>/oauth/authorize</font>. These are two different Snowflake endpoints.",
        NOTE),
]

# ── 7. Snowflake Configuration ────────────────────────────────────────────────
story += [
    Paragraph("7. Snowflake Configuration", H1), hr(),
    Paragraph("Network policy — allowlist the static egress IP:", H3),
    code(
        "ALTER NETWORK POLICY <your_policy_name>\n"
        "  ADD ALLOWED_IP_LIST = ('<static_ip>/32');"
    ),
    Paragraph(
        "Only the proxy's static IP needs to be allowlisted. All traffic to Snowflake originates from it.",
        BODY),
    Paragraph("OAuth security integration — required settings:", H3),
    Paragraph(
        "The Snowflake OAuth integration must issue refresh tokens for the connector to maintain "
        "long-lived access:",
        BODY),
    code(
        "CREATE SECURITY INTEGRATION <name>\n"
        "  TYPE = OAUTH\n"
        "  ENABLED = TRUE\n"
        "  OAUTH_CLIENT = CUSTOM\n"
        "  OAUTH_CLIENT_TYPE = CONFIDENTIAL\n"
        "  OAUTH_REDIRECT_URI = 'https://vertexaisearch.cloud.google.com/oauth-redirect'\n"
        "  OAUTH_ISSUE_REFRESH_TOKENS = TRUE\n"
        "  OAUTH_REFRESH_TOKEN_VALIDITY = 7776000;  -- 90 days"
    ),
]

# ── 8. Verification ───────────────────────────────────────────────────────────
story += [
    Paragraph("8. Verification", H1), hr(),
    Paragraph("Confirm the proxy is forwarding to Snowflake:", H3),
    code("curl -si https://<cloud-run-url>/api/v2/ping | head -10"),
    Paragraph("Any Snowflake response (including 401) confirms the proxy is working.", BODY),
    Paragraph("Confirm Snowflake sees the static egress IP:", H3),
    Paragraph("Run in Snowsight after a test query or OAuth flow:", BODY),
    code(
        "SELECT client_net_address, user_name, start_time\n"
        "FROM TABLE(information_schema.query_history(\n"
        "    daterange_start => dateadd('hour', -1, current_timestamp())))\n"
        "ORDER BY start_time DESC\n"
        "LIMIT 5;"
    ),
    Paragraph("Check Cloud Run logs:", H3),
    code(
        "gcloud logging read \\\n"
        '  "resource.type=cloud_run_revision \\\n'
        '   AND resource.labels.service_name=<service-name>" \\\n'
        "  --project=<project-id> --limit=100 --freshness=10m \\\n"
        '  --format="value(timestamp, httpRequest.requestMethod, \\\n'
        '            httpRequest.requestUrl, httpRequest.status)"'
    ),
    Paragraph(
        "A healthy OAuth flow produces these requests in sequence: "
        "<font face='Courier'>GET /oauth/authorize 200</font>, "
        "<font face='Courier'>POST /session/authenticate-request 200</font>, "
        "<font face='Courier'>POST /oauth/authorization-request 200</font>, "
        "<font face='Courier'>POST /oauth/token-request 200</font>.",
        BODY),
]

# ── 9. Security Model ─────────────────────────────────────────────────────────
story += [
    Paragraph("9. Security Model", H1), hr(),
    tbl([
        ["Layer",                    "How it protects"],
        ["Snowflake OAuth",          "Valid client credentials (client ID + secret) required to initiate any flow"],
        ["Snowflake network policy", "Only the static egress IP is allowlisted — all other source IPs are rejected"],
    ], col_widths=[5 * cm, 13.5 * cm]),
]

# ── 10. Operational Reference ──────────────────────────────────────────────────
story += [
    Paragraph("10. Operational Reference — igbokwe Deployment", H1), hr(),
    tbl([
        ["Resource",              "Value"],
        ["GCP Project",           "igbokwe"],
        ["Region",                "us-central1"],
        ["VPC Network",           "ice"],
        ["Cloud Run service",     "snowflake-proxy"],
        ["Cloud Run URL",         "https://snowflake-proxy-bt24fn2lfa-uc.a.run.app"],
        ["VPC Connector",         "snowflake-connector (subnet: snowflake-connector-subnet)"],
        ["Static egress IP",      "34.68.22.120"],
        ["Snowflake host",        "HIJZKAO-RG62005.snowflakecomputing.com"],
        ["Artifact Registry repo","snowflake-proxy (us-central1)"],
    ], col_widths=[5.5 * cm, 13 * cm]),
    Spacer(1, 0.4 * cm),
    Paragraph("Gemini Enterprise connector URLs:", H3),
    tbl([
        ["Field",             "Value"],
        ["Authorization URL", "https://snowflake-proxy-bt24fn2lfa-uc.a.run.app/oauth/authorize"],
        ["Token URL",         "https://snowflake-proxy-bt24fn2lfa-uc.a.run.app/oauth/token-request"],
    ], col_widths=[4.5 * cm, 14 * cm]),
]

doc.build(story)
print("PDF written to:", os.path.abspath(OUTPUT))
