"""Direct coverage tests for the extracted AKS extended-check modules.

The compatibility facade has its own synchronization behavior; these tests call
the extracted modules directly and replace their existing kubectl/helper seams.
"""

import importlib
import json
import time
from contextlib import ExitStack
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
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_time as time_checks,
)


@pytest.fixture(autouse=True)
def _restore_extracted_module_seams():
    """Undo facade synchronization mutations left by facade-oriented tests."""
    importlib.reload(common)
    importlib.reload(time_checks)
    importlib.reload(http)
    importlib.reload(dns)
    importlib.reload(cluster_plane)
    importlib.reload(io)


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _json(value):
    return _result(json.dumps(value))


def _ready_pod(name="pod", namespace="app"):
    return {
        "metadata": {"name": name, "namespace": namespace},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
            "containerStatuses": [{"name": "app", "restartCount": 0}],
        },
        "spec": {"initContainers": [{"name": "chaosfs"}]},
    }


def _patch_kubectl(module, responder):
    stack = ExitStack()
    stack.enter_context(patch.object(common, "_kubectl", side_effect=responder))
    if module is not common:
        stack.enter_context(patch.object(module, "_kubectl", side_effect=responder))
    return stack


def test_common_helpers_cover_parse_errors_fallback_and_dns_measurement():
    calls = []

    def responder(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("get", "pods"):
            return _json({"items": [_ready_pod("runner")]})
        if args[:2] == ("get", "nodes"):
            return _json({"items": []})
        if args[:1] == ("exec",):
            return _result("Address: 10.0.0.1")
        return _result()

    with _patch_kubectl(common, responder):
        assert common._get_pods_json("ctx", "ns", "app=x")[0]
        assert common._get_deployment_json("ctx", "ns", "app")[0] is None
        assert common._first_running_pod("ctx", "ns", "app=x") == "runner"
        measured = common._measure_dns_latency("ctx", "ns", "app=x", "example.com", n=2)
        assert measured["success"] == 2
        assert common._get_workload_by_selector("ctx", "ns", "deployment", "app=x")[0] is None
        assert common._get_ready_node_count("ctx")[0] == 0
        assert common._canary_pod("ctx") == ("runner", "app")

    with patch("chaosforge.providers.azure.components.aks.kubernetes.subprocess.run", return_value=_result("via-fallback")) as run:
        assert common._kubectl("version", context="ctx").stdout == "via-fallback"
    assert run.call_args.args[0] == ["kubectl", "version", "--request-timeout=10s", "--context", "ctx"]
    assert common._parse_duration_to_secs("bad") == 0
    assert common._parse_skew_offset_to_secs("-100ms") == 0.1
    assert calls


def test_time_module_exercises_all_pre_and_post_checks():
    certs = {"items": []}
    deployment = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2, "availableReplicas": 2}}

    def responder(*args, **kwargs):
        if args[:2] == ("get", "deployment"):
            return _json(deployment)
        if args[:2] == ("get", "pods"):
            return _json({"items": [_ready_pod()]})
        if args[:2] == ("get", "certificates"):
            return _json(certs)
        if args[:2] == ("get", "daemonsets"):
            return _json({"items": [{"metadata": {"name": "chrony"}}]})
        if args[:2] == ("get", "pod"):
            return _result("node-a")
        if args[:2] == ("get", "events"):
            return _json({"items": []})
        if args[:2] == ("get", "timechaos"):
            return _result()
        if args[:1] == ("exec",):
            return _result(str(int(time.time())))
        return _result()

    with _patch_kubectl(time_checks, responder):
        pre = time_checks.build_time_chaos_pre_checks("ctx", "ns", "app", time_offset="1m")
        post = time_checks.build_time_chaos_post_checks("ctx", "ns", "app")
        assert all(check()[0] for check in pre.values())
        assert all(check()[0] for check in post.values())

    checks = time_checks.build_time_chaos_pre_checks("ctx", "ns", "app", time_offset="10m")
    assert checks["Clock Skew Offset Magnitude"]()[0] is False


def test_http_module_exercises_all_pre_and_post_checks():
    deployment = {
        "spec": {"replicas": 2, "template": {"spec": {"containers": [{
            "name": "api", "ports": [{"containerPort": 80}],
            "livenessProbe": {"timeoutSeconds": 5, "failureThreshold": 2},
            "readinessProbe": {"timeoutSeconds": 5, "failureThreshold": 2},
        }]}}},
        "status": {"readyReplicas": 2, "availableReplicas": 2},
    }

    def responder(*args, **kwargs):
        if args[:2] == ("get", "mutatingwebhookconfiguration"):
            return _result("inject-v1-pod")
        if args[:2] == ("get", "namespace"):
            return _result("enabled")
        if args[:2] == ("get", "pods"):
            return _json({"items": [_ready_pod()]})
        if args[:2] == ("get", "deployment"):
            return _json(deployment)
        if args[:2] == ("get", "endpoints"):
            return _json({"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]})
        if args[:2] == ("get", "events"):
            return _json({"items": []})
        return _result()

    with _patch_kubectl(http, responder):
        pre = http.build_http_chaos_pre_checks("ctx", "ns", "api", injected_delay="5s")
        post = http.build_http_chaos_post_checks("ctx", "ns", "api", pre_chaos_endpoint_count=1)
        assert all(check()[0] for check in pre.values())
        assert all(check()[0] for check in post.values())

    with _patch_kubectl(http, lambda *a, **k: _json(deployment)):
        checks = http.build_http_chaos_pre_checks("ctx", "ns", "api", injected_delay="20s")
        assert checks["Liveness Probe vs Injected Delay"]()[0] is False


def test_dns_module_exercises_pre_post_and_latency_regression():
    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            if "kube-system" in args:
                return _json({"items": [_ready_pod("coredns", "kube-system")]})
            return _json({"items": [_ready_pod()]})
        if args[:1] == ("exec",):
            command = args[-1]
            if command == "echo ok":
                return _result("ok")
            return _result("Address: 10.0.0.1")
        if args[:2] == ("get", "clusterissuers") or args[:2] == ("get", "issuers"):
            return _json({"items": []})
        if args[:2] == ("get", "events"):
            return _json({"items": []})
        return _result()

    with _patch_kubectl(dns, responder):
        pre = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="example.com")
        post = dns.build_dns_chaos_post_checks("ctx", "ns", "app", dns_pattern="example.com")
        assert all(check()[0] for check in pre.values())
        assert all(check()[0] for check in post.values())

    checks = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="localhost")
    assert checks["DNS Pattern Valid (non-empty, non-placeholder)"]()[0] is False


def test_cluster_plane_module_exercises_pre_and_post_checks():
    pods = {"items": [_ready_pod("coredns-1", "kube-system"), _ready_pod("coredns-2", "kube-system")]}

    def responder(*args, **kwargs):
        if args[:2] == ("get", "daemonset"):
            return _result("--runtime=containerd")
        if args[:2] == ("get", "pods"):
            if any(str(a).startswith("jsonpath=") and "nodeName" in str(a) for a in args):
                if "chaos-testing" in args:
                    return _result("node-a=Running")
                return _result("node-a")
            if "--all-namespaces" in args:
                return _json({"items": [_ready_pod("canary", "team") ]})
            if "--no-headers" in args:
                return _result("coredns-1")
            return _json(pods)
        if args[:2] == ("get", "pdb"):
            return _json({"items": []})
        if args[:2] == ("get", "nodes"):
            return _json({"items": [{"status": {"conditions": [{"type": "Ready", "status": "True"}]}}, {"status": {"conditions": [{"type": "Ready", "status": "True"}]}}]})
        if args[:2] in (("get", "podchaos"), ("get", "stresschaos")):
            return _json({"items": []})
        if args[:2] == ("get", "deployment"):
            return _json({"items": [{"spec": {"template": {"spec": {"containers": [{"name": "dns", "resources": {"limits": {"cpu": "1"}}}]}}}, "status": {"replicas": 2, "readyReplicas": 2}}]})
        if args[:2] == ("get", "events"):
            return _json({"items": []})
        if args[:1] == ("exec",):
            return _result("10.0.0.1")
        return _result()

    with _patch_kubectl(cluster_plane, responder):
        pre = cluster_plane.build_cluster_plane_chaos_pre_checks("ctx", "aks-coredns-cpu")
        post = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-cpu")
        assert all(check()[0] for check in pre.values())
        assert all(check()[0] for check in post.values())

    with _patch_kubectl(cluster_plane, responder):
        checks = cluster_plane.build_cluster_plane_chaos_pre_checks("ctx", "aks-coredns-kill", mode="all")
        assert checks["Blast-Radius Mode Check"]()[0] is False


def test_io_module_exercises_all_pre_and_post_checks():
    deployment = {"spec": {"replicas": 2}}

    def responder(*args, **kwargs):
        if args[:2] == ("get", "namespace"):
            return _result("enabled")
        if args[:2] == ("get", "pods"):
            return _json({"items": [_ready_pod()]})
        if args[:2] == ("get", "deployment"):
            return _json(deployment)
        if args[:2] == ("get", "pod"):
            return _result("/data")
        if args[:1] == ("exec",):
            return _result("EXISTS")
        return _result()

    with _patch_kubectl(io, responder):
        pre = io.build_io_chaos_pre_checks("ctx", "ns", "app", volume_path="/data")
        post = io.build_io_chaos_post_checks("ctx", "ns", "app", volume_path="/data")
        assert all(check()[0] for check in pre.values())
        assert all(check()[0] for check in post.values())

    with _patch_kubectl(io, responder):
        checks = io.build_io_chaos_pre_checks("ctx", "ns", "app", volume_path="/missing")
        # The command seam supplies a real missing result for this targeted guard.
        with patch.object(io, "_kubectl", side_effect=[_json({"items": [_ready_pod()]}), _result("MISSING")]):
            assert checks["Volume Mount Path Exists"]()[0] is False


def test_common_stale_finalizer_cleanup_and_parse_failures():
    responses = [
        _result("stuck"), _result(), _result("stuck"), _result("stuck"), _result("stuck"),
        _result("stuck"), _result("stuck"), _result(), _result(),
    ]
    with _patch_kubectl(common, lambda *a, **k: responses.pop(0)), patch("time.sleep"):
        passed, detail = common._check_no_stale_chaos_crd("ctx", "iochaos")
    assert passed is True
    assert "force-removed" in detail

    with _patch_kubectl(common, lambda *a, **k: _result("not-json")):
        assert common._get_pods_json("ctx", "ns", "app=x")[0] is None
        assert common._get_deployment_json("ctx", "ns", "app")[0] is None
        assert common._get_workload_by_selector("ctx", "ns", "deployment", "app=x")[0] is None
        assert common._get_ready_node_count("ctx")[0] is None


def test_time_certificate_tls_and_clock_failure_paths():
    checks = time_checks.build_time_chaos_pre_checks("ctx", "ns", "app", time_offset="5m")
    cert = {"items": [{"metadata": {"name": "soon"}, "status": {"notAfter": "2099-01-01T00:00:00Z"}}]}
    # A dynamically generated near-future timestamp covers the risk branch.
    cert["items"][0]["status"]["notAfter"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 30))
    with _patch_kubectl(time_checks, lambda *a, **k: _json(cert)):
        assert "Certificates approaching" in checks["cert-manager Certificate Expiry Window"]()[1]

    post = time_checks.build_time_chaos_post_checks("ctx", "ns", "app")
    events = {"items": [{"type": "Warning", "lastTimestamp": "2099-01-01T00:00:00Z", "reason": "TLS", "message": "certificate expired"}]}
    with _patch_kubectl(time_checks, lambda *a, **k: _json(events)):
        assert post["No TLS/Auth Events Post-Skew"]()[0] is False
    with _patch_kubectl(time_checks, lambda *a, **k: _json({"items": [_ready_pod()]})):
        assert post["Pod Clock Reverted"]()[0] is True


def test_http_nsexec_abort_and_post_failure_paths():
    dep = {"spec": {"template": {"spec": {"containers": [{"name": "api", "securityContext": {"allowPrivilegeEscalation": False}, "livenessProbe": {"httpGet": {"port": 80}}}]}}}}

    def nsexec(*args, **kwargs):
        if args[:2] == ("get", "mutatingwebhookconfiguration"):
            return _result("crd-mutation")
        return _json(dep)

    with _patch_kubectl(http, nsexec):
        checks = http.build_http_chaos_pre_checks("ctx", "ns", "api", experiment_id="aks-http-abort", http_port="80")
        assert checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()[0] is False
        assert checks["Liveness Probe vs Injected Delay"]()[0] is False

    post = http.build_http_chaos_post_checks("ctx", "ns", "api")
    with _patch_kubectl(http, lambda *a, **k: _json({"subsets": [{"notReadyAddresses": [{"ip": "10.0.0.1"}]}]})):
        assert post["Service Endpoints Restored"]()[0] is False
    warnings = {"items": [{"type": "Warning", "reason": "Unhealthy", "lastTimestamp": "2099-01-01T00:00:00Z", "message": "probe failed"}]}
    with _patch_kubectl(http, lambda *a, **k: _json(warnings)):
        assert post["No Probe Failures Post-HTTP Chaos"]()[0] is False


def test_dns_post_failure_paths_and_acme_advisory():
    checks = dns.build_dns_chaos_pre_checks("ctx", "ns", "app", dns_pattern="acme.example.com")
    issuers = {"items": [{"spec": {"acme": {"server": "https://acme.example.com/directory"}}}]}
    with _patch_kubectl(dns, lambda *a, **k: _json(issuers)):
        assert "matches the ACME issuer" in checks["cert-manager ACME Issuer Domain (Advisory)"]()[1]

    post = dns.build_dns_chaos_post_checks("ctx", "ns", "app", dns_pattern="example.com")
    with _patch_kubectl(dns, lambda *a, **k: _result("", 1, "down")):
        assert post["Pod Readiness Restored"]()[0] is False
    events = {"items": [{"type": "Warning", "lastTimestamp": "2099-01-01T00:00:00Z", "message": "dns lookup failed"}]}
    with _patch_kubectl(dns, lambda *a, **k: _json(events)):
        assert post["No DNS Error Events Post-Chaos"]()[0] is False


def test_cluster_plane_pdb_chaos_and_recovery_failure_paths():
    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _result("coredns")
        if args[:2] == ("get", "pdb"):
            return _json({"items": [{"metadata": {"name": "dns"}, "spec": {"selector": {"matchLabels": {"k8s-app": "kube-dns"}}}, "status": {"disruptionsAllowed": 0}}]})
        if args[:2] in (("get", "podchaos"), ("get", "stresschaos")):
            return _json({"items": [{"metadata": {"name": "old"}, "spec": {"selector": {"labelSelectors": {"k8s-app": "kube-dns"}}}}]})
        if args[:2] == ("get", "events"):
            return _json({"items": [{"type": "Warning", "lastTimestamp": "2099-01-01T00:00:00Z", "involvedObject": {"name": "coredns"}, "message": "bad"}]})
        return _result()

    with _patch_kubectl(cluster_plane, responder):
        checks = cluster_plane.build_cluster_plane_chaos_pre_checks("ctx", "aks-coredns-kill")
        assert checks["CoreDNS PodDisruptionBudget Safety"]()[0] is False
        assert checks["No Existing Chaos CRD For Target"]()[0] is False
        post = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
        assert post["No CoreDNS Warning Events Post-Chaos"]()[0] is False


def test_cluster_plane_canary_recovery_failure_and_node_warning():
    post = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    with _patch_kubectl(cluster_plane, lambda *a, **k: _json({"items": [_ready_pod("canary", "team")]})):
        # _canary_pod uses common's seam; this is the subsequent exec failure.
        with patch.object(cluster_plane, "_kubectl", return_value=_result("", 1, "down")):
            assert post["Cluster-Wide Canary Recovery"]()[0] is False
    with _patch_kubectl(cluster_plane, lambda *a, **k: _json({"items": [{"status": {"conditions": []}}]})):
        assert "not Ready" in post["Node Ready Count Consistent"]()[1]


def test_dns_latency_regression_and_resolution_error_paths():
    post = dns.build_dns_chaos_post_checks("ctx", "ns", "app", dns_pattern="example.com")
    with _patch_kubectl(dns, lambda *a, **k: _result("", 1, "not found")):
        assert post["DNS Recovered in Pod (example.com)"]()[0] is False


def test_http_and_io_remaining_safety_warnings():
    dep = {"spec": {"template": {"spec": {"containers": [{"name": "api", "ports": [{"containerPort": 81}]}]}}}}
    with _patch_kubectl(http, lambda *a, **k: _json(dep)):
        checks = http.build_http_chaos_pre_checks("ctx", "ns", "api", http_port="80")
        assert checks["HTTP Target Port (80) Exists"]()[0] is False

    with _patch_kubectl(io, lambda *a, **k: _result("", 1, "denied")):
        checks = io.build_io_chaos_pre_checks("ctx", "ns", "app")
        assert checks["Replica Count Safety (I/O impact)"]()[0] is True
    post = io.build_io_chaos_post_checks("ctx", "ns", "app")
    with _patch_kubectl(io, lambda *a, **k: _result("stuck")):
        assert post["IOChaos CRD Cleaned Up"]()[0] is False


def test_http_post_replica_and_crd_failure_paths():
    post = http.build_http_chaos_post_checks("ctx", "ns", "api")
    with _patch_kubectl(http, lambda *a, **k: _json({"spec": {"replicas": 2}, "status": {"readyReplicas": 1}})):
        assert post["Replicas Restored After HTTP Chaos"]()[0] is False
    with _patch_kubectl(http, lambda *a, **k: _result("http-fault")):
        assert post["HTTPChaos CRD Cleaned Up"]()[0] is False



def test_cluster_plane_component_restore_failure():
    post = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    workload = {"items": [{"status": {"replicas": 2, "readyReplicas": 1}}]}
    with _patch_kubectl(cluster_plane, lambda *a, **k: _json(workload)):
        assert post["CoreDNS Restored to Desired Ready Count"]()[0] is False
