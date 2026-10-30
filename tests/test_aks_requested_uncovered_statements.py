import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_cluster_plane as cluster_plane,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_common as common,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_dns as dns,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_http as http,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_io as io,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _json(value):
    return _result(json.dumps(value))


def _ready_pod(name="pod", *, sidecar=True, restarts=0):
    pod = {
        "metadata": {"name": name, "namespace": "app"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "app", "ready": True, "restartCount": restarts}],
        },
        "spec": {"containers": [{"name": "app"}]},
    }
    if sidecar:
        pod["spec"]["initContainers"] = [{"name": "chaosfs"}]
    return pod


def test_find_writable_probe_location_prefers_direct_writable_mount():
    pod = {"spec": {"containers": [{"name": "app", "volumeMounts": [
        {"name": "data", "mountPath": "/data", "readOnly": False},
    ]}]}}

    with patch.object(common, "_kubectl", return_value=_json(pod)) as kubectl:
        assert common._find_writable_probe_location("ctx", "ns", "pod", "/data/logs/") == (
            "app", "/data/logs",
        )

    kubectl.assert_called_once_with(
        "get", "pod", "pod", "-n", "ns", "-o", "json", context="ctx",
    )


def test_find_writable_probe_location_uses_writable_same_volume_sidecar_path():
    pod = {"spec": {"containers": [
        {"name": "log-shipper", "volumeMounts": [
            {"name": "logs", "mountPath": "/var/log/app", "readOnly": True},
        ]},
        {"name": "app", "volumeMounts": [
            {"name": "logs", "mountPath": "/work/logs/", "readOnly": False},
        ]},
    ]}}

    with patch.object(common, "_kubectl", return_value=_json(pod)):
        assert common._find_writable_probe_location("ctx", "ns", "pod", "/var/log/app") == (
            "app", "/work/logs",
        )


def test_find_writable_probe_location_falls_back_to_readonly_match():
    pod = {"spec": {"containers": [{"name": "log-shipper", "volumeMounts": [
        {"name": "logs", "mountPath": "/var/log/app", "readOnly": True},
    ]}]}}

    with patch.object(common, "_kubectl", return_value=_json(pod)):
        assert common._find_writable_probe_location("ctx", "ns", "pod", "/var/log/app/") == (
            "log-shipper", "/var/log/app",
        )


def test_find_writable_probe_location_returns_empty_when_no_mount_matches():
    pod = {"spec": {"containers": [{"name": "app", "volumeMounts": [
        {"name": "cache", "mountPath": "/cache", "readOnly": False},
    ]}]}}

    with patch.object(common, "_kubectl", return_value=_json(pod)):
        assert common._find_writable_probe_location("ctx", "ns", "pod", "/data") == ("", "")


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [("", "empty"), ("<domain>", "placeholder"), ("localhost", "Loopback")],
)
def test_dns_pattern_rejection_branches(pattern, expected):
    check = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern=pattern)[
        "DNS Pattern Valid (non-empty, non-placeholder)"
    ]
    assert check()[0] is False
    assert expected in check()[1]


def test_dns_precheck_query_parse_and_absence_branches():
    checks = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="example.com")

    with patch.object(dns, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        assert checks["CoreDNS Running"]()[0] is False
    with patch.object(dns, "_kubectl", return_value=_result("not-json")):
        assert checks["CoreDNS Running"]()[0] is False
    with patch.object(dns, "_kubectl", return_value=_json({"items": []})):
        assert checks["CoreDNS Running"]()[0] is False

    with patch.object(dns, "_first_running_pod", return_value=None):
        assert checks["Shell Present in Target Pod (DNSChaos Requirement)"]()[0] is True
        assert checks["DNS Pre-Resolution (example.com)"]()[0] is True
    with patch.object(dns, "_first_running_pod", return_value="pod"), patch.object(
        dns, "_kubectl", return_value=_result(returncode=1, stderr="executable file not found")
    ):
        assert checks["Shell Present in Target Pod (DNSChaos Requirement)"]()[0] is False
    with patch.object(dns, "_first_running_pod", return_value="pod"), patch.object(
        dns, "_kubectl", return_value=_result(returncode=1, stderr="transient")
    ):
        assert checks["Shell Present in Target Pod (DNSChaos Requirement)"]()[0] is True
        assert checks["DNS Pre-Resolution (example.com)"]()[0] is True


def test_dns_precheck_advisory_and_latency_edge_branches():
    empty = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="")
    assert empty["Auth Domain Safety Check"]()[0] is True
    assert empty["DNS Pattern Blast Radius"]()[0] is True

    wildcard = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="*")
    assert "ALL DNS" in wildcard["DNS Pattern Blast Radius"]()[1]
    assert wildcard["cert-manager ACME Issuer Domain (Advisory)"]()[0] is True

    checks = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="example.com")
    with patch.object(dns, "_kubectl", return_value=_result(returncode=1)):
        assert checks["cert-manager ACME Issuer Domain (Advisory)"]()[0] is True
    with patch.object(dns, "_kubectl", return_value=_result("bad-json")):
        assert checks["cert-manager ACME Issuer Domain (Advisory)"]()[0] is True


def test_dns_postcheck_error_and_recovery_edges():
    checks = dns.build_dns_chaos_post_checks("ctx", "ns", "app", dns_pattern="example.com")
    with patch.object(dns, "_first_running_pod", return_value="pod"), patch.object(
        dns, "_kubectl", return_value=_result("NXDOMAIN")
    ):
        assert checks["DNS Recovered in Pod (example.com)"]()[0] is False
    with patch.object(dns, "_first_running_pod", return_value="pod"), patch.object(
        dns, "_kubectl", return_value=_result(returncode=1, stderr="tool not found")
    ):
        assert checks["DNS Recovered in Pod (example.com)"]()[0] is True
    with patch.object(dns, "_kubectl", return_value=_result(returncode=1)):
        assert checks["DNSChaos CRD Cleaned Up"]()[0] is True
        assert checks["No DNS Error Events Post-Chaos"]()[0] is True
    with patch.object(dns, "_kubectl", return_value=_result("bad-json")):
        assert checks["No DNS Error Events Post-Chaos"]()[0] is True
    with patch.object(dns, "_get_pods_json", return_value=([_ready_pod("down")], None)):
        _ready_pod_result = _ready_pod("down")
        _ready_pod_result["status"]["conditions"] = []
    with patch.object(dns, "_get_pods_json", return_value=([_ready_pod_result], None)):
        assert checks["Pod Readiness Restored"]()[0] is False



def test_http_precheck_missing_and_malformed_resource_branches():
    checks = http.build_http_chaos_pre_checks("ctx", "ns", "app", http_port="invalid")
    assert checks["HTTP Target Port (invalid) Exists"]()[0] is True

    def sidecar_responder(*args, **kwargs):
        if args[1] == "mutatingwebhookconfiguration":
            return _result("inject-v1-pod")
        if args[1] == "namespace":
            return _result("enabled")
        return _result("bad-json")

    with patch.object(http, "_kubectl", side_effect=sidecar_responder):
        assert checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()[0] is True

    no_sidecar = _json({"items": [_ready_pod(sidecar=False)]})
    with patch.object(
        http, "_kubectl", side_effect=[_result("inject-v1-pod"), _result("enabled"), no_sidecar]
    ):
        assert checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()[0] is False

    with patch.object(http, "_kubectl", side_effect=[_result(), _result(returncode=1)]):
        assert checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()[0] is True
    with patch.object(http, "_kubectl", side_effect=[_result(), _result("bad-json")]):
        assert checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()[0] is True


def test_http_abort_and_postcheck_failure_branches():
    abort = http.build_http_chaos_pre_checks(
        "ctx", "ns", "app", experiment_id="aks-http-abort", http_port="80"
    )
    with patch.object(http, "_kubectl", return_value=_result()), patch.object(
        http, "_get_deployment_json", return_value=(None, "missing")
    ):
        assert abort["Liveness Probe vs Injected Delay"]()[0] is True

    dep = {"spec": {"template": {"spec": {"containers": [{"name": "app"}]}}}}
    with patch.object(http, "_kubectl", return_value=_result()), patch.object(
        http, "_get_deployment_json", return_value=(dep, None)
    ):
        assert abort["Liveness Probe vs Injected Delay"]()[0] is True
        assert abort["Readiness Probe vs Injected Delay"]()[0] is True

    post = http.build_http_chaos_post_checks("ctx", "ns", "app")
    with patch.object(http, "_get_deployment_json", return_value=(None, "missing")):
        assert post["Replicas Restored After HTTP Chaos"]()[0] is False
    with patch.object(http, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        assert post["HTTPChaos CRD Cleaned Up"]()[0] is True
        assert post["Service Endpoints Restored"]()[0] is False
        assert post["No Probe Failures Post-HTTP Chaos"]()[0] is True
    with patch.object(http, "_kubectl", return_value=_result("bad-json")):
        assert post["Service Endpoints Restored"]()[0] is False
        assert post["No Probe Failures Post-HTTP Chaos"]()[0] is True
    with patch.object(http, "_kubectl", return_value=_json({"subsets": []})):
        assert post["Service Endpoints Restored"]()[0] is False


def test_io_pre_and_post_unavailable_resource_branches():
    checks = io.build_io_chaos_pre_checks("ctx", "ns", "app")
    with patch.object(io, "_kubectl", return_value=_result("bad-json")):
        assert checks["Replica Count Safety (I/O impact)"]()[0] is True
    with patch.object(io, "_first_running_pod", return_value=None):
        assert checks["Volume Mount Path Exists"]()[0] is True
        assert checks["Baseline File I/O Timing"]()[0] is True
    with patch.object(io, "_first_running_pod", return_value="pod"), patch.object(
        io, "_kubectl", return_value=_result(returncode=1, stderr="exec denied")
    ):
        assert checks["Volume Mount Path Exists"]()[0] is True
        assert checks["Baseline File I/O Timing"]()[0] is True

    post = io.build_io_chaos_post_checks("ctx", "ns", "app")
    with patch.object(io, "_kubectl", return_value=_result(returncode=1)):
        assert post["IOChaos CRD Cleaned Up"]()[0] is True
    with patch.object(io, "_first_running_pod", return_value=None):
        assert post["Residual I/O Fault Check"]()[0] is True
    with patch.object(io, "_first_running_pod", return_value="pod"), patch.object(
        io, "_kubectl", return_value=_result(returncode=1, stderr="I/O error")
    ):
        assert post["Residual I/O Fault Check"]()[0] is False
    with patch.object(io, "_get_pods_json", return_value=(None, "denied")):
        assert post["Restart Count Delta (post)"]()[0] is True
    with patch.object(io, "_get_pods_json", return_value=([_ready_pod(restarts=2)], None)):
        assert "Total restarts" in post["Restart Count Delta (post)"]()[1]


def test_cluster_plane_precheck_failure_and_advisory_branches():
    with patch.object(cluster_plane, "_kubectl", return_value=_result()):
        checks = cluster_plane.build_cluster_plane_chaos_pre_checks(
            "ctx", "aks-coredns-kill", mode="unexpected"
        )
    with patch.object(cluster_plane, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        assert checks["Chaos Daemon Runtime (containerd)"]()[0] is True
        assert checks["CoreDNS PodDisruptionBudget Safety"]()[0] is True
    with patch.object(cluster_plane, "_get_pods_json", return_value=(None, "denied")):
        assert checks["CoreDNS Present & Ready"]()[0] is False
        assert checks["CoreDNS HA Floor (>=2 Ready)"]()[0] is False
    with patch.object(cluster_plane, "_get_pods_json", return_value=([_ready_pod()], None)):
        assert checks["CoreDNS HA Floor (>=2 Ready)"]()[0] is False
    with patch.object(cluster_plane, "_kubectl", return_value=_result("bad-json")):
        assert checks["CoreDNS PodDisruptionBudget Safety"]()[0] is True
        assert checks["No Existing Chaos CRD For Target"]()[0] is True
    assert checks["Blast-Radius Mode Check"]()[0] is True
    with patch.object(cluster_plane, "_get_ready_node_count", return_value=(None, 0, "denied")):
        assert checks["Node Topology Note (test vs non-prod)"]()[0] is True
    with patch.object(cluster_plane, "_canary_pod", return_value=("pod", "team")), patch.object(
        cluster_plane, "_kubectl", return_value=_result(returncode=1)
    ):
        assert checks["Cluster-Wide Canary Baseline"]()[0] is True


def test_cluster_plane_postcheck_failure_branches():
    checks = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-kube-proxy-kill")
    with patch.object(cluster_plane, "_get_workload_by_selector", return_value=(None, "missing")):
        assert checks["kube-proxy Restored to Desired Ready Count"]()[0] is False
    daemonset = {"status": {"desiredNumberScheduled": 2, "numberReady": 1}}
    with patch.object(cluster_plane, "_get_workload_by_selector", return_value=(daemonset, None)):
        assert checks["kube-proxy Restored to Desired Ready Count"]()[0] is False
    crash = _ready_pod()
    crash["status"]["containerStatuses"][0]["state"] = {
        "waiting": {"reason": "CrashLoopBackOff"}
    }
    with patch.object(cluster_plane, "_get_pods_json", return_value=([crash], None)):
        assert checks["No kube-proxy CrashLoopBackOff"]()[0] is False
    with patch.object(cluster_plane, "_kubectl", return_value=_result("bad-json")):
        assert checks["kube-proxy Chaos CRD Cleaned Up"]()[0] is True
        assert checks["No kube-proxy Warning Events Post-Chaos"]()[0] is True
    with patch.object(cluster_plane, "_canary_pod", return_value=("pod", "team")), patch.object(
        cluster_plane, "_kubectl", return_value=_result(returncode=1)
    ):
        assert checks["Cluster-Wide Canary Recovery"]()[0] is False
    with patch.object(cluster_plane, "_get_ready_node_count", return_value=(None, 0, "denied")):
        assert checks["Node Ready Count Consistent"]()[0] is True


def test_cluster_plane_remaining_component_pdb_and_cpu_branches():
    with patch.object(cluster_plane, "_kubectl", return_value=_result()):
        checks = cluster_plane.build_cluster_plane_chaos_pre_checks("ctx", "aks-coredns-cpu")

    unready = _ready_pod()
    unready["status"]["conditions"] = []
    with patch.object(cluster_plane, "_get_pods_json", return_value=([unready], None)):
        assert checks["CoreDNS Present & Ready"]()[0] is False

    pdbs = {"items": [
        {"spec": {"selector": {"matchLabels": {"app": "other"}}}, "status": {}},
        {
            "metadata": {"name": "dns"},
            "spec": {"selector": {"matchLabels": {"k8s-app": "kube-dns"}}},
            "status": {
                "disruptionsAllowed": 1, "currentHealthy": 2, "desiredHealthy": 1,
            },
        },
    ]}
    with patch.object(cluster_plane, "_kubectl", return_value=_json(pdbs)):
        assert checks["CoreDNS PodDisruptionBudget Safety"]()[0] is True
    with patch.object(
        cluster_plane, "_get_workload_by_selector", return_value=(None, "missing")
    ):
        assert checks["CoreDNS CPU Limits Set (Advisory)"]()[0] is True
    workload = {
        "spec": {"template": {"spec": {"containers": [{"name": "dns"}]}}}
    }
    with patch.object(
        cluster_plane, "_get_workload_by_selector", return_value=(workload, None)
    ):
        assert "without a CPU limit" in checks["CoreDNS CPU Limits Set (Advisory)"]()[1]


def test_cluster_plane_remaining_post_crd_and_event_branches():
    checks = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    with patch.object(cluster_plane, "_get_pods_json", return_value=(None, "denied")):
        assert checks["No CoreDNS CrashLoopBackOff"]()[0] is False

    lingering = {"items": [{
        "metadata": {"name": "fault"},
        "spec": {"selector": {"labelSelectors": {"k8s-app": "kube-dns"}}},
    }]}
    with patch.object(
        cluster_plane, "_kubectl", side_effect=[_result(returncode=1), _json(lingering)]
    ):
        assert checks["CoreDNS Chaos CRD Cleaned Up"]()[0] is False

    events = {"items": [
        {"type": "Normal", "involvedObject": {"name": "coredns"}},
        {"type": "Warning", "involvedObject": {"name": "other"}},
        {
            "type": "Warning", "lastTimestamp": "not-a-time",
            "involvedObject": {"name": "coredns-1"}, "reason": "Failed",
            "message": "still unhealthy",
        },
    ]}
    with patch.object(cluster_plane, "_kubectl", return_value=_json(events)):
        assert checks["No CoreDNS Warning Events Post-Chaos"]()[0] is False
    with patch.object(cluster_plane, "_kubectl", return_value=_result(returncode=1)):
        assert checks["No CoreDNS Warning Events Post-Chaos"]()[0] is True


def test_safety_service_lookup_fallback_and_uncovered_closure_errors():
    with patch.object(
        safety, "_kubectl", side_effect=[_result("bad-json"), _result(returncode=1)]
    ):
        assert safety._find_svc_name("ns", "app", "api", "fallback", "ctx") == (
            "fallback", False
        )

    checks = safety.build_steady_state_checks(
        "ctx", "ns", "app", "app", "api", "aks-container-kill", container_name="api"
    )
    with patch.object(safety, "_kubectl", return_value=_result(returncode=1, stderr="denied")):
        assert checks["Replica Floor (app)"]()[0] is False
        assert checks["Container Exists (api)"]()[0] is False


def test_safety_postcheck_malformed_and_exact_pod_error_branches():
    checks = safety.build_post_experiment_checks("aks-cpu-stress", "ctx", "ns", "app")
    with patch.object(safety, "_kubectl", return_value=_result("bad-json")):
        assert checks["Pod Recovery"]()[0] is False
        assert checks["Replica Count Restored"]()[0] is False
        assert checks["Pod Events (last 5m)"]()[0] is True

    exact = safety.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "app", "app", "api",
        target_mode="pod", exact_pod_name="api-0",
    )
    pod = _ready_pod("api-0")
    pod["status"]["podIP"] = "10.0.0.1"
    with patch.object(safety, "_find_svc_name", return_value=("api", True)), patch.object(
        safety, "_kubectl", side_effect=[_json({"items": [pod]}), _result("bad-json")]
    ):
        assert exact["Service Endpoints Restored"]()[0] is False
