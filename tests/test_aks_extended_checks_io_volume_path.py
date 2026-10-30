"""
Regression test for a real bug found via a live campaign report
(campaign-report-20260921-111254.txt): an IOChaos experiment was configured
with volume_path=/root against deployment "pvc-app" (whose real
PersistentVolumeClaim is actually mounted at /data). The "Volume Mount Path
Exists" pre-check only ran `test -e /root` inside the container — which
passed, because /root genuinely exists as part of the container's writable
overlay layer — even though it is NOT the mounted volume IOChaos needs to
hook. Azure Chaos Studio then destructively created the Chaos Mesh
IOChaos CR, which entered a "Failed" condition instead of injecting,
because chaosfs can only intercept I/O on a real mount.

The fix cross-checks volume_path against the pod's actual declared
volumeMounts (not just filesystem existence), catching this misconfiguration
before the destructive Chaos Studio phase, and reports the pod's real
mount path(s) so the operator can correct volume_path immediately.
"""

import json
from subprocess import CompletedProcess
from unittest.mock import patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_cluster_plane as cluster_plane,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    extended as aks_extended_checks,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended import (
    build_io_chaos_pre_checks,
)


def _pod_json(name):
    return {
        "items": [{
            "metadata": {"name": name},
            "status": {"phase": "Running"},
        }]
    }


def _deployment_json(replicas, ready=None, available=None):
    return {
        "spec": {"replicas": replicas},
        "status": {
            "readyReplicas": replicas if ready is None else ready,
            "availableReplicas": replicas if available is None else available,
        },
    }


def _pods_json(items):
    return {"items": items}


def test_volume_path_that_exists_but_is_not_a_real_mount_fails_with_guidance():
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        side_effect=[
            # _first_running_pod: list pods matching selector
            CompletedProcess([], 0, stdout=json.dumps(_pod_json("pvc-app-abc")), stderr=""),
            # _find_mounted_container: get pod spec (no matching mount for /root)
            CompletedProcess([], 0, stdout=json.dumps({"spec": {"containers": []}}), stderr=""),
            # test -e /root — genuinely exists (part of the base image)
            CompletedProcess([], 0, stdout="EXISTS\n", stderr=""),
            # actual declared volumeMounts on the pod — only /data is real
            CompletedProcess([], 0, stdout="/data\n", stderr=""),
        ],
    ):
        checks = build_io_chaos_pre_checks(
            "ctx", "app-ns", "pvc-app", "app", "pvc-app",
            experiment_id="aks-io-latency", volume_path="/root",
        )
        passed, detail = checks["Volume Mount Path Exists"]()

    assert passed is False
    assert "is NOT under any mounted volume" in detail
    assert "['/data']" in detail


def test_volume_path_that_matches_a_real_mount_passes():
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(_pod_json("pvc-app-abc")), stderr=""),
            # _find_mounted_container: get pod spec (matching container mounts /data)
            CompletedProcess([], 0, stdout=json.dumps({
                "spec": {"containers": [{"name": "app", "volumeMounts": [{"mountPath": "/data"}]}]}
            }), stderr=""),
            CompletedProcess([], 0, stdout="EXISTS\n", stderr=""),
            CompletedProcess([], 0, stdout="/data\n", stderr=""),
        ],
    ):
        checks = build_io_chaos_pre_checks(
            "ctx", "app-ns", "pvc-app", "app", "pvc-app",
            experiment_id="aks-io-latency", volume_path="/data",
        )
        passed, detail = checks["Volume Mount Path Exists"]()

    assert passed is True
    assert "under a mounted volume" in detail


def test_volume_path_check_stays_lenient_when_mounts_cannot_be_determined():
    """If the mountPath lookup itself fails/returns nothing, don't newly
    block runs that the old existence-only check would have allowed —
    stay conservative and only fail when we positively know the path isn't
    under a declared mount."""
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(_pod_json("pvc-app-abc")), stderr=""),
            # _find_mounted_container: get pod spec (no matching mount)
            CompletedProcess([], 0, stdout=json.dumps({"spec": {"containers": []}}), stderr=""),
            CompletedProcess([], 0, stdout="EXISTS\n", stderr=""),
            CompletedProcess([], 1, stdout="", stderr="RBAC denied"),
        ],
    ):
        checks = build_io_chaos_pre_checks(
            "ctx", "app-ns", "pvc-app", "app", "pvc-app",
            experiment_id="aks-io-latency", volume_path="/root",
        )
        passed, _ = checks["Volume Mount Path Exists"]()

    assert passed is True


def test_iochaos_crd_installed_passes_when_crd_exists():
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        return_value=CompletedProcess([], 0, stdout="iochaos.chaos-mesh.org\n", stderr=""),
    ):
        checks = build_io_chaos_pre_checks("ctx", "app-ns", "pvc-app")
        passed, detail = checks["IOChaos CRD Installed"]()

    assert passed is True
    assert "CRD 'iochaos.chaos-mesh.org' present" in detail


def test_iochaos_crd_installed_fails_when_crd_missing():
    with patch.object(
        aks_extended_checks,
        "_kubectl",
        return_value=CompletedProcess([], 1, stdout="", stderr="NotFound"),
    ):
        checks = build_io_chaos_pre_checks("ctx", "app-ns", "pvc-app")
        passed, detail = checks["IOChaos CRD Installed"]()

    assert passed is False
    assert "not installed" in detail


def test_no_existing_iochaos_auto_deletes_stale_resources():
    with patch("time.sleep", return_value=None), patch.object(
        aks_extended_checks,
        "_kubectl",
        side_effect=[
            CompletedProcess([], 0, stdout="old-iochaos  1m\n", stderr=""),
            CompletedProcess([], 0, stdout="", stderr=""),
            CompletedProcess([], 0, stdout="", stderr=""),
        ],
    ):
        checks = build_io_chaos_pre_checks("ctx", "app-ns", "pvc-app")
        passed, detail = checks["No Existing IOChaos"]()

    assert passed is True
    assert "Found stale iochaos resource(s): ['old-iochaos']" in detail
    assert "Auto-deleted" in detail


# ── _check_chaos_crd / _check_no_stale_chaos_crd ────────────────────────────

def test_check_chaos_crd_present():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="", stderr="")):
        passed, detail = aks_extended_checks._check_chaos_crd("ctx", "iochaos.chaos-mesh.org")
    assert passed is True
    assert "present" in detail


def test_check_chaos_crd_missing():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="not found")):
        passed, detail = aks_extended_checks._check_chaos_crd("ctx", "iochaos.chaos-mesh.org")
    assert passed is False
    assert "not installed" in detail


def test_check_no_stale_chaos_crd_clean():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="", stderr="")):
        passed, detail = aks_extended_checks._check_no_stale_chaos_crd("ctx", "iochaos")
    assert passed is True
    assert "No stale" in detail


def test_check_no_stale_chaos_crd_auto_deletes(monkeypatch):
    monkeypatch.setattr(aks_extended_checks.time, "sleep", lambda *_: None) if hasattr(aks_extended_checks, "time") else None
    calls = [
        CompletedProcess([], 0, stdout="stale1", stderr=""),   # initial get: stale found
        CompletedProcess([], 0, stdout="", stderr=""),          # delete --all
        CompletedProcess([], 0, stdout="", stderr=""),          # re-check: clean
    ]
    with patch.object(aks_extended_checks, "_kubectl", side_effect=calls), \
         patch("time.sleep", return_value=None):
        passed, detail = aks_extended_checks._check_no_stale_chaos_crd("ctx", "iochaos")
    assert passed is True
    assert "Auto-deleted" in detail


# ── _get_pods_json / _get_deployment_json / _first_running_pod ─────────────

def test_get_pods_json_success():
    pods = {"items": [{"metadata": {"name": "p1"}}]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        items, err = aks_extended_checks._get_pods_json("ctx", "ns", "app=x")
    assert err is None
    assert items == pods["items"]


def test_get_pods_json_kubectl_failure():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="boom")):
        items, err = aks_extended_checks._get_pods_json("ctx", "ns", "app=x")
    assert items is None
    assert "boom" in err


def test_get_deployment_json_success():
    dep = {"metadata": {"name": "dep-a"}}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(dep), stderr="")):
        result, err = aks_extended_checks._get_deployment_json("ctx", "ns", "dep-a")
    assert err is None
    assert result == dep


def test_first_running_pod_returns_first_match():
    pods = {"items": [
        {"status": {"phase": "Pending"}, "metadata": {"name": "p0"}},
        {"status": {"phase": "Running"}, "metadata": {"name": "p1"}},
    ]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        assert aks_extended_checks._first_running_pod("ctx", "ns", "app=x") == "p1"


def test_first_running_pod_returns_none_on_failure():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        assert aks_extended_checks._first_running_pod("ctx", "ns", "app=x") is None


# ── _get_workload_by_selector / _get_ready_node_count / _canary_pod ─────────

def test_get_workload_by_selector_returns_first_item():
    items = {"items": [{"metadata": {"name": "dep-a"}}]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(items), stderr="")):
        result, err = aks_extended_checks._get_workload_by_selector("ctx", "ns", "deployment", "app=x")
    assert err is None
    assert result == {"metadata": {"name": "dep-a"}}


def test_get_workload_by_selector_returns_none_when_empty():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        result, err = aks_extended_checks._get_workload_by_selector("ctx", "ns", "deployment", "app=x")
    assert result is None
    assert err is None


def test_get_ready_node_count_counts_ready_nodes():
    nodes = {"items": [
        {"status": {"conditions": [{"type": "Ready", "status": "True"}]}},
        {"status": {"conditions": [{"type": "Ready", "status": "False"}]}},
    ]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(nodes), stderr="")):
        ready, total, err = aks_extended_checks._get_ready_node_count("ctx")
    assert err is None
    assert ready == 1
    assert total == 2


def test_get_ready_node_count_returns_error_on_failure():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="down")):
        ready, total, err = aks_extended_checks._get_ready_node_count("ctx")
    assert ready is None
    assert "down" in err


def test_canary_pod_finds_ready_pod_outside_excluded_namespaces():
    pods = {"items": [
        {
            "metadata": {"name": "kube-dns-abc", "namespace": "kube-system"},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        },
        {
            "metadata": {"name": "app-pod", "namespace": "team-a"},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
        },
    ]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        name, ns = aks_extended_checks._canary_pod("ctx")
    assert name == "app-pod"
    assert ns == "team-a"


def test_canary_pod_returns_none_when_nothing_found():
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        name, ns = aks_extended_checks._canary_pod("ctx")
    assert name is None
    assert ns is None


# ── _parse_duration_to_secs / _parse_skew_offset_to_secs ────────────────────

def test_parse_duration_to_secs_various_units():
    assert aks_extended_checks._parse_duration_to_secs("5s") == 5.0
    assert aks_extended_checks._parse_duration_to_secs("100ms") == 0.1
    assert aks_extended_checks._parse_duration_to_secs("2m") == 120.0
    assert aks_extended_checks._parse_duration_to_secs("1h") == 3600.0


def test_parse_duration_to_secs_invalid_returns_zero():
    assert aks_extended_checks._parse_duration_to_secs("garbage") == 0.0
    assert aks_extended_checks._parse_duration_to_secs("") == 0.0


def test_parse_skew_offset_to_secs_strips_sign():
    assert aks_extended_checks._parse_skew_offset_to_secs("+1h") == 3600.0
    assert aks_extended_checks._parse_skew_offset_to_secs("-30m") == 1800.0
    assert aks_extended_checks._parse_skew_offset_to_secs("+300s") == 300.0


# ── build_time_chaos_pre_checks ──────────────────────────────────────────────

def test_time_chaos_offset_magnitude_passes_within_limit():
    checks = aks_extended_checks.build_time_chaos_pre_checks(
        "ctx", "ns", "dep", "app", "dep",
        experiment_id="aks-clock-skew-forward", time_offset="+1m",
    )
    passed, detail = checks["Clock Skew Offset Magnitude"]()
    assert passed is True
    assert "within safe limit" in detail


def test_time_chaos_offset_magnitude_blocks_over_limit():
    checks = aks_extended_checks.build_time_chaos_pre_checks(
        "ctx", "ns", "dep", "app", "dep",
        experiment_id="aks-clock-skew-forward", time_offset="+10m",
    )
    passed, detail = checks["Clock Skew Offset Magnitude"]()
    assert passed is False
    assert "exceeds safe limit" in detail


def test_time_chaos_timing_sensitive_detection_blocks_on_match():
    pods = {"items": [{
        "metadata": {"name": "vault-0", "labels": {}},
        "spec": {"containers": [{"name": "vault", "image": "vault:1.0"}]},
    }]}
    checks = aks_extended_checks.build_time_chaos_pre_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["Timing-Sensitive System Detection"]()
    assert passed is False
    assert "vault" in detail


def test_time_chaos_timing_sensitive_detection_passes_when_clean():
    pods = {"items": [{
        "metadata": {"name": "app-1", "labels": {}},
        "spec": {"containers": [{"name": "app", "image": "myapp:1.0"}]},
    }]}
    checks = aks_extended_checks.build_time_chaos_pre_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["Timing-Sensitive System Detection"]()
    assert passed is True


def test_time_chaos_no_pre_existing_crashloop_detects_crash():
    pods = {"items": [{
        "metadata": {"name": "app-1"},
        "status": {"containerStatuses": [
            {"name": "app", "state": {"waiting": {"reason": "CrashLoopBackOff"}}}
        ]},
    }]}
    checks = aks_extended_checks.build_time_chaos_pre_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["No Pre-Existing CrashLoop"]()
    assert passed is False
    assert "CrashLoopBackOff" in detail


def test_time_chaos_cert_manager_expiry_skips_when_no_certs():
    checks = aks_extended_checks.build_time_chaos_pre_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        passed, detail = checks["cert-manager Certificate Expiry Window"]()
    assert passed is True


def test_time_chaos_node_time_sync_warns_when_no_ntp_daemon():
    checks = aks_extended_checks.build_time_chaos_pre_checks("ctx", "ns", "dep", "app", "dep")
    responses = [
        CompletedProcess([], 0, stdout='{"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}', stderr=""),
        CompletedProcess([], 0, stdout="node-a", stderr=""),
        CompletedProcess([], 0, stdout='{"items": []}', stderr=""),
    ]
    with patch.object(aks_extended_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["Node Time Sync (NTP/Chrony)"]()
    assert passed is True
    assert "No NTP/chrony DaemonSet detected" in detail


def test_time_chaos_crd_installed_check_present_in_dict():
    checks = aks_extended_checks.build_time_chaos_pre_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="", stderr="")):
        passed, _ = checks["TimeChaos CRD Installed"]()
    assert passed is True


# ── build_time_chaos_post_checks ─────────────────────────────────────────────

def test_time_chaos_post_no_crashloop_detects_crash():
    pods = {"items": [{
        "metadata": {"name": "app-1"},
        "status": {"containerStatuses": [
            {"name": "app", "state": {"waiting": {"reason": "CrashLoopBackOff"}}}
        ]},
    }]}
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["No CrashLoop After Clock Skew"]()
    assert passed is False
    assert "CrashLoopBackOff" in detail


def test_time_chaos_post_replicas_restored_passes():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2, "availableReplicas": 2}}
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(dep), stderr="")):
        passed, detail = checks["Replicas Restored"]()
    assert passed is True


def test_time_chaos_post_replicas_not_restored_fails():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 1, "availableReplicas": 1}}
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(dep), stderr="")):
        passed, detail = checks["Replicas Restored"]()
    assert passed is False


def test_time_chaos_post_no_tls_events_passes_when_clean():
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        passed, detail = checks["No TLS/Auth Events Post-Skew"]()
    assert passed is True


def test_time_chaos_post_timechaos_crd_cleaned_up():
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="", stderr="")):
        passed, detail = checks["TimeChaos CRD Cleaned Up"]()
    assert passed is True


def test_time_chaos_post_timechaos_crd_still_present_fails():
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="tc1", stderr="")):
        passed, detail = checks["TimeChaos CRD Cleaned Up"]()
    assert passed is False


def test_time_chaos_post_pod_clock_reverted_skips_without_pod():
    checks = aks_extended_checks.build_time_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        passed, detail = checks["Pod Clock Reverted"]()
    assert passed is True


# ── build_dns_chaos_post_checks ──────────────────────────────────────────────

def test_dns_chaos_post_resolved_in_pod_success():
    checks = aks_extended_checks.build_dns_chaos_post_checks(
        "ctx", "ns", "dep", "app", "dep", dns_pattern="example.com",
    )
    responses = [
        CompletedProcess([], 0, stdout='{"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}', stderr=""),
        CompletedProcess([], 0, stdout="Address: 1.2.3.4", stderr=""),
    ]
    with patch.object(aks_extended_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["DNS Recovered in Pod (example.com)"]()
    assert passed is True


def test_dns_chaos_post_resolved_in_pod_skips_for_wildcard():
    checks = aks_extended_checks.build_dns_chaos_post_checks(
        "ctx", "ns", "dep", "app", "dep", dns_pattern="*.example.com",
    )
    passed, detail = checks["DNS Recovered in Pod (*.example.com)"]()
    assert passed is True
    assert "skipping" in detail


def test_dns_chaos_post_crd_cleaned_up():
    checks = aks_extended_checks.build_dns_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="", stderr="")):
        passed, _ = checks["DNSChaos CRD Cleaned Up"]()
    assert passed is True


def test_dns_chaos_post_crd_still_present_fails():
    checks = aks_extended_checks.build_dns_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="dc1", stderr="")):
        passed, _ = checks["DNSChaos CRD Cleaned Up"]()
    assert passed is False


def test_dns_chaos_post_no_dns_events_passes_when_clean():
    checks = aks_extended_checks.build_dns_chaos_post_checks("ctx", "ns", "dep", "app", "dep")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        passed, _ = checks["No DNS Error Events Post-Chaos"]()
    assert passed is True


# ── build_cluster_plane_chaos_pre_checks ─────────────────────────────────────

def _ready_pod(name):
    return {
        "metadata": {"name": name},
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
    }


def _build_pre_checks(*args, **kwargs):
    """
    build_cluster_plane_chaos_pre_checks() itself runs a real _kubectl() call
    (selector-fallback probe) before returning the checks dict, independent of
    whichever check function a test later exercises. Without stubbing _kubectl
    here too, that eager call falls through to the real `kubectl` subprocess —
    which isn't installed on CI runners — and raises FileNotFoundError before
    the test's own patch.object() context ever takes effect.
    """
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        return aks_extended_checks.build_cluster_plane_chaos_pre_checks(*args, **kwargs)


def test_cluster_plane_shared_infra_notice_always_passes():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    passed, detail = checks["CoreDNS Shared Cluster-Plane Notice"]()
    assert passed is True
    assert "SHARED cluster-plane" in detail


def test_cluster_plane_chaos_daemon_runtime_containerd_confirmed():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="[containerd, shim]", stderr="")):
        passed, detail = checks["Chaos Daemon Runtime (containerd)"]()
    assert passed is True


def test_cluster_plane_chaos_daemon_runtime_wrong_runtime_blocks():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout="[docker]", stderr="")):
        passed, detail = checks["Chaos Daemon Runtime (containerd)"]()
    assert passed is False


def test_cluster_plane_component_present_and_ready():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    pods = {"items": [_ready_pod("coredns-1"), _ready_pod("coredns-2")]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["CoreDNS Present & Ready"]()
    assert passed is True
    assert "2 instance" in detail


def test_cluster_plane_component_absent_blocks():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        passed, detail = checks["CoreDNS Present & Ready"]()
    assert passed is False


def test_cluster_plane_ha_floor_blocks_with_single_instance():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    pods = {"items": [_ready_pod("coredns-1")]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["CoreDNS HA Floor (>=2 Ready)"]()
    assert passed is False


def test_cluster_plane_ha_floor_passes_with_multiple_instances():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    pods = {"items": [_ready_pod("coredns-1"), _ready_pod("coredns-2"), _ready_pod("coredns-3")]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["CoreDNS HA Floor (>=2 Ready)"]()
    assert passed is True


def test_cluster_plane_kube_proxy_selector_fallback():
    checks = _build_pre_checks("ctx", "aks-kube-proxy-kill")
    assert "kube-proxy Present & Ready" in checks


def test_cluster_plane_blast_radius_mode_blocks_all():
    checks = _build_pre_checks(
        "ctx", "aks-coredns-kill", mode="all",
    )
    passed, detail = checks["Blast-Radius Mode Check"]()
    assert passed is False


def test_cluster_plane_blast_radius_mode_passes_for_one():
    checks = _build_pre_checks(
        "ctx", "aks-coredns-kill", mode="one",
    )
    passed, detail = checks["Blast-Radius Mode Check"]()
    assert passed is True


def test_cluster_plane_node_topology_note_warns_on_single_node():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": [{"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}', stderr="")):
        passed, detail = checks["Node Topology Note (test vs non-prod)"]()
    assert passed is True
    assert "Single-node" in detail


def test_cluster_plane_no_existing_chaos_crd_passes_when_clean():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        passed, detail = checks["No Existing Chaos CRD For Target"]()
    assert passed is True


def test_cluster_plane_canary_baseline_warns_when_no_canary_found():
    checks = _build_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        passed, detail = checks["Cluster-Wide Canary Baseline"]()
    assert passed is True


def test_cluster_plane_coredns_cpu_limits_check_only_for_cpu_experiment():
    checks_cpu = _build_pre_checks("ctx", "aks-coredns-cpu")
    assert "CoreDNS CPU Limits Set (Advisory)" in checks_cpu
    checks_kill = _build_pre_checks("ctx", "aks-coredns-kill")
    assert "CoreDNS CPU Limits Set (Advisory)" not in checks_kill


def test_cluster_plane_coredns_stress_blocks_when_daemon_is_missing_from_target_node():
    checks = _build_pre_checks("ctx", "aks-coredns-cpu")
    responses = [
        CompletedProcess([], 0, stdout="system-node", stderr=""),
        CompletedProcess([], 0, stdout="other-node=Running\n", stderr=""),
    ]
    with patch.object(aks_extended_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["Chaos Daemon Present On Target Node(s)"]()

    assert passed is False
    assert "NOT present/Running" in detail


def test_cluster_plane_coredns_stress_skips_daemon_comparison_without_target_nodes():
    checks = _build_pre_checks("ctx", "aks-coredns-cpu")
    with patch.object(
        aks_extended_checks, "_kubectl", return_value=CompletedProcess([], 1, stdout="", stderr="denied")
    ):
        passed, detail = checks["Chaos Daemon Present On Target Node(s)"]()

    assert passed is True
    assert "could not resolve target node(s)" in detail


# ── build_cluster_plane_chaos_post_checks ────────────────────────────────────

def test_cluster_plane_post_component_restored_passes():
    checks = aks_extended_checks.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    dep = {"items": [{"status": {"replicas": 2, "readyReplicas": 2}}]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(dep), stderr="")):
        passed, detail = checks["CoreDNS Restored to Desired Ready Count"]()
    assert passed is True


def test_cluster_plane_post_component_not_restored_fails():
    checks = aks_extended_checks.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    dep = {"items": [{"status": {"replicas": 2, "readyReplicas": 1}}]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(dep), stderr="")):
        passed, detail = checks["CoreDNS Restored to Desired Ready Count"]()
    assert passed is False


def test_cluster_plane_post_no_crashloop_passes_when_clean():
    checks = aks_extended_checks.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    pods = {"items": [_ready_pod("coredns-1")]}
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout=json.dumps(pods), stderr="")):
        passed, detail = checks["No CoreDNS CrashLoopBackOff"]()
    assert passed is True


def test_cluster_plane_post_crd_cleaned_up():
    checks = aks_extended_checks.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        passed, detail = checks["CoreDNS Chaos CRD Cleaned Up"]()
    assert passed is True


def test_cluster_plane_post_no_warning_events_passes_when_clean():
    checks = aks_extended_checks.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 0, stdout='{"items": []}', stderr="")):
        passed, detail = checks["No CoreDNS Warning Events Post-Chaos"]()
    assert passed is True


def test_cluster_plane_post_canary_recovery_warns_without_canary():
    checks = aks_extended_checks.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    with patch.object(aks_extended_checks, "_kubectl",
                       return_value=CompletedProcess([], 1, stdout="", stderr="")):
        passed, detail = checks["Cluster-Wide Canary Recovery"]()
    assert passed is True


def test_cluster_plane_post_canary_recovery_accepts_missing_probe_tools():
    checks = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    with patch.object(cluster_plane, "_canary_pod", return_value=("witness", "app")), patch.object(
        cluster_plane, "_kubectl", return_value=CompletedProcess([], 0, stdout="__NOPROBE__", stderr="")
    ):
        passed, detail = checks["Cluster-Wide Canary Recovery"]()

    assert passed is True
    assert "tooling gap" in detail
