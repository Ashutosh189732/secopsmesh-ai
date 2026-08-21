"""Evidence Agent — mocked connectors (Day 3, addresses Gap 2 and Gap 4).

Each connector returns hardcoded, realistic JSON for the demo scenario. A real
deploy swaps these bodies for actual API calls against Azure Monitor / Kubernetes
/ GitHub / IAM logs — the `fetch()` signature and trust-tagging shape don't change.

Confidence scores are fixed per source, per the plan: Monitor=0.95, K8s=0.9,
GitHub=0.85, iam_logs=0.8 (IAM logs are noisier/more prone to benign false positives).

Connector selection has two modes (controlled by USE_AGENTIC_CONNECTOR_SELECTION):
- Hard-coded: Pre-defined connector order per signal type (fast, deterministic)
- Agentic: LLM chooses from all connectors based on incident context (autonomous)
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


def _detect_scenario_type(context: dict) -> str:
    """Detect scenario type from signal patterns.

    Returns: "storage_gdpr" | "ml_exfiltration" | "access_control" | "kubernetes" | "noise"
    """
    signal_type = context.get("signal_type", "")
    details = context.get("details", {})
    severity = context.get("severity", "low")
    timeline = context.get("timeline", [])
    resource = context.get("resource_name", "")

    # Noise indicators: low severity + blocked outcomes or dev/sandbox resources
    if severity == "low":
        for event in timeline:
            if event.get("outcome") == "blocked":
                return "noise"
        if any(tag in resource.lower() for tag in ["dev", "sandbox", "test", "qa"]):
            return "noise"

    # Storage/GDPR: PublicStorageBucket signals or bucket ACL details
    if signal_type == "PublicStorageBucket" or details.get("bucket_acl"):
        return "storage_gdpr"

    # ML/Exfiltration: OpenAI API calls
    if "openai" in details.get("api", "").lower():
        return "ml_exfiltration"

    # Kubernetes: Any event from kubernetes source
    for event in timeline:
        if event.get("source") == "kubernetes":
            return "kubernetes"

    # Access Control: Key Vault or secrets enumeration
    api = details.get("api", "").lower()
    if "keyvault" in api or "secrets" in api:
        return "access_control"

    if signal_type == "UnauthorizedAPICall":
        return "access_control"

    return "storage_gdpr"  # fallback


def _get_primary_actor(context: dict) -> dict:
    """Extract primary actor from first timeline event."""
    timeline = context.get("timeline", [])
    if timeline and timeline[0].get("actor"):
        actor = timeline[0]["actor"]
        return {
            "type": actor.get("type", "unknown"),
            "id": actor.get("id", "unknown"),
            "ip": actor.get("ip_address", "unknown"),
        }
    return {"type": "unknown", "id": "unknown", "ip": "unknown"}


def _azure_monitor(context: dict) -> dict:
    scenario = _detect_scenario_type(context)
    resource = context.get("resource_name", "unknown-resource")
    details = context.get("details", {})
    actor = _get_primary_actor(context)

    if scenario == "storage_gdpr":
        return {
            "deployment_id": "rel-20260727-0342",
            "resource": resource,
            "event": "storage_account_config_change",
            "change": "public_network_access: Disabled -> Enabled; allow_blob_public_access: false -> true",
            "deployed_by": actor["id"],
            "actor_type": actor["type"],
            "source_ip": actor["ip"],
            "minutes_before_incident": 6,
            "pipeline": "infra-terraform-apply",
            "acl_change": details.get("bucket_acl", "public-read"),
        }

    elif scenario == "ml_exfiltration":
        return {
            "deployment_id": "rel-20260815-1204",
            "resource": resource,
            "event": "ml_gateway_config_change",
            "change": "api_rate_limit: 100 -> unlimited; auth_required: true -> false",
            "deployed_by": actor["id"],
            "source_ip": actor["ip"],
            "minutes_before_incident": 8,
            "pipeline": "ml-gateway-deploy",
        }

    elif scenario == "access_control":
        return {
            "resource": resource,
            "event": "keyvault_access_policy_change",
            "change": f"added GET/LIST permissions for {actor['id']}",
            "deployed_by": actor["id"],
            "source_ip": actor["ip"],
            "minutes_before_incident": 5,
            "pipeline": "iam-policy-update",
        }

    elif scenario == "kubernetes":
        return {
            "resource": resource,
            "event": "persistent_volume_mount_change",
            "change": "added external storage mount to training pods",
            "deployed_by": actor["id"],
            "minutes_before_incident": 3,
            "pipeline": "k8s-config-apply",
        }

    else:  # noise
        return {
            "resource": resource,
            "event": "dev_config_change",
            "deployed_by": actor["id"],
            "environment": "dev/sandbox",
            "blocked": True,
        }


def _kubernetes(context: dict) -> dict:
    scenario = _detect_scenario_type(context)
    resource = context.get("resource_name", "unknown-resource")
    details = context.get("details", {})
    actor = _get_primary_actor(context)

    if scenario == "storage_gdpr":
        return {
            "namespace": "prod-analytics",
            "resource": resource,
            "event": "pod_restart",
            "pod": f"{resource}-exporter-7f8b9c-x2j4k",
            "restart_count": 3,
            "reason": "OOMKilled",
            "restarted_at_offset_minutes": -4,
            "service_account": actor["id"],
        }

    elif scenario == "ml_exfiltration":
        return {
            "namespace": "prod-ml",
            "resource": resource,
            "event": "high_network_egress",
            "pod": f"{resource}-api-7d9k2s-m4p8n",
            "egress_gb_last_hour": 12.3,
            "baseline_egress_gb": 0.5,
            "service_account": actor["id"],
        }

    elif scenario == "access_control":
        return {
            "namespace": "prod-services",
            "resource": resource,
            "event": "secret_access_spike",
            "pod": f"{resource}-worker-3x7f9b-k2m4j",
            "secret_access_count": details.get("call_count_last_hour", 12),
            "service_account": actor["id"],
        }

    elif scenario == "kubernetes":
        return {
            "namespace": "prod-ml-training",
            "resource": resource,
            "event": "large_volume_write",
            "pod": f"{resource}-trainer-7f8b9c-x2j4k",
            "volume_write_gb": details.get("size_gb", 8.7),
            "reason": "TrainingBatchUpload",
            "service_account": actor["id"],
        }

    else:  # noise
        return {
            "namespace": "dev",
            "resource": resource,
            "event": "pod_sandbox_terminated",
            "pod": f"{resource}-test-runner",
            "reason": "Completed",
            "exit_code": 0,
        }


def _github_commits(context: dict) -> dict:
    scenario = _detect_scenario_type(context)
    resource = context.get("resource_name", "unknown-resource")
    actor = _get_primary_actor(context)

    if scenario == "storage_gdpr":
        return {
            "repo": "org/infra-terraform",
            "resource": resource,
            "commit_sha": "a1b2c3d4",
            "author": actor["id"],
            "message": "bump storage module to v3.2 (enable public read for CDN migration)",
            "file_changed": "modules/storage/main.tf",
            "diff_summary": "allow_blob_public_access = false -> true",
            "merged_minutes_before_incident": 8,
        }

    elif scenario == "ml_exfiltration":
        return {
            "repo": "org/ml-platform",
            "resource": resource,
            "commit_sha": "e7f9a2b5",
            "author": actor["id"],
            "message": "update ML gateway config: remove rate limits for batch processing",
            "file_changed": "services/ml-gateway/config.yaml",
            "diff_summary": "rate_limit: enabled -> disabled; max_tokens_per_hour: 10000 -> unlimited",
            "merged_minutes_before_incident": 12,
        }

    elif scenario == "access_control":
        return {
            "repo": "org/iam-policies",
            "resource": resource,
            "commit_sha": "c4d8f1a9",
            "author": actor["id"],
            "message": "grant Key Vault access to backup service for automated secret rotation",
            "file_changed": "policies/keyvault-access.tf",
            "diff_summary": f"added secrets.get and secrets.list permissions for {actor['id']}",
            "merged_minutes_before_incident": 10,
        }

    elif scenario == "kubernetes":
        return {
            "repo": "org/k8s-manifests",
            "resource": resource,
            "commit_sha": "b9e3c7f2",
            "author": actor["id"],
            "message": "update ML training cluster: add persistent volume for large datasets",
            "file_changed": f"clusters/{resource}/storage.yaml",
            "diff_summary": "added 50GB PersistentVolume mount to training pods",
            "merged_minutes_before_incident": 6,
        }

    else:  # noise
        return {
            "repo": "org/dev-configs",
            "resource": resource,
            "commit_sha": "x9y2z4w1",
            "author": "ci-bot",
            "message": "auto-update dev sandbox configs",
            "file_changed": "dev/sandbox-configs.yaml",
            "diff_summary": "routine config refresh",
            "merged_minutes_before_incident": 2,
        }


def _iam_logs(context: dict) -> dict:
    scenario = _detect_scenario_type(context)
    resource = context.get("resource_name", "unknown-resource")
    details = context.get("details", {})
    actor = _get_primary_actor(context)

    if scenario == "storage_gdpr":
        return {
            "resource": resource,
            "caller": actor["id"],
            "api": "azure.storage.blob.setMetadata",
            "call_count_last_hour": 23,
            "baseline_call_count_last_hour": 5,
            "source_ip": actor["ip"],
            "event": "storage_access_spike",
            "acl_modifications": 1,
        }

    elif scenario == "ml_exfiltration":
        return {
            "resource": resource,
            "caller": actor["id"],
            "api": details.get("api", "azure.openai.completions"),
            "call_count_last_hour": details.get("call_count_last_hour", 47),
            "baseline_call_count_last_hour": details.get("baseline_call_count_last_hour", 2),
            "source_ip": actor["ip"],
            "event": "anomalous_api_volume",
            "avg_tokens_per_call": 8742,
        }

    elif scenario == "access_control":
        api_name = details.get("api", "azure.keyvault.secrets.list")
        return {
            "resource": resource,
            "caller": actor["id"],
            "api": api_name,
            "call_count_last_hour": details.get("call_count_last_hour", 12),
            "baseline_call_count_last_hour": details.get("baseline_call_count_last_hour", 1),
            "source_ip": actor["ip"],
            "event": "credential_enumeration",
            "unique_secrets_accessed": 31,
        }

    elif scenario == "kubernetes":
        return {
            "resource": resource,
            "caller": actor["id"],
            "api": "azure.storage.blob.download",
            "call_count_last_hour": 8,
            "baseline_call_count_last_hour": 1,
            "source_ip": actor["ip"],
            "event": "data_retrieval_after_upload",
            "total_bytes_downloaded": int(details.get("size_gb", 8.7) * 1024 * 1024 * 1024),
        }

    else:  # noise
        return {
            "resource": resource,
            "caller": actor["id"],
            "api": "azure.management.healthCheck",
            "call_count_last_hour": 1,
            "baseline_call_count_last_hour": 1,
            "source_ip": actor["ip"],
            "event": "routine_healthcheck",
            "blocked": True,
        }


_CONNECTORS: dict[str, Callable[[str], dict]] = {
    "azure_monitor": _azure_monitor,
    "kubernetes": _kubernetes,
    "github_commits": _github_commits,
    "iam_logs": _iam_logs,
}


def connector_order_for(signal_type: str, agentic: bool = False) -> list[str]:
    """Return connector order for a signal type.

    Args:
        signal_type: The incident signal type (e.g., "PublicStorageBucket")
        agentic: If True, return all connectors; if False, use predefined order

    Returns:
        List of connector names in priority order
    """
    if agentic:
        # Agentic mode: return all connectors, sorted by confidence (highest first)
        # This gives LLM the full toolbox; it decides which are relevant
        return ["azure_monitor", "kubernetes", "github_commits", "iam_logs"]

    # Hard-coded mode: return predefined order per signal type
    return CONNECTOR_ORDER.get(signal_type, DEFAULT_ORDER)


def fetch(connector_name: str, context: dict) -> dict:
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
        "data": handler(context),
    }
