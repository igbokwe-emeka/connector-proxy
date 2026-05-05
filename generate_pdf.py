"""
Generate administrator runbook PDF for the Snowflake Connector Proxy.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import KeepTogether
from datetime import date

OUTPUT = "Snowflake_Connector_Proxy_Admin_Runbook.pdf"

# ── Colour palette ─────────────────────────────────────────────────────────────
BLUE       = colors.HexColor("#1a73e8")
DARK_BLUE  = colors.HexColor("#0d47a1")
LIGHT_BLUE = colors.HexColor("#e8f0fe")
GREY_BG    = colors.HexColor("#f8f9fa")
GREY_LINE  = colors.HexColor("#dadce0")
CODE_BG    = colors.HexColor("#1e1e2e")
CODE_FG    = colors.HexColor("#cdd6f4")
WARN_BG    = colors.HexColor("#fff8e1")
WARN_LINE  = colors.HexColor("#f9a825")
SUCCESS_BG = colors.HexColor("#e8f5e9")
SUCCESS_LINE = colors.HexColor("#2e7d32")
RED        = colors.HexColor("#c62828")
STEP_BG    = colors.HexColor("#e3f2fd")

W, H = A4

# ── Styles ─────────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def style(name, parent="Normal", **kw):
    s = ParagraphStyle(name, parent=base[parent], **kw)
    return s

S = {
    "h1":    style("h1",    "Heading1", fontSize=22, textColor=DARK_BLUE,
                   spaceAfter=6, spaceBefore=0, leading=28),
    "h2":    style("h2",    "Heading2", fontSize=14, textColor=DARK_BLUE,
                   spaceAfter=4, spaceBefore=14, leading=20,
                   borderPad=4),
    "h3":    style("h3",    "Heading3", fontSize=11, textColor=BLUE,
                   spaceAfter=3, spaceBefore=10, leading=16, fontName="Helvetica-Bold"),
    "body":  style("body",  "Normal",   fontSize=9.5, leading=14, spaceAfter=4,
                   alignment=TA_JUSTIFY),
    "bullet":style("bullet","Normal",   fontSize=9.5, leading=13, spaceAfter=2,
                   leftIndent=14, bulletIndent=4),
    "note":  style("note",  "Normal",   fontSize=9, leading=13, textColor=colors.HexColor("#5f6368")),
    "code":  style("code",  "Code",     fontSize=8.2, leading=12, fontName="Courier",
                   textColor=CODE_FG, backColor=CODE_BG,
                   leftIndent=10, rightIndent=10, spaceBefore=4, spaceAfter=4),
    "step_title": style("step_title", "Normal", fontSize=10.5, fontName="Helvetica-Bold",
                        textColor=DARK_BLUE, spaceAfter=4),
    "warn":  style("warn",  "Normal",   fontSize=9, leading=13,
                   textColor=colors.HexColor("#e65100")),
    "center":style("center","Normal",   fontSize=9, alignment=TA_CENTER,
                   textColor=colors.HexColor("#5f6368")),
    "title_main": style("title_main","Normal", fontSize=28, fontName="Helvetica-Bold",
                        textColor=colors.white, alignment=TA_CENTER, leading=36),
    "title_sub":  style("title_sub", "Normal", fontSize=13, textColor=colors.HexColor("#bbdefb"),
                        alignment=TA_CENTER, leading=20),
    "title_meta": style("title_meta","Normal", fontSize=10, textColor=colors.HexColor("#90caf9"),
                        alignment=TA_CENTER),
}

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=GREY_LINE, spaceAfter=8, spaceBefore=4)

def code_block(text):
    return Preformatted(text.strip(), S["code"])

def note_box(text, bg=WARN_BG, line=WARN_LINE, label="NOTE"):
    data = [[Paragraph(f"<b>{label}:</b> {text}", S["warn"])]]
    t = Table(data, colWidths=[W - 4.4*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LINEAFTER", (0,0), (0,-1), 4, line),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [bg]),
    ]))
    return t

def success_box(text):
    return note_box(text, bg=SUCCESS_BG, line=SUCCESS_LINE, label="OUTPUT")

def step_box(number, title, body_elements):
    header_data = [[
        Paragraph(f"<b>Step {number}</b>", style("sn","Normal",fontSize=10,
                  fontName="Helvetica-Bold",textColor=colors.white)),
        Paragraph(title, style("st","Normal",fontSize=10,
                  fontName="Helvetica-Bold",textColor=colors.white)),
    ]]
    header = Table(header_data, colWidths=[1.8*cm, W - 6.2*cm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), DARK_BLUE),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    return [header] + body_elements + [Spacer(1, 8)]

def kv_table(rows, col_widths=None):
    if col_widths is None:
        col_widths = [5.5*cm, W - 9.9*cm]
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), LIGHT_BLUE),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("GRID", (0,0), (-1,-1), 0.4, GREY_LINE),
        ("LEFTPADDING", (0,0), (-1,-1), 7),
        ("RIGHTPADDING", (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [GREY_BG, colors.white]),
    ]))
    return t

# ── Page callbacks ─────────────────────────────────────────────────────────────
def on_first_page(canvas, doc):
    canvas.saveState()
    # Full-bleed header band
    canvas.setFillColor(DARK_BLUE)
    canvas.rect(0, H - 10*cm, W, 10*cm, fill=1, stroke=0)
    # Accent stripe
    canvas.setFillColor(BLUE)
    canvas.rect(0, H - 10*cm, W, 0.4*cm, fill=1, stroke=0)
    # Footer
    canvas.setFillColor(GREY_LINE)
    canvas.rect(0, 0, W, 1.2*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5f6368"))
    canvas.drawCentredString(W/2, 0.45*cm, "CONFIDENTIAL — Internal Use Only")
    canvas.restoreState()

def on_later_pages(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK_BLUE)
    canvas.rect(0, H - 1.2*cm, W, 1.2*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.white)
    canvas.drawString(1.5*cm, H - 0.75*cm, "Snowflake Connector Proxy — Administrator Runbook")
    canvas.drawRightString(W - 1.5*cm, H - 0.75*cm, f"Page {doc.page}")
    canvas.setFillColor(GREY_LINE)
    canvas.rect(0, 0, W, 1.0*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5f6368"))
    canvas.drawCentredString(W/2, 0.35*cm, "CONFIDENTIAL — Internal Use Only")
    canvas.restoreState()

# ── Document ───────────────────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    OUTPUT, pagesize=A4,
    leftMargin=2.2*cm, rightMargin=2.2*cm,
    topMargin=3.6*cm, bottomMargin=2.0*cm,
)

story = []

# ─────────────────────────────── COVER ───────────────────────────────────────
story += [
    Spacer(1, 6.5*cm),
    Paragraph("Snowflake Connector Proxy", S["title_main"]),
    Spacer(1, 0.4*cm),
    Paragraph("Administrator Runbook", S["title_sub"]),
    Spacer(1, 0.3*cm),
    Paragraph("Step-by-step provisioning guide for GCP infrastructure", S["title_sub"]),
    Spacer(1, 1.2*cm),
    Paragraph(f"Version 1.0 &nbsp;&nbsp;|&nbsp;&nbsp; {date.today().strftime('%B %d, %Y')} &nbsp;&nbsp;|&nbsp;&nbsp; igbokwe", S["title_meta"]),
    PageBreak(),
]

# ─────────────────────────────── TOC ─────────────────────────────────────────
story += [
    Paragraph("Table of Contents", S["h1"]),
    hr(),
    Spacer(1, 0.2*cm),
]
toc_entries = [
    ("1", "Overview & Architecture"),
    ("2", "Prerequisites"),
    ("3", "Configuration Variables (.env)"),
    ("4", "Proxy Source Files"),
    ("5", "Provisioning Steps (Steps 1 – 14)"),
    ("  5.1", "Step 1  — Enable GCP APIs"),
    ("  5.2", "Step 2  — Reserve Regional Static IP (Egress)"),
    ("  5.3", "Step 3  — Cloud Router"),
    ("  5.4", "Step 4  — Cloud NAT"),
    ("  5.5", "Step 5  — Artifact Registry Repository"),
    ("  5.6", "Step 6  — Build & Push Docker Image"),
    ("  5.7", "Step 7  — Serverless VPC Access Connector"),
    ("  5.8", "Step 8  — Deploy Cloud Run Service"),
    ("  5.9", "Step 9  — Reserve Global Static IP (Load Balancer)"),
    ("  5.10","Step 10 — Google-Managed SSL Certificate"),
    ("  5.11","Step 11 — Serverless Network Endpoint Group (NEG)"),
    ("  5.12","Step 12 — Global Backend Service"),
    ("  5.13","Step 13 — Global HTTPS Load Balancer"),
    ("  5.14","Step 14 — Cloud Armor Security Policy"),
    ("6", "Post-Provisioning Configuration"),
    ("  6.1", "DNS A Record"),
    ("  6.2", "Snowflake Network Policy"),
    ("  6.3", "Gemini Enterprise Connector"),
    ("7", "Verification"),
    ("8", "Secret Rotation"),
    ("9", "Resources Provisioned — Summary Table"),
]
toc_data = [[Paragraph(f"<b>{n}</b>", S["note"]), Paragraph(t, S["note"])] for n, t in toc_entries]
toc_t = Table(toc_data, colWidths=[1.8*cm, W - 6.0*cm])
toc_t.setStyle(TableStyle([
    ("FONTSIZE", (0,0), (-1,-1), 9),
    ("TOPPADDING", (0,0), (-1,-1), 3),
    ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ("LINEBELOW", (0,-1), (-1,-1), 0.4, GREY_LINE),
]))
story += [toc_t, PageBreak()]

# ─────────────────────────── SECTION 1 — OVERVIEW ────────────────────────────
story += [
    Paragraph("1. Overview & Architecture", S["h1"]),
    hr(),
    Paragraph(
        "This runbook provides sequential instructions to provision the Snowflake Connector Proxy "
        "on Google Cloud Platform. The proxy gives the Gemini Enterprise connector a "
        "<b>customer-controlled static egress IP</b> when connecting to Snowflake, satisfying "
        "Snowflake's requirement that only known, allowlisted IPs can connect.",
        S["body"]),
    Spacer(1, 0.3*cm),
    Paragraph("Problem Statement", S["h3"]),
    Paragraph(
        "Gemini Enterprise uses a dynamic pool of Google IP addresses. Snowflake network policies "
        "require a fixed, pre-approved IP address. Without this proxy, Gemini cannot connect to a "
        "Snowflake account that enforces network policies.",
        S["body"]),
    Spacer(1, 0.3*cm),
    Paragraph("Solution Architecture", S["h3"]),
]

arch = """\
  Gemini Enterprise connector
      │  HTTPS  →  https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/
      ▼
  Cloud Armor  [SECURITY LAYER 1]
      • evaluateThreatIntelligence('iplist-public-clouds-gcp')
      • Blocks all non-GCP source IPs with HTTP 403
      ▼
  Global HTTPS Load Balancer  (port 443, TLS termination)
      │  →  Serverless NEG
      ▼
  Cloud Run  (nginx container)  [SECURITY LAYER 2]
      • Secret path gate: 404 for any path ≠ /<PROXY_SECRET_PATH>/
      • Rewrites Host header to Snowflake hostname
      • --ingress=internal-and-cloud-load-balancing (direct URL blocked)
      • --vpc-egress=all-traffic
      ▼
  Serverless VPC Access Connector
      ▼
  Cloud NAT  →  Static External IP  ←── allowlisted in Snowflake
      ▼
  Snowflake  (account.snowflakecomputing.com:443)"""

story += [
    code_block(arch),
    Spacer(1, 0.3*cm),
    Paragraph("Security Layers", S["h3"]),
    Paragraph(
        "<b>Layer 1 — Cloud Armor (network):</b> Attached to the Global LB backend. "
        "Uses the Google Threat Intelligence feed <i>iplist-public-clouds-gcp</i> to allow "
        "only GCP source IPs. All other traffic is denied with HTTP 403 before reaching "
        "Cloud Run. Requires Cloud Armor Enterprise subscription.",
        S["bullet"]),
    Paragraph(
        "<b>Layer 2 — Secret path (application):</b> nginx returns HTTP 404 for any URL "
        "that does not begin with the randomly generated <i>PROXY_SECRET_PATH</i> segment. "
        "The secret is stripped before the request is forwarded to Snowflake.",
        S["bullet"]),
    Spacer(1, 0.3*cm),
    note_box(
        "Cloud Run ingress is set to <i>internal-and-cloud-load-balancing</i>. "
        "The raw Cloud Run URL is not publicly reachable — all traffic must pass through "
        "the Global LB and Cloud Armor.", bg=STEP_BG, line=BLUE, label="IMPORTANT"),
    PageBreak(),
]

# ─────────────────────────── SECTION 2 — PREREQUISITES ───────────────────────
story += [
    Paragraph("2. Prerequisites", S["h1"]),
    hr(),
    Paragraph("The following must be in place before beginning provisioning:", S["body"]),
    Spacer(1, 0.2*cm),
]

prereqs = [
    ["GCP Project", "Billing enabled. You must have Owner or Editor role."],
    ["gcloud CLI", "Installed and authenticated: gcloud auth login"],
    ["VPC Network", "An existing VPC network in the target region."],
    ["Dedicated /28 subnet", "A subnet used exclusively by the VPC connector — no other resources. Required so Cloud NAT can scope egress by subnet name."],
    ["Domain name", "A domain (or subdomain) you control for LB_DOMAIN. You must be able to create an A record pointing to the LB IP."],
    ["Cloud Armor Enterprise", "Enrolled at the project level. Required for evaluateThreatIntelligence() expressions."],
    ["Docker", "Not required — the proxy image is built in the cloud via Cloud Build."],
    ["Snowflake access", "Admin rights to modify the Snowflake network policy."],
]
story += [
    kv_table([[Paragraph(f"<b>{k}</b>", S["note"]), Paragraph(v, S["note"])] for k,v in prereqs],
             col_widths=[4.5*cm, W - 9.0*cm]),
    Spacer(1, 0.4*cm),
    Paragraph("Required IAM Roles (minimum)", S["h3"]),
]
roles = [
    ["Role", "Purpose"],
    ["roles/run.admin", "Deploy and configure Cloud Run services"],
    ["roles/compute.admin", "Create IPs, routers, NAT, LB resources, Cloud Armor"],
    ["roles/vpcaccess.admin", "Create Serverless VPC Access Connectors"],
    ["roles/artifactregistry.admin", "Create Artifact Registry repositories"],
    ["roles/cloudbuild.builds.editor", "Submit Cloud Build jobs"],
    ["roles/iam.securityAdmin", "Grant IAM bindings (Cloud Build → Artifact Registry)"],
]
rt = Table(roles, colWidths=[6*cm, W - 10.4*cm])
rt.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), DARK_BLUE),
    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 8.5),
    ("GRID", (0,0), (-1,-1), 0.4, GREY_LINE),
    ("LEFTPADDING", (0,0), (-1,-1), 7),
    ("TOPPADDING", (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [GREY_BG, colors.white]),
]))
story += [rt, PageBreak()]

# ─────────────────────────── SECTION 3 — CONFIG VARS ─────────────────────────
story += [
    Paragraph("3. Configuration Variables (.env)", S["h1"]),
    hr(),
    Paragraph(
        "Copy <b>.env.example</b> to <b>.env</b> in the repository root and fill in all values "
        "before running the provisioning script. The script will fail fast if any variable is missing.",
        S["body"]),
    Spacer(1, 0.2*cm),
    code_block("cp .env.example .env"),
    Spacer(1, 0.3*cm),
]

env_vars = [
    ["Variable", "Example / How to set", "Description"],
    ["PROJECT_ID", "igbokwe", "GCP project ID"],
    ["REGION", "us-central1", "GCP region for all regional resources"],
    ["VPC_NETWORK", "default", "Name of the existing VPC network"],
    ["SNOWFLAKE_HOST", "xy12345.snowflakecomputing.com", "Snowflake account hostname"],
    ["SNOWFLAKE_PORT", "443", "Snowflake HTTPS port (always 443)"],
    ["NAT_IP_NAME", "snowflake-proxy-nat-ip", "Name for the reserved regional egress IP"],
    ["NAT_ROUTER_NAME", "snowflake-router", "Name for the Cloud Router"],
    ["NAT_GATEWAY_NAME", "snowflake-nat", "Name for the Cloud NAT gateway"],
    ["VPC_CONNECTOR_NAME", "snowflake-connector", "Name for the VPC Access Connector"],
    ["VPC_CONNECTOR_SUBNET", "snowflake-connector-subnet", "Dedicated /28 subnet name (no other resources)"],
    ["CLOUD_RUN_SERVICE_NAME", "snowflake-proxy", "Cloud Run service name"],
    ["AR_REPO", "snowflake-proxy", "Artifact Registry Docker repository name"],
    ["PROXY_SECRET_PATH", "openssl rand -hex 16", "Random hex secret embedded in the URL path"],
    ["LB_DOMAIN", "proxy.yourdomain.com", "Domain name for the Global LB (you must control DNS)"],
    ["CLOUD_DNS_ZONE", "my-zone-name", "(Optional) Cloud DNS managed zone that controls LB_DOMAIN. If set, the script creates the DNS A record automatically in Step 9b. Leave blank to manage DNS manually."],
]
et = Table(env_vars, colWidths=[4.5*cm, 4.8*cm, W - 13.4*cm])
et.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), DARK_BLUE),
    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 8),
    ("GRID", (0,0), (-1,-1), 0.4, GREY_LINE),
    ("LEFTPADDING", (0,0), (-1,-1), 6),
    ("TOPPADDING", (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [GREY_BG, colors.white]),
    ("FONTNAME", (0,1), (0,-1), "Courier"),
    ("FONTNAME", (1,1), (1,-1), "Courier"),
    ("FONTSIZE", (0,1), (1,-1), 7.5),
]))
story += [
    et,
    Spacer(1, 0.3*cm),
    note_box("PROXY_SECRET_PATH must be generated fresh for each deployment. "
             "Run: openssl rand -hex 16  and paste the output into .env. "
             "Never reuse a secret path across environments."),
    PageBreak(),
]

# ─────────────────────────── SECTION 4 — PROXY FILES ─────────────────────────
story += [
    Paragraph("4. Proxy Source Files", S["h1"]),
    hr(),
    Paragraph(
        "The repository contains three files that make up the nginx proxy container. "
        "These are built into a Docker image by Cloud Build in Step 6.",
        S["body"]),
    Spacer(1, 0.2*cm),
]
files = [
    ["File", "Purpose"],
    ["proxy/Dockerfile", "Builds nginx:alpine with CA certificates and envsubst (gettext). Exposes port 8080."],
    ["proxy/entrypoint.sh", "Runs envsubst to substitute SNOWFLAKE_HOST, SNOWFLAKE_PORT, and PROXY_SECRET_PATH into the nginx config template at container startup, then starts nginx."],
    ["proxy/nginx.conf.template", "nginx reverse proxy config. Defines two location blocks: one for the secret path (strips prefix, proxies to Snowflake with TLS verification and SSE support) and a catch-all that returns 404."],
]
ft = Table(files, colWidths=[5.5*cm, W - 9.9*cm])
ft.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), DARK_BLUE),
    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 8.5),
    ("GRID", (0,0), (-1,-1), 0.4, GREY_LINE),
    ("LEFTPADDING", (0,0), (-1,-1), 7),
    ("TOPPADDING", (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [GREY_BG, colors.white]),
    ("FONTNAME", (0,1), (0,-1), "Courier"),
    ("FONTSIZE", (0,1), (0,-1), 8),
]))
story += [ft, PageBreak()]

# ─────────────────────────── SECTION 5 — STEPS ───────────────────────────────
story += [
    Paragraph("5. Provisioning Steps", S["h1"]),
    hr(),
    Paragraph(
        "Execute steps in the order shown. Each step is idempotent — if a resource already "
        "exists the command will detect it and skip creation. All gcloud commands target "
        "the project and region defined in your .env file.",
        S["body"]),
    Spacer(1, 0.3*cm),
]

# ── Step 1 ────────────────────────────────────────────────────────────────────
story += step_box("1", "Enable Required GCP APIs", [
    Paragraph(
        "Enable all GCP service APIs used by this solution. Safe to re-run — "
        "enabling an already-enabled API is a no-op.",
        S["body"]),
    code_block("""\
gcloud services enable \\
    compute.googleapis.com \\
    run.googleapis.com \\
    vpcaccess.googleapis.com \\
    artifactregistry.googleapis.com \\
    cloudbuild.googleapis.com \\
    networkservices.googleapis.com \\
    --project=<PROJECT_ID>"""),
    kv_table([
        [Paragraph("<b>compute</b>", S["note"]),   Paragraph("Cloud NAT, Cloud Router, Global LB, Cloud Armor", S["note"])],
        [Paragraph("<b>run</b>", S["note"]),        Paragraph("Cloud Run service", S["note"])],
        [Paragraph("<b>vpcaccess</b>", S["note"]),  Paragraph("Serverless VPC Access Connector", S["note"])],
        [Paragraph("<b>artifactregistry</b>", S["note"]), Paragraph("Docker image registry", S["note"])],
        [Paragraph("<b>cloudbuild</b>", S["note"]), Paragraph("Cloud-based Docker build (no local Docker required)", S["note"])],
        [Paragraph("<b>networkservices</b>", S["note"]), Paragraph("Global LB URL map and NEG wiring", S["note"])],
    ], col_widths=[3.8*cm, W - 8.2*cm]),
])

# ── Step 2 ────────────────────────────────────────────────────────────────────
story += step_box("2", "Reserve Regional Static IP (Egress)", [
    Paragraph(
        "Reserve a <b>regional</b> static external IP address. This is the IP that "
        "Snowflake's network policy will allowlist. It must be regional — Cloud NAT "
        "does not accept global addresses.",
        S["body"]),
    code_block("""\
gcloud compute addresses create <NAT_IP_NAME> \\
    --region=<REGION> \\
    --project=<PROJECT_ID> \\
    --network-tier=PREMIUM"""),
    Paragraph("Retrieve the allocated IP address:", S["body"]),
    code_block("""\
gcloud compute addresses describe <NAT_IP_NAME> \\
    --region=<REGION> \\
    --project=<PROJECT_ID> \\
    --format="value(address)" """),
    success_box("Record the IP address printed — you will add it to Snowflake's network policy in Section 6.2."),
])

# ── Step 3 ────────────────────────────────────────────────────────────────────
story += step_box("3", "Create Cloud Router", [
    Paragraph(
        "Create a Cloud Router in the VPC. The router is required by Cloud NAT (Step 4) "
        "to advertise and manage the egress IP.",
        S["body"]),
    code_block("""\
gcloud compute routers create <NAT_ROUTER_NAME> \\
    --network=<VPC_NETWORK> \\
    --region=<REGION> \\
    --project=<PROJECT_ID>"""),
])

# ── Step 4 ────────────────────────────────────────────────────────────────────
story += step_box("4", "Create Cloud NAT", [
    Paragraph(
        "Create a Cloud NAT gateway on the router. The gateway is scoped to "
        "<b>VPC_CONNECTOR_SUBNET</b> only — this ensures only traffic from the VPC "
        "Access Connector uses the static IP, not other workloads in the VPC.",
        S["body"]),
    code_block("""\
gcloud compute routers nats create <NAT_GATEWAY_NAME> \\
    --router=<NAT_ROUTER_NAME> \\
    --region=<REGION> \\
    --project=<PROJECT_ID> \\
    --nat-external-ip-pool=<NAT_IP_NAME> \\
    --nat-custom-subnet-ip-ranges=<VPC_CONNECTOR_SUBNET>"""),
    note_box(
        "--nat-custom-subnet-ip-ranges requires the VPC connector to be created with "
        "--subnet (a named subnet). Connectors created with --range use an anonymous "
        "CIDR that cannot be targeted by name."),
])

# ── Step 5 ────────────────────────────────────────────────────────────────────
story += step_box("5", "Create Artifact Registry Repository", [
    Paragraph("Create a Docker repository to store the proxy image:", S["body"]),
    code_block("""\
gcloud artifacts repositories create <AR_REPO> \\
    --repository-format=docker \\
    --location=<REGION> \\
    --project=<PROJECT_ID>"""),
    Paragraph("Grant Cloud Build write access to the repository:", S["body"]),
    code_block("""\
# Get the project number first
PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> \\
    --format="value(projectNumber)")

gcloud artifacts repositories add-iam-policy-binding <AR_REPO> \\
    --location=<REGION> \\
    --project=<PROJECT_ID> \\
    --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \\
    --role="roles/artifactregistry.writer" \\
    --condition=None"""),
])

# ── Step 6 ────────────────────────────────────────────────────────────────────
story += step_box("6", "Build & Push Docker Image", [
    Paragraph(
        "Build the nginx proxy Docker image using Cloud Build (no local Docker required). "
        "Cloud Build reads the Dockerfile from the <b>proxy/</b> directory and pushes the "
        "result to Artifact Registry.",
        S["body"]),
    code_block("""\
IMAGE="<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/proxy:latest"

gcloud builds submit proxy/ \\
    --tag="${IMAGE}" \\
    --project=<PROJECT_ID>"""),
    success_box("Build takes ~60–90 seconds. Output ends with 'SUCCESS' and the image digest."),
])

# ── Step 7 ────────────────────────────────────────────────────────────────────
story += step_box("7", "Create Serverless VPC Access Connector", [
    Paragraph(
        "Create a Serverless VPC Access Connector that bridges Cloud Run's egress into "
        "the VPC so it can exit through Cloud NAT with the static IP. The connector subnet "
        "must be a dedicated <b>/28</b> with no other resources.",
        S["body"]),
    code_block("""\
gcloud compute networks vpc-access connectors create <VPC_CONNECTOR_NAME> \\
    --region=<REGION> \\
    --project=<PROJECT_ID> \\
    --subnet=<VPC_CONNECTOR_SUBNET>"""),
    note_box(
        "Use --subnet (named subnet), not --range (anonymous CIDR). "
        "Cloud NAT in Step 4 scopes to this subnet by name — an anonymous range "
        "cannot be targeted."),
])

# ── Step 8 ────────────────────────────────────────────────────────────────────
story += step_box("8", "Deploy Cloud Run Service", [
    Paragraph(
        "Deploy the nginx proxy container to Cloud Run. Two flags are critical for security "
        "and correct egress routing:",
        S["body"]),
    Paragraph(
        "<b>--vpc-egress=all-traffic</b> — forces ALL outbound traffic through the VPC "
        "connector and therefore through Cloud NAT. Without this, only RFC-1918 traffic "
        "uses the connector and Snowflake would see a dynamic Google IP.",
        S["bullet"]),
    Paragraph(
        "<b>--ingress=internal-and-cloud-load-balancing</b> — makes the raw Cloud Run URL "
        "unreachable from the public internet. Only the Global LB (Step 13) can reach it, "
        "making Cloud Armor the mandatory entry point.",
        S["bullet"]),
    Spacer(1, 0.2*cm),
    code_block("""\
IMAGE="<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/proxy:latest"

gcloud run deploy <CLOUD_RUN_SERVICE_NAME> \\
    --image="${IMAGE}" \\
    --region=<REGION> \\
    --project=<PROJECT_ID> \\
    --vpc-connector=<VPC_CONNECTOR_NAME> \\
    --vpc-egress=all-traffic \\
    --set-env-vars="SNOWFLAKE_HOST=<SNOWFLAKE_HOST>,SNOWFLAKE_PORT=<SNOWFLAKE_PORT>,PROXY_SECRET_PATH=<PROXY_SECRET_PATH>" \\
    --port=8080 \\
    --cpu=1 \\
    --memory=512Mi \\
    --max-instances=3 \\
    --ingress=internal-and-cloud-load-balancing \\
    --allow-unauthenticated"""),
    success_box("Note the Service URL printed — it will be used in Steps 11 and referenced in verification."),
])

# ── Step 9 ────────────────────────────────────────────────────────────────────
story += step_box("9", "Reserve Global Static IP (Load Balancer)", [
    Paragraph(
        "Reserve a <b>global</b> static IP for the HTTPS Load Balancer. This must be "
        "global (not regional) — Global HTTPS Load Balancers require a global address. "
        "This is the IP the DNS A record will point to.",
        S["body"]),
    code_block("""\
gcloud compute addresses create <CLOUD_RUN_SERVICE_NAME>-lb-ip \\
    --global \\
    --project=<PROJECT_ID>

# Retrieve the allocated IP
gcloud compute addresses describe <CLOUD_RUN_SERVICE_NAME>-lb-ip \\
    --global \\
    --project=<PROJECT_ID> \\
    --format="value(address)" """),
    success_box("Record the LB IP address — it is used in Step 9b to create the DNS A record."),
])

# ── Step 9b ───────────────────────────────────────────────────────────────────
story += step_box("9b", "Create DNS A Record for LB_DOMAIN", [
    Paragraph(
        "Create a DNS A record pointing <b>LB_DOMAIN</b> at the LB IP from Step 9. "
        "The Google-managed SSL certificate (Step 10) will remain in PROVISIONING status "
        "until this record resolves publicly.",
        S["body"]),
    Paragraph("<b>Option 1 — Automated (Cloud DNS zone in the same GCP project):</b>", S["h3"]),
    Paragraph(
        "If LB_DOMAIN is managed by a Cloud DNS zone in the same project, set "
        "<b>CLOUD_DNS_ZONE</b> in .env. The setup script creates the record automatically "
        "in Step 9b. No manual action required.",
        S["body"]),
    code_block("""\
# Automated — done by setup_psc_proxy.sh when CLOUD_DNS_ZONE is set
gcloud dns record-sets create <LB_DOMAIN>. \\
    --zone=<CLOUD_DNS_ZONE> \\
    --type=A \\
    --ttl=300 \\
    --rrdatas=<LB_IP> \\
    --project=<PROJECT_ID>"""),
    Paragraph("<b>Option 2 — Manual (external DNS provider):</b>", S["h3"]),
    Paragraph(
        "If LB_DOMAIN is managed outside GCP, create the record in your DNS provider's console:",
        S["body"]),
    kv_table([
        [Paragraph("<b>Type</b>", S["note"]),  Paragraph("A", S["note"])],
        [Paragraph("<b>Name</b>", S["note"]),  Paragraph("<LB_DOMAIN>", S["note"])],
        [Paragraph("<b>Value</b>", S["note"]), Paragraph("<LB IP from Step 9>", S["note"])],
        [Paragraph("<b>TTL</b>", S["note"]),   Paragraph("300", S["note"])],
    ], col_widths=[2.5*cm, W - 7.0*cm]),
    Spacer(1, 0.2*cm),
    Paragraph("Verify propagation:", S["body"]),
    code_block("nslookup <LB_DOMAIN>"),
    note_box("Do not proceed to Step 10 until nslookup returns the correct LB IP. "
             "The SSL certificate will not provision until DNS is live."),
])

# ── Step 10 ───────────────────────────────────────────────────────────────────
story += step_box("10", "Create Google-Managed SSL Certificate", [
    Paragraph(
        "Create a Google-managed SSL certificate for LB_DOMAIN. Google automatically "
        "provisions and renews the certificate once the DNS A record for LB_DOMAIN "
        "resolves to the LB IP (Step 9b). Provisioning typically takes ~15 minutes "
        "after DNS propagates.",
        S["body"]),
    code_block("""\
gcloud compute ssl-certificates create <CLOUD_RUN_SERVICE_NAME>-cert \\
    --domains=<LB_DOMAIN> \\
    --global \\
    --project=<PROJECT_ID>"""),
    Paragraph("Check provisioning status:", S["body"]),
    code_block("""\
gcloud compute ssl-certificates describe <CLOUD_RUN_SERVICE_NAME>-cert \\
    --global \\
    --project=<PROJECT_ID> \\
    --format="value(managed.status,managed.domainStatus)" """),
    note_box("Status shows PROVISIONING until DNS propagates. Wait for ACTIVE before testing the endpoint."),
])

# ── Step 11 ───────────────────────────────────────────────────────────────────
story += step_box("11", "Create Serverless Network Endpoint Group (NEG)", [
    Paragraph(
        "Create a Serverless NEG that connects the Global LB to the Cloud Run service "
        "without requiring a VPC. The NEG is regional and matched to the Cloud Run region.",
        S["body"]),
    code_block("""\
gcloud compute network-endpoint-groups create <CLOUD_RUN_SERVICE_NAME>-neg \\
    --region=<REGION> \\
    --network-endpoint-type=serverless \\
    --cloud-run-service=<CLOUD_RUN_SERVICE_NAME> \\
    --project=<PROJECT_ID>"""),
])

# ── Step 12 ───────────────────────────────────────────────────────────────────
story += step_box("12", "Create Global Backend Service", [
    Paragraph(
        "Create a global backend service and attach the Serverless NEG. "
        "The backend service is the LB component that holds the NEG and will carry "
        "the Cloud Armor security policy (attached in Step 14).",
        S["body"]),
    code_block("""\
# Create backend service
gcloud compute backend-services create <CLOUD_RUN_SERVICE_NAME>-backend \\
    --global \\
    --project=<PROJECT_ID>

# Attach the Serverless NEG
gcloud compute backend-services add-backend <CLOUD_RUN_SERVICE_NAME>-backend \\
    --global \\
    --network-endpoint-group=<CLOUD_RUN_SERVICE_NAME>-neg \\
    --network-endpoint-group-region=<REGION> \\
    --project=<PROJECT_ID>"""),
])

# ── Step 13 ───────────────────────────────────────────────────────────────────
story += step_box("13", "Create Global HTTPS Load Balancer", [
    Paragraph(
        "Wire together three resources to form the Global HTTPS Load Balancer:",
        S["body"]),
    Paragraph("<b>URL map</b> — routes all traffic to the backend service.", S["bullet"]),
    Paragraph("<b>Target HTTPS proxy</b> — terminates TLS using the managed certificate.", S["bullet"]),
    Paragraph("<b>Forwarding rule</b> — binds the global IP to the HTTPS proxy on port 443.", S["bullet"]),
    Spacer(1, 0.2*cm),
    code_block("""\
# URL map
gcloud compute url-maps create <CLOUD_RUN_SERVICE_NAME>-urlmap \\
    --default-service=<CLOUD_RUN_SERVICE_NAME>-backend \\
    --global \\
    --project=<PROJECT_ID>

# HTTPS proxy (attaches the SSL certificate)
gcloud compute target-https-proxies create <CLOUD_RUN_SERVICE_NAME>-https-proxy \\
    --url-map=<CLOUD_RUN_SERVICE_NAME>-urlmap \\
    --ssl-certificates=<CLOUD_RUN_SERVICE_NAME>-cert \\
    --global \\
    --project=<PROJECT_ID>

# Forwarding rule (binds global IP → HTTPS proxy → :443)
gcloud compute forwarding-rules create <CLOUD_RUN_SERVICE_NAME>-fwd \\
    --global \\
    --target-https-proxy=<CLOUD_RUN_SERVICE_NAME>-https-proxy \\
    --address=<CLOUD_RUN_SERVICE_NAME>-lb-ip \\
    --ports=443 \\
    --project=<PROJECT_ID>"""),
])

# ── Step 14 ───────────────────────────────────────────────────────────────────
story += step_box("14", "Create Cloud Armor Security Policy", [
    Paragraph(
        "Create a Cloud Armor security policy and attach it to the backend service. "
        "Evaluation happens at the LB edge before requests reach Cloud Run. "
        "The policy uses the Google Threat Intelligence feed to allow only GCP source IPs.",
        S["body"]),
    code_block("""\
# Create the security policy
gcloud compute security-policies create <CLOUD_RUN_SERVICE_NAME>-armor \\
    --description="Allow GCP source IPs only via Threat Intelligence feed" \\
    --project=<PROJECT_ID>

# Priority 1000: allow GCP IP ranges (Gemini runs on GCP)
gcloud compute security-policies rules create 1000 \\
    --security-policy=<CLOUD_RUN_SERVICE_NAME>-armor \\
    --expression="evaluateThreatIntelligence('iplist-public-clouds-gcp')" \\
    --action=allow \\
    --project=<PROJECT_ID>

# Default rule (priority 2147483647): deny everything else with HTTP 403
gcloud compute security-policies rules update 2147483647 \\
    --security-policy=<CLOUD_RUN_SERVICE_NAME>-armor \\
    --action=deny-403 \\
    --project=<PROJECT_ID>

# Attach the policy to the backend service
gcloud compute backend-services update <CLOUD_RUN_SERVICE_NAME>-backend \\
    --global \\
    --security-policy=<CLOUD_RUN_SERVICE_NAME>-armor \\
    --project=<PROJECT_ID>"""),
    note_box(
        "evaluateThreatIntelligence('iplist-public-clouds-gcp') requires Cloud Armor "
        "Enterprise enrollment at the project level. Without this subscription, "
        "the rule creation command will fail with an invalid expression error."),
    PageBreak(),
])

# ─────────────────────────── SECTION 6 — POST-PROVISIONING ───────────────────
story += [
    Paragraph("6. Post-Provisioning Configuration", S["h1"]),
    hr(),
    Paragraph(
        "Complete these steps after all provisioning steps succeed.",
        S["body"]),
    Spacer(1, 0.3*cm),

    Paragraph("6.1  DNS A Record", S["h2"]),
    Paragraph(
        "If <b>CLOUD_DNS_ZONE</b> was set in .env, the DNS A record was created automatically "
        "in Step 9b — no action needed here. Verify with:",
        S["body"]),
    code_block("nslookup <LB_DOMAIN>"),
    Paragraph(
        "If CLOUD_DNS_ZONE was not set, create the A record manually in your DNS provider "
        "before the SSL certificate can provision:",
        S["body"]),
]
dns_data = [
    ["Record type", "Name", "Value", "TTL"],
    ["A", "<LB_DOMAIN>", "<LB IP from Step 9>", "300"],
]
dns_t = Table(dns_data, colWidths=[2.5*cm, 5.5*cm, 4.5*cm, 2.0*cm])
dns_t.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), DARK_BLUE),
    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 8.5),
    ("GRID", (0,0), (-1,-1), 0.4, GREY_LINE),
    ("LEFTPADDING", (0,0), (-1,-1), 7),
    ("TOPPADDING", (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [GREY_BG, colors.white]),
]))
story += [
    dns_t,
    Spacer(1, 0.3*cm),
    Paragraph("Verify DNS propagation:", S["body"]),
    code_block("nslookup <LB_DOMAIN>"),
    Spacer(1, 0.4*cm),

    Paragraph("6.2  Snowflake Network Policy", S["h2"]),
    Paragraph(
        "Add the static egress IP (from Step 2) to your Snowflake network policy. "
        "Run this in Snowsight or via the Snowflake CLI:",
        S["body"]),
    code_block("""\
ALTER NETWORK POLICY <your_policy_name>
  ADD ALLOWED_IP_LIST = ('<STATIC_EGRESS_IP>/32');"""),
    Spacer(1, 0.4*cm),

    Paragraph("6.3  Gemini Enterprise Connector", S["h2"]),
    Paragraph(
        "Configure the Gemini Enterprise connector with the following endpoint URL. "
        "The URL includes the secret path segment — this must be kept confidential.",
        S["body"]),
    code_block("https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/"),
    Spacer(1, 0.2*cm),
    note_box(
        "The trailing slash after PROXY_SECRET_PATH is required. "
        "nginx will return 404 if the path does not include the exact secret segment.",
        bg=WARN_BG, line=WARN_LINE, label="IMPORTANT"),
    PageBreak(),
]

# ─────────────────────────── SECTION 7 — VERIFICATION ────────────────────────
story += [
    Paragraph("7. Verification", S["h1"]),
    hr(),
    Paragraph("Run these checks in order to confirm the full data path is working:", S["body"]),
    Spacer(1, 0.2*cm),
    Paragraph("7.1  Secret Path Gate", S["h3"]),
    Paragraph("A request to any path other than the secret path must return HTTP 404:", S["body"]),
    code_block("curl -si https://<LB_DOMAIN>/anything | head -5"),
    Paragraph("Expected: HTTP/2 404", S["note"]),
    Spacer(1, 0.3*cm),

    Paragraph("7.2  Cloud Armor Gate", S["h3"]),
    Paragraph("The direct Cloud Run URL must be unreachable (connection refused or HTTP 403):", S["body"]),
    code_block("curl -si https://<cloud-run-url>/ | head -5"),
    Paragraph("Expected: connection refused or HTTP 403", S["note"]),
    Spacer(1, 0.3*cm),

    Paragraph("7.3  Proxy Connectivity", S["h3"]),
    Paragraph(
        "A request with the correct secret path should reach Snowflake. "
        "Any Snowflake response (including 401 Unauthorized) confirms the proxy is forwarding correctly:",
        S["body"]),
    code_block("""\
curl -si https://<LB_DOMAIN>/<PROXY_SECRET_PATH>/api/v2/mcp/sse \\
    -H 'Authorization: Bearer <snowflake_token>' | head -10"""),
    Paragraph("Expected: any HTTP response from Snowflake (401 without credentials is correct behaviour)", S["note"]),
    Spacer(1, 0.3*cm),

    Paragraph("7.4  Confirm Snowflake Sees the Static IP", S["h3"]),
    Paragraph(
        "After running a query through the Gemini connector, verify in Snowsight "
        "that the client IP matches the reserved static egress IP:",
        S["body"]),
    code_block("""\
SELECT client_net_address, user_name, start_time
FROM TABLE(information_schema.query_history(
    daterange_start => dateadd('hour', -1, current_timestamp())))
ORDER BY start_time DESC
LIMIT 5;"""),
    Paragraph("Expected: client_net_address = <STATIC_EGRESS_IP>", S["note"]),
    Spacer(1, 0.3*cm),

    Paragraph("7.5  SSL Certificate Status", S["h3"]),
    code_block("""\
gcloud compute ssl-certificates describe <CLOUD_RUN_SERVICE_NAME>-cert \\
    --global --project=<PROJECT_ID> \\
    --format="value(managed.status,managed.domainStatus)" """),
    Paragraph("Expected: ACTIVE  /  <LB_DOMAIN>=ACTIVE", S["note"]),
    PageBreak(),
]

# ─────────────────────────── SECTION 8 — ROTATION ────────────────────────────
story += [
    Paragraph("8. Secret Rotation", S["h1"]),
    hr(),
    Paragraph(
        "Rotate the PROXY_SECRET_PATH if it is compromised or as part of regular key rotation. "
        "The Gemini connector endpoint URL must be updated at the same time.",
        S["body"]),
    Spacer(1, 0.2*cm),
    Paragraph("Step 1 — Generate a new secret:", S["h3"]),
    code_block("openssl rand -hex 16"),
    Paragraph("Step 2 — Update PROXY_SECRET_PATH in .env:", S["h3"]),
    code_block("# Replace the existing PROXY_SECRET_PATH value in .env with the new value"),
    Paragraph("Step 3 — Redeploy Cloud Run to pick up the new value:", S["h3"]),
    code_block("""\
gcloud run deploy <CLOUD_RUN_SERVICE_NAME> \\
    --image=<REGION>-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/proxy:latest \\
    --region=<REGION> \\
    --project=<PROJECT_ID> \\
    --update-env-vars="PROXY_SECRET_PATH=<NEW_SECRET_PATH>" """),
    Paragraph("Step 4 — Update the Gemini Enterprise connector endpoint URL:", S["h3"]),
    code_block("https://<LB_DOMAIN>/<NEW_PROXY_SECRET_PATH>/"),
    note_box(
        "During the time between redeployment and updating the Gemini connector, "
        "requests using the old secret path will receive HTTP 404. "
        "Plan rotation during a maintenance window to avoid connector downtime."),
    PageBreak(),
]

# ─────────────────────────── SECTION 9 — SUMMARY TABLE ───────────────────────
story += [
    Paragraph("9. Resources Provisioned — Summary Table", S["h1"]),
    hr(),
    Paragraph(
        "All resources created by this runbook, in provisioning order.",
        S["body"]),
    Spacer(1, 0.3*cm),
]
summary = [
    ["Step", "Resource", "Type", "Scope", "Purpose"],
    ["2",  "<NAT_IP_NAME>",                    "External IP",          "Regional", "Fixed egress IP allowlisted in Snowflake"],
    ["3",  "<NAT_ROUTER_NAME>",                "Cloud Router",         "Regional", "Enables Cloud NAT"],
    ["4",  "<NAT_GATEWAY_NAME>",               "Cloud NAT",            "Regional", "Routes connector egress through static IP"],
    ["5",  "<AR_REPO>",                        "Artifact Registry",    "Regional", "Stores the nginx proxy Docker image"],
    ["6",  "proxy:latest",                     "Docker Image",         "Regional", "nginx proxy container built by Cloud Build"],
    ["7",  "<VPC_CONNECTOR_NAME>",             "VPC Connector",        "Regional", "Bridges Cloud Run egress into VPC"],
    ["8",  "<CLOUD_RUN_SERVICE_NAME>",         "Cloud Run Service",    "Regional", "nginx proxy; ingress locked to LB only"],
    ["9",  "<CLOUD_RUN_SERVICE_NAME>-lb-ip",   "Global IP",            "Global",   "Front-door IP; DNS A record points here"],
    ["9b", "<LB_DOMAIN>",                     "DNS A Record",         "Global",   "Auto-created if CLOUD_DNS_ZONE set; else manual"],
    ["10", "<CLOUD_RUN_SERVICE_NAME>-cert",    "SSL Certificate",      "Global",   "TLS for LB_DOMAIN; auto-renewed"],
    ["11", "<CLOUD_RUN_SERVICE_NAME>-neg",     "Serverless NEG",       "Regional", "Connects Global LB to Cloud Run"],
    ["12", "<CLOUD_RUN_SERVICE_NAME>-backend", "Backend Service",      "Global",   "LB backend; carries Cloud Armor policy"],
    ["13", "<CLOUD_RUN_SERVICE_NAME>-urlmap",  "URL Map",              "Global",   "Routes all paths to backend service"],
    ["13", "<CLOUD_RUN_SERVICE_NAME>-https-proxy","HTTPS Proxy",       "Global",   "Terminates TLS with managed cert"],
    ["13", "<CLOUD_RUN_SERVICE_NAME>-fwd",     "Forwarding Rule",      "Global",   "Binds global IP to HTTPS proxy on :443"],
    ["14", "<CLOUD_RUN_SERVICE_NAME>-armor",   "Cloud Armor Policy",   "Global",   "Allows GCP IPs; denies all others (403)"],
]
st = Table(summary, colWidths=[1.2*cm, 5.0*cm, 3.2*cm, 2.0*cm, W - 15.4*cm])
st.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), DARK_BLUE),
    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 7.5),
    ("GRID", (0,0), (-1,-1), 0.4, GREY_LINE),
    ("LEFTPADDING", (0,0), (-1,-1), 5),
    ("TOPPADDING", (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [GREY_BG, colors.white]),
    ("FONTNAME", (1,1), (1,-1), "Courier"),
    ("FONTSIZE", (1,1), (1,-1), 7),
]))
story += [st, Spacer(1, 0.8*cm), hr(),
          Paragraph(f"Snowflake Connector Proxy — Administrator Runbook v1.0 — {date.today().strftime('%B %d, %Y')}", S["center"])]

# ── Build ──────────────────────────────────────────────────────────────────────
doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
print(f"PDF written to {OUTPUT}")
