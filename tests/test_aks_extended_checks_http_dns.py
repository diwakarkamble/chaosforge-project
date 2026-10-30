import json
from subprocess import CompletedProcess
from unittest.mock import patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    extended as aks_extended_checks,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
    build_dns_chaos_pre_checks,
    build_http_chaos_pre_checks,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_http_tproxy_check_fails_when_sidecar_webhook_exists_but_namespace_label_is_missing():
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        side_effect=[
            _cp(stdout="inject-v1-pod"),
            _cp(stdout=""),
        ],
    ):
        checks = build_http_chaos_pre_checks(
            "ctx",
            "app-ns",
            "web",
            "app",
            "web",
            experiment_id="aks-http-delay",
        )
        passed, detail = checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()

    assert passed is False
    assert "Namespace label missing" in detail
    assert "chaos-mesh.org/inject=enabled" in detail


def test_http_liveness_probe_check_fails_when_injected_delay_exceeds_probe_tolerance():
    deployment = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "api",
                        "livenessProbe": {"timeoutSeconds": 1, "failureThreshold": 3},
                    }]
                }
            }
        }
    }
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        return_value=_cp(stdout=json.dumps(deployment)),
    ):
        checks = build_http_chaos_pre_checks(
            "ctx",
            "app-ns",
            "api",
            experiment_id="aks-http-delay",
            injected_delay="5s",
        )
        passed, detail = checks["Liveness Probe vs Injected Delay"]()

    assert passed is False
    assert "KUBELET WILL KILL POD DURING CHAOS" in detail
    assert "Liveness probe tolerance ≤ injected delay" in detail


def test_dns_pattern_valid_check_rejects_invalid_wildcard_placement():
    checks = build_dns_chaos_pre_checks(
        "ctx",
        "app-ns",
        "api",
        dns_pattern="*.example.com",
    )

    passed, detail = checks["DNS Pattern Valid (non-empty, non-placeholder)"]()

    assert passed is False
    assert "Invalid wildcard placement" in detail
    assert "*.example.com" in detail


def test_http_readiness_probe_check_fails_when_delay_exceeds_tolerance():
    deployment = {
        "spec": {"template": {"spec": {"containers": [{
            "name": "api", "readinessProbe": {"timeoutSeconds": 1, "failureThreshold": 3},
        }]}}}
    }
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(deployment))):
        checks = build_http_chaos_pre_checks(
            "ctx", "app-ns", "api", experiment_id="aks-http-delay", injected_delay="5s",
        )
        passed, detail = checks["Readiness Probe vs Injected Delay"]()
    assert passed is False


def test_http_readiness_probe_check_passes_when_within_tolerance():
    deployment = {
        "spec": {"template": {"spec": {"containers": [{
            "name": "api", "readinessProbe": {"timeoutSeconds": 5, "failureThreshold": 5},
        }]}}}
    }
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(deployment))):
        checks = build_http_chaos_pre_checks(
            "ctx", "app-ns", "api", experiment_id="aks-http-delay", injected_delay="5s",
        )
        passed, detail = checks["Readiness Probe vs Injected Delay"]()
    assert passed is True


def test_http_target_port_exists_check():
    pods = {"items": [{"spec": {"containers": [{"ports": [{"containerPort": 80}]}]}}]}
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        checks = build_http_chaos_pre_checks(
            "ctx", "app-ns", "api", "app", "api", experiment_id="aks-http-delay", http_port="80",
        )
        passed, detail = checks["HTTP Target Port (80) Exists"]()
    assert passed is True


def test_http_chaos_crd_installed():
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp()):
        checks = build_http_chaos_pre_checks("ctx", "app-ns", "api", experiment_id="aks-http-delay")
        passed, _ = checks["HTTPChaos CRD Installed"]()
    assert passed is True


# ── build_dns_chaos_pre_checks ───────────────────────────────────────────────

def test_dns_chaos_crd_installed():
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp()):
        checks = build_dns_chaos_pre_checks("ctx", "app-ns", "api", dns_pattern="example.com")
        passed, _ = checks["DNSChaos CRD Installed"]()
    assert passed is True


def test_dns_chaos_auth_domain_safety_blocks_sensitive_domain():
    checks = build_dns_chaos_pre_checks("ctx", "app-ns", "api", dns_pattern="sts.amazonaws.com")
    passed, detail = checks["Auth Domain Safety Check"]()
    assert passed is False


def test_dns_chaos_auth_domain_safety_passes_for_normal_domain():
    checks = build_dns_chaos_pre_checks("ctx", "app-ns", "api", dns_pattern="myapp.example.com")
    passed, detail = checks["Auth Domain Safety Check"]()
    assert passed is True


def test_dns_chaos_coredns_running_check():
    pods = {"items": [{
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}
    }]}
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        checks = build_dns_chaos_pre_checks("ctx", "app-ns", "api", dns_pattern="example.com")
        passed, detail = checks["CoreDNS Running"]()
    assert passed is True


def test_dns_chaos_wildcard_blast_radius_warns_for_broad_pattern():
    checks = build_dns_chaos_pre_checks("ctx", "app-ns", "api", dns_pattern="*.svc.cluster.local")
    passed, detail = checks["DNS Pattern Blast Radius"]()
    assert passed is True


# ── build_http_chaos_post_checks ─────────────────────────────────────────────

def test_http_post_replicas_restored_passes():
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
        build_http_chaos_post_checks,
    )
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2, "availableReplicas": 2}}
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        checks = build_http_chaos_post_checks("ctx", "ns", "dep")
        passed, _ = checks["Replicas Restored After HTTP Chaos"]()
    assert passed is True


def test_http_post_crd_cleaned_up():
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
        build_http_chaos_post_checks,
    )
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp()):
        checks = build_http_chaos_post_checks("ctx", "ns", "dep")
        passed, _ = checks["HTTPChaos CRD Cleaned Up"]()
    assert passed is True


def test_http_post_endpoints_restored_passes():
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
        build_http_chaos_post_checks,
    )
    ep = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}], "notReadyAddresses": []}]}
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(ep))):
        checks = build_http_chaos_post_checks("ctx", "ns", "dep")
        passed, _ = checks["Service Endpoints Restored"]()
    assert passed is True


def test_http_post_endpoints_partial_recovery_fails():
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
        build_http_chaos_post_checks,
    )
    ep = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}], "notReadyAddresses": []}]}
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout=json.dumps(ep))):
        checks = build_http_chaos_post_checks("ctx", "ns", "dep", pre_chaos_endpoint_count=3)
        passed, detail = checks["Service Endpoints Restored"]()
    assert passed is False
    assert "Partial recovery" in detail


def test_http_post_no_unhealthy_probe_events_passes_when_clean():
    from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
        build_http_chaos_post_checks,
    )
    with patch.object(aks_extended_checks, "_kubectl", return_value=_cp(stdout='{"items": []}')):
        checks = build_http_chaos_post_checks("ctx", "ns", "dep")
        passed, _ = checks["No Probe Failures Post-HTTP Chaos"]()
    assert passed is True
