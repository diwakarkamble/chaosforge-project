"""
Unit tests for build_post_experiment_checks in actions/aks_safety_checks.py —
the post-rollback validation check factory. Covers the common checks (all
experiment types) plus network-delay and bandwidth-limit as representative
samples of the network-fault-specific branches, including the 150 KB/s
throughput threshold.
"""

import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_delay_loss_bandwidth as network_post_checks,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as aks_safety_checks,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _network_post_check_factory(experiment_id, responder, service=("svc-a", True)):
    """Build checks with callable suppliers to preserve the facade's late binding."""
    return network_post_checks.build_post_network_checks(
        experiment_id, "ctx", "ns", "dep", "app", "x", ("-l", "app=x"),
        "-l app=x", kubectl=lambda: responder, find_svc_name=lambda: lambda *args: service,
    )


def _network_healthy_responder(*args, **kwargs):
    if args[:2] == ("get", "pods"):
        return _cp(json.dumps({"items": [{
            "metadata": {"name": "pod-a"},
            "status": {"phase": "Running", "containerStatuses": [{"restartCount": 0}]},
        }]}))
    if args[:2] == ("get", "networkchaos"):
        return _cp()
    if args[:2] == ("get", "endpoints"):
        return _cp(json.dumps({"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]}))
    if args[:2] == ("get", "events"):
        return _cp(json.dumps({"items": []}))
    if args[:2] == ("get", "service"):
        return _cp("10.0.0.10")
    if args[:1] == ("exec",):
        if "tc" in args:
            return _cp("qdisc fq_codel 0: root")
        if "cat" in args:
            return _cp("Tcp: RtoAlgorithm RetransSegs\nTcp: 1 7")
        if "ping" in args:
            return _cp("rtt min/avg/max/mdev = 1.0/2.0/3.0/4.0 ms")
        if "nslookup" in args:
            return _cp("Name: svc-a\nAddress: 10.0.0.1")
        if any("%{size_download}" in arg for arg in args):
            return _cp("1000000 0.5 500000")
        if any("%{http_code}" in arg for arg in args):
            return _cp("200 0.1")
        return _cp("0.1")
    return _cp()


def test_post_checks_skip_workload_validation_without_target_selector():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-node-drain", "ctx", "", "", "", ""
    )

    assert checks


# ── common checks (present for every experiment type) ───────────────────────

def test_pod_recovery_fails_when_some_pods_not_running():
    # aks-container-kill routes pod listing through kubectl (not the Python
    # k8s client used by aks-pod-kill/aks-pod-failure), so _kubectl mocking applies.
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-container-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [
        {"metadata": {"name": "p1"}, "status": {"phase": "Running"}},
        {"metadata": {"name": "p2"}, "status": {"phase": "Pending"}},
    ]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        passed, detail = checks["Pod Recovery"]()
    assert passed is False
    assert "p2" in detail


def test_exact_pod_kill_recovers_via_ready_replacement_pod():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-pod-kill",
        "ctx",
        "ns",
        "deployment",
        label_key="app",
        label_val="api",
        target_mode="pod",
        exact_pod_name="api-old",
    )
    replacement = {
        "metadata": {"name": "api-new"},
        "status": {"phase": "Running"},
    }
    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.get_pods",
        return_value=([replacement], None),
    ):
        passed, detail = checks["Pod Recovery"]()

    assert passed is True
    assert "api-new" in detail


def test_exact_pod_kill_retries_replacement_recovery_until_ready():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-pod-kill",
        "ctx",
        "ns",
        "deployment",
        label_key="app",
        label_val="api",
        target_mode="pod",
        exact_pod_name="api-old",
        recovery_retry_count=5,
        recovery_retry_interval_seconds=50,
    )
    unavailable = [{"metadata": {"name": "api-new"}, "status": {"phase": "Pending"}}]
    ready = [{"metadata": {"name": "api-new"}, "status": {"phase": "Running"}}]
    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.get_pods",
        side_effect=[(unavailable, None), (ready, None)],
    ) as get_pods, patch.object(aks_safety_checks.time, "sleep") as sleep:
        passed, detail = checks["Pod Recovery"]()

    assert passed is True
    assert "attempt 2" in detail
    sleep.assert_called_once_with(50)
    assert get_pods.call_count == 2


def test_replica_count_restored_fails_when_ready_below_desired():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-container-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    dep = {"spec": {"replicas": 3}, "status": {"readyReplicas": 2, "availableReplicas": 2}}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        passed, detail = checks["Replica Count Restored"]()
    assert passed is False
    assert "Not fully restored" in detail


def test_no_crashloop_fails_when_container_crashlooping():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-container-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{
        "metadata": {"name": "p1"},
        "status": {"containerStatuses": [{"name": "app", "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        passed, detail = checks["No CrashLoop"]()
    assert passed is False
    assert "p1/app" in detail


def test_pod_events_check_present_for_non_network_experiments_only():
    pod_checks = aks_safety_checks.build_post_experiment_checks(
        "aks-pod-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    network_checks = aks_safety_checks.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    assert "Pod Events (last 5m)" in pod_checks
    assert "Pod Events (last 5m)" not in network_checks


# ── network-delay branch ─────────────────────────────────────────────────────

def test_network_delay_crd_cleanup_auto_deletes_stale_resource():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    responses = [
        _cp(stdout="networkchaos-a\n"),  # get networkchaos --no-headers finds a stale one
        _cp(),                            # delete networkchaos --all
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses) as mock_kubectl:
        passed, detail = checks["NetworkChaos CRD Cleaned Up"]()
    assert passed is True
    assert "auto-deleted" in detail
    delete_calls = [c for c in mock_kubectl.call_args_list if c.args[:2] == ("delete", "networkchaos")]
    assert len(delete_calls) == 1


def test_network_delay_tc_netem_removed_fails_when_rule_still_present():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    responses = [
        _cp(stdout=json.dumps(pods)),                       # _first_running_pod_post
        _cp(stdout="qdisc netem 8001: dev eth0 root delay 500ms"),  # tc qdisc show
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["tc-netem Rule Removed"]()
    assert passed is False
    assert "still on eth0" in detail


def test_network_delay_endpoints_restored_fails_on_not_ready_addresses():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-network-delay", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    endpoints = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}], "notReadyAddresses": [{"ip": "10.0.0.2"}]}]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(endpoints))), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("svc-a", True)):
        passed, detail = checks["Service Endpoints Restored"]()
    assert passed is False
    assert "still NotReady" in detail


# ── bandwidth-limit branch (150 KB/s throughput threshold) ──────────────────

def test_bandwidth_throughput_restored_passes_above_threshold():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-bandwidth-limit", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    responses = [
        _cp(stdout=json.dumps(pods)),  # _bw_post_first_pod
        _cp(stdout="1000000 0.5 500000"),  # curl: size time speed_bps (~488 KB/s)
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("svc-a", True)):
        passed, detail = checks["Throughput Restored (KB/s)"]()
    assert passed is True
    assert "Throughput restored" in detail


def test_bandwidth_throughput_restored_fails_at_or_below_150kbs():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-bandwidth-limit", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    # 150 KB/s * 1024 = 153600 B/s exactly at the threshold — must fail (<=).
    responses = [
        _cp(stdout=json.dumps(pods)),
        _cp(stdout="1000000 6.5 153600"),
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("svc-a", True)):
        passed, detail = checks["Throughput Restored (KB/s)"]()
    assert passed is False
    assert "still low" in detail


def test_bandwidth_throughput_check_skips_when_no_service_found():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-bandwidth-limit", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        passed, detail = checks["Throughput Restored (KB/s)"]()
    assert passed is True
    assert "not applicable" in detail


# ── packet-loss branch ───────────────────────────────────────────────────────

def test_packet_loss_tc_netem_removed_fails_when_loss_rule_still_present():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-packet-loss", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    responses = [
        _cp(stdout=json.dumps(pods)),
        _cp(stdout="qdisc netem 8001: dev eth0 root loss 25%"),
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["tc-netem Rule Removed"]()
    assert passed is False
    assert "not rolled back" in detail


def test_packet_loss_crd_cleanup_auto_deletes_stale_resource():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-packet-loss", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    responses = [_cp(stdout="networkchaos-a\n"), _cp()]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["NetworkChaos CRD Cleaned Up"]()
    assert passed is True
    assert "auto-deleted" in detail


@pytest.mark.parametrize(
    ("experiment_id", "expected_check_count"),
    [
        ("aks-network-delay", 9),
        ("aks-packet-loss", 10),
        ("aks-bandwidth-limit", 10),
    ],
)
def test_network_post_checks_all_happy_path_closures(experiment_id, expected_check_count):
    checks = _network_post_check_factory(experiment_id, _network_healthy_responder)

    assert len(checks) == expected_check_count
    assert all(check()[0] for check in checks.values())


@pytest.mark.parametrize(
    ("experiment_id", "check_name", "exec_output", "expected_detail"),
    [
        ("aks-network-delay", "HTTP Response Time Restored", "1.1", "still elevated"),
        ("aks-network-delay", "DNS Resolution Restored", "server failed", "still not resolving"),
        ("aks-packet-loss", "HTTP Success Restored", "503 0.1", "HTTP 503"),
        ("aks-packet-loss", "DNS Resolution Restored (UDP)", "server failed", "still failing"),
        ("aks-bandwidth-limit", "tc-tbf Rule Removed", "qdisc tbf 1: root", "still on eth0"),
        ("aks-bandwidth-limit", "HTTP Success Restored", "200 5.1", "still very slow"),
        ("aks-bandwidth-limit", "DNS Resolution Restored", "server failed", "not resolving"),
    ],
)
def test_network_post_checks_report_faults_after_rollback(
    experiment_id, check_name, exec_output, expected_detail,
):
    def responder(*args, **kwargs):
        if args[:1] == ("exec",):
            return _cp(exec_output)
        return _network_healthy_responder(*args, **kwargs)

    checks = _network_post_check_factory(experiment_id, responder)

    passed, detail = checks[check_name]()

    assert passed is False
    assert expected_detail in detail


@pytest.mark.parametrize(
    ("experiment_id", "check_name"),
    [
        ("aks-network-delay", "Service Endpoints Restored"),
        ("aks-packet-loss", "Service Endpoints Restored"),
        ("aks-bandwidth-limit", "Service Endpoints Restored"),
    ],
)
def test_network_post_endpoint_checks_fail_for_unready_endpoints(experiment_id, check_name):
    def responder(*args, **kwargs):
        if args[:2] == ("get", "endpoints"):
            return _cp(json.dumps({"subsets": [{"notReadyAddresses": [{"ip": "10.0.0.2"}]}]}))
        return _network_healthy_responder(*args, **kwargs)

    checks = _network_post_check_factory(experiment_id, responder)

    passed, detail = checks[check_name]()

    assert passed is False
    assert "still NotReady" in detail


@pytest.mark.parametrize("experiment_id", ["aks-network-delay", "aks-packet-loss", "aks-bandwidth-limit"])
def test_network_post_event_checks_fail_for_recent_network_warnings(experiment_id):
    warning = {
        "type": "Warning",
        "lastTimestamp": "2099-01-01T00:00:00Z",
        "reason": "NetworkNotReady",
        "message": "network timeout",
        "involvedObject": {"name": "pod-a"},
    }

    def responder(*args, **kwargs):
        if args[:2] == ("get", "events"):
            return _cp(json.dumps({"items": [warning]}))
        return _network_healthy_responder(*args, **kwargs)

    checks = _network_post_check_factory(experiment_id, responder)

    assert checks["Probe Failures Stopped (post)"]()[0] is False
    assert checks["No Network Warning Events (post)"]()[0] is False


# ── network-partition branch ─────────────────────────────────────────────────

def test_partition_iptables_removed_fails_when_chaos_chain_still_present():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-network-partition", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    responses = [
        _cp(stdout=json.dumps(pods)),
        _cp(stdout="Chain CHAOS-XYZ (1 references)\nDROP  all  --  0.0.0.0/0  0.0.0.0/0\n"),
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["iptables Chaos Rules Removed"]()
    assert passed is False
    assert "still partitioned" in detail


def test_partition_endpoints_restored_passes_when_pod_rejoins():
    checks = aks_safety_checks.build_post_experiment_checks(
        "aks-network-partition", "ctx", "ns", "dep", label_key="app", label_val="x",
    )
    endpoints = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}], "notReadyAddresses": []}]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(endpoints))), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("svc-a", True)):
        passed, detail = checks["Service Endpoints Restored"]()
    assert passed is True
