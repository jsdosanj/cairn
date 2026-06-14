"""Human-facing metadata for every integration: what to ask, what it means.

One source of truth for the setup wizard, the `doctor` command, and the web
dashboard. Keeping the "what does this provider need" knowledge here (rather than
scattered across each provider's validate_config) lets the UX describe any
integration without importing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Field:
    key: str
    label: str
    help: str = ""
    secret: bool = False          # store in keychain / mask in UI
    required: bool = False
    default: Optional[str] = None
    placeholder: str = ""


@dataclass
class ProviderMeta:
    key: str
    display: str
    blurb: str
    fields: list[Field] = field(default_factory=list)
    note: str = ""


SOURCES: dict[str, ProviderMeta] = {
    "jamf": ProviderMeta(
        "jamf", "Jamf Pro", "Apple MDM (computers, mobile).",
        [
            Field("url", "Server URL", "Your Jamf Pro URL.", required=True,
                  placeholder="https://your.jamfcloud.com"),
            Field("client_id", "API Client ID", "From an API Role/Client.", secret=True),
            Field("client_secret", "API Client Secret", secret=True),
            Field("username", "API username", "Only if not using a client ID."),
            Field("password", "API password", secret=True),
        ],
        note="Use either a client_id+client_secret (preferred) or username+password.",
    ),
    "intune": ProviderMeta(
        "intune", "Microsoft Intune", "Microsoft endpoint manager via Graph.",
        [
            Field("tenant_id", "Azure tenant ID", required=True),
            Field("client_id", "App (client) ID", required=True),
            Field("client_secret", "Client secret", secret=True, required=True),
        ],
    ),
    "kandji": ProviderMeta(
        "kandji", "Kandji", "Apple MDM.",
        [
            Field("api_url", "API URL", "Your Kandji API base URL.", required=True,
                  placeholder="https://SUBDOMAIN.api.kandji.io"),
            Field("api_token", "API token", secret=True, required=True),
        ],
    ),
    "jumpcloud": ProviderMeta(
        "jumpcloud", "JumpCloud", "Cross-platform directory + device management.",
        [
            Field("api_key", "API key", secret=True, required=True),
            Field("org_id", "Org ID", "Only for multi-tenant admins."),
        ],
    ),
    "google_workspace": ProviderMeta(
        "google_workspace", "Google Workspace (ChromeOS)", "ChromeOS devices.",
        [
            Field("subject", "Admin email", "Admin to impersonate (delegation).",
                  required=True, placeholder="admin@yourdomain.com"),
            Field("service_account_file", "Service account JSON path", required=True,
                  placeholder="/path/to/service-account.json"),
            Field("customer_id", "Customer ID", default="my_customer"),
        ],
        note="Needs a service account with domain-wide delegation. "
             "Install with: pip install 'cairn-sync[google]'.",
    ),
    "crowdstrike": ProviderMeta(
        "crowdstrike", "CrowdStrike Falcon", "EDR.",
        [
            Field("client_id", "Client ID", required=True),
            Field("client_secret", "Client secret", secret=True, required=True),
            Field("base_url", "API base URL", "Region-specific.",
                  default="https://api.crowdstrike.com"),
        ],
    ),
    "sophos": ProviderMeta(
        "sophos", "Sophos Central", "EDR.",
        [
            Field("client_id", "Client ID", required=True),
            Field("client_secret", "Client secret", secret=True, required=True),
        ],
    ),
    "defender": ProviderMeta(
        "defender", "Microsoft Defender for Endpoint", "EDR (enrichment).",
        [
            Field("tenant_id", "Azure tenant ID", required=True),
            Field("client_id", "App (client) ID", required=True),
            Field("client_secret", "Client secret", secret=True, required=True),
        ],
    ),
    "apple_bm": ProviderMeta(
        "apple_bm", "Apple Business Manager", "Apple device purchase/enrollment records.",
        [
            Field("client_id", "API client ID", required=True),
            Field("key_id", "Private key ID", required=True),
            Field("private_key_file", "Private key (.pem) path", required=True,
                  placeholder="/path/to/abm-key.pem"),
        ],
        note="Modern ABM API. Install with: pip install 'cairn-sync[apple]'.",
    ),
    "unifi": ProviderMeta(
        "unifi", "UniFi", "Ubiquiti network gear (APs, switches, gateways).",
        [
            Field("host", "Controller URL", required=True, placeholder="https://192.168.1.1"),
            Field("api_key", "API key", secret=True, required=True),
            Field("ca_bundle", "CA bundle path", "Trusted CA for self-signed certs.",
                  placeholder="/path/to/controller-ca.pem"),
        ],
    ),
    "cdw": ProviderMeta(
        "cdw", "CDW (procurement)", "Import a CDW order/invoice CSV export.",
        [
            Field("csv_file", "CSV file path", required=True,
                  placeholder="/path/to/cdw-orders.csv"),
        ],
        note="File import: creates assets with purchase metadata (order, cost, date).",
    ),
    "rudder": ProviderMeta(
        "rudder", "Rudder", "Open-source config management / audit inventory.",
        [
            Field("url", "Rudder URL", required=True, placeholder="https://rudder.example.com"),
            Field("api_token", "API token", secret=True, required=True),
            Field("ca_bundle", "CA bundle path", "Trusted CA for self-signed certs.",
                  placeholder="/path/to/rudder-ca.pem"),
        ],
    ),
    "snipeit": ProviderMeta(
        "snipeit", "Snipe-IT (read)", "Read assets from a Snipe-IT instance.",
        [
            Field("url", "API URL", "Ends in /api/v1.", required=True,
                  placeholder="https://assets.example.com/api/v1"),
            Field("token", "API token", secret=True, required=True),
        ],
        note="Mainly used as the read side of writeback; the sink config is reused automatically.",
    ),
}

# Writeback targets (reverse sync: Snipe-IT asset tag -> MDM).
WRITEBACKS: dict[str, ProviderMeta] = {
    "jamf": ProviderMeta(
        "jamf", "Jamf Pro (writeback)", "Push the Snipe-IT asset tag into Jamf.",
        [
            Field("url", "Server URL", required=True, placeholder="https://your.jamfcloud.com"),
            Field("client_id", "API Client ID", secret=True),
            Field("client_secret", "API Client Secret", secret=True),
            Field("conflict", "Conflict policy", "snipe_wins | only_if_empty",
                  default="snipe_wins"),
        ],
    ),
    "intune": ProviderMeta(
        "intune", "Microsoft Intune (writeback)", "Write the asset tag to a device field.",
        [
            Field("tenant_id", "Azure tenant ID", required=True),
            Field("client_id", "App (client) ID", required=True),
            Field("client_secret", "Client secret", secret=True, required=True),
            Field("target_field", "Target field", "managedDevice property.",
                  default="notes"),
            Field("conflict", "Conflict policy", "snipe_wins | only_if_empty",
                  default="only_if_empty"),
        ],
    ),
}

SINKS: dict[str, ProviderMeta] = {
    "snipeit": ProviderMeta(
        "snipeit", "Snipe-IT", "Your asset system of record.",
        [
            Field("url", "API URL", "Ends in /api/v1.", required=True,
                  placeholder="https://assets.example.com/api/v1"),
            Field("token", "API token", secret=True, required=True),
            Field("company_id", "Default company ID", default="1"),
            Field("site_id", "Default site ID", default="1"),
            Field("status_id", "Default status ID", default="2"),
        ],
    ),
}

NOTIFIERS: dict[str, ProviderMeta] = {
    "teams": ProviderMeta("teams", "Microsoft Teams", "Run summaries to a channel.",
                          [Field("webhook_url", "Incoming webhook URL", secret=True, required=True)]),
    "slack": ProviderMeta("slack", "Slack", "Run summaries to a channel.",
                          [Field("webhook_url", "Incoming webhook URL", secret=True, required=True)]),
    "webhook": ProviderMeta("webhook", "Generic webhook", "POST run summaries anywhere.",
                            [Field("url", "Endpoint URL", required=True)]),
}


def all_meta() -> dict[str, dict[str, ProviderMeta]]:
    return {"sources": SOURCES, "sinks": SINKS, "notifiers": NOTIFIERS}


def get_meta(section: str, key: str) -> Optional[ProviderMeta]:
    return {"sources": SOURCES, "sinks": SINKS, "notifiers": NOTIFIERS}.get(section, {}).get(key)
