"""Evidence Agent — mocked connectors (Day 3, addresses Gap 2 and Gap 4).

Each connector returns hardcoded, realistic JSON for the demo scenario (a
storage bucket goes public via a bad release, then a large upload, then a
suspicious Azure OpenAI call from the same environment). A real deploy swaps
these bodies for actual API calls against Azure Monitor / Kubernetes / GitHub
/ IAM logs — the `fetch()` signature and the trust-tagging shape don't change.

Confidence scores are fixed per source, per the plan: Monitor=0.95, K8s=0.9,
GitHub=0.85. iam_logs isn't specified in the plan; 0.8 keeps it below the
other three since IAM logs are noisier/more prone to benign false positives.
"""

from datetime import datetime, timezone
from typing import Callable

CONFIDENCE = {
    "azure_monitor": 0.95,
    "kubernetes": 0.90,
    "github_commits": 0.85,
    "iam_logs": 0.80,
}

# Connector order to try per incident signal type — the plan's "simple
# if/else, no magic needed" connector-selection rule. The LLM planner (see
# graph.py) still picks the *next single* connector each iteration, but never
# suggests one outside this incident type's relevant set.
CONNECTOR_ORDER = {
    "PublicStorageBucket": ["azure_monitor", "github_commits", "iam_logs", "kubernetes"],
    "LargeDataUpload": ["azure_monitor", "kubernetes", "iam_logs", "github_commits"],
    "UnauthorizedAPICall": ["iam_logs", "azure_monitor", "github_commits", "kubernetes"],
}
DEFAULT_ORDER = ["azure_monitor", "kubernetes", "github_commits", "iam_logs"]


def _azure_monitor(query: str) -> dict:
    return {
        "deployment_id": "rel-20260727-0342",
        "resource": query,
        "event": "storage_account_config_change",
        "change": "public_network_access: Disabled -> Enabled; allow_blob_public_access: false -> true",
        "deployed_by": "svc-deploy-bot",
        "minutes_before_incident": 6,
        "pipeline": "infra-terraform-apply",
    }


def _kubernetes(query: str) -> dict:
    return {
        "namespace": "prod-analytics",
        "resource": query,
        "event": "pod_restart",
        "pod": "analytics-exporter-7f8b9c-x2j4k",
        "restart_count": 3,
        "reason": "OOMKilled",
        "restarted_at_offset_minutes": -4,
    }


def _github_commits(query: str) -> dict:
    return {
        "repo": "org/infra-terraform",
        "resource": query,
        "commit_sha": "a1b2c3d4",
        "author": "svc-deploy-bot",
        "message": "bump storage module to v3.2 (enable public read for CDN migration)",
        "file_changed": "modules/storage/main.tf",
        "diff_summary": "allow_blob_public_access = false -> true",
        "merged_minutes_before_incident": 8,
    }


def _iam_logs(query: str) -> dict:
    return {
        "resource": query,
        "caller": "svc-deploy-bot",
        "api": "azure.openai.completions",
        "call_count_last_hour": 47,
        "baseline_call_count_last_hour": 2,
        "source_ip": "10.0.4.12",
        "event": "anomalous_api_volume",
    }


_CONNECTORS: dict[str, Callable[[str], dict]] = {
    "azure_monitor": _azure_monitor,
    "kubernetes": _kubernetes,
    "github_commits": _github_commits,
    "iam_logs": _iam_logs,
}


def connector_order_for(signal_type: str) -> list[str]:
    return CONNECTOR_ORDER.get(signal_type, DEFAULT_ORDER)


def fetch(connector_name: str, query: str) -> dict:
    """Fetch mocked evidence from one connector, tagged with trust metadata.

    Returns the Evidence Trust Layer shape: {data, source, connector,
    confidence, fetched_at}.
    """
    handler = _CONNECTORS.get(connector_name)
    if handler is None:
        raise ValueError(f"Unknown connector: {connector_name}")
    return {
        "connector": connector_name,
        "source": connector_name,
        "confidence": CONFIDENCE[connector_name],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": handler(query),
    }
