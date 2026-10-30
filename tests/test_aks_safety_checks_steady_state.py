"""
Unit tests for the steady-state check factory/runner in
actions/aks_safety_checks.py: build_steady_state_checks and
run_parallel_steady_state. These two functions are the pre-flight backbone
called from setup_studio for every AKS experiment type.
"""

import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as aks_safety_checks,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _pod(name, phase="Running", ready=True, restart_count=0, node_name="node-a"):
    return {
        "metadata": {"name": name},
        "spec": {"nodeName": node_name, "containers": [{"name": "app"}]},
        "status": {
            "phase": phase,
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "containerStatuses": [{"name": "app", "restartCount": restart_count}],
        },
    }


# ── build_steady_state_checks: always-present checks ───────────────────────

def test_build_steady_state_checks_always_includes_nodes_and_system_pods():
    checks = aks_safety_checks.build_steady_state_checks("ctx")
    assert "Nodes Ready" in checks
    assert "System Pods (CoreDNS, kube-proxy)" in checks
    # No namespace/deployment given — no target-specific checks added.
    assert not any(k.startswith("Replica Floor") for k in checks)
    assert "PodDisruptionBudget" not in checks


def test_nodes_ready_check_fails_when_worker_node_not_ready():
    nodes = {"items": [{
        "metadata": {"name": "node-a"},
        "spec": {"taints": []},
        "status": {"conditions": [{"type": "Ready", "status": "False"}]},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(nodes))):
        checks = aks_safety_checks.build_steady_state_checks("ctx")
        passed, detail = checks["Nodes Ready"]()
    assert passed is False
    assert "NOT Ready" in detail


# ── build_steady_state_checks: namespace/deployment target checks ──────────

def test_replica_floor_check_added_when_namespace_and_deployment_given():
    checks = aks_safety_checks.build_steady_state_checks("ctx", namespace="ns", deployment="dep")
    assert "Replica Floor (dep)" in checks


def test_replica_floor_closure_fails_on_zero_ready_replicas():
    dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 0}}
    checks = aks_safety_checks.build_steady_state_checks("ctx", namespace="ns", deployment="dep")
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        passed, detail = checks["Replica Floor (dep)"]()
    assert passed is False
    assert "0 ready replicas" in detail


def test_pdb_check_added_only_with_label_key_and_val():
    with_labels = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep", label_key="app", label_val="x"
    )
    without_labels = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep"
    )
    assert "PodDisruptionBudget" in with_labels
    assert "PodDisruptionBudget" not in without_labels


def test_pdb_closure_blocks_when_zero_disruptions_allowed():
    pdbs = {"items": [{
        "metadata": {"name": "pdb-a"},
        "spec": {"selector": {"matchLabels": {"app": "x"}}},
        "status": {"disruptionsAllowed": 0, "currentHealthy": 1, "desiredHealthy": 2},
    }]}
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep", label_key="app", label_val="x"
    )
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pdbs))):
        passed, detail = checks["PodDisruptionBudget"]()
    assert passed is False
    assert "disruptionsAllowed=0" in detail


# ── build_steady_state_checks: pod-chaos experiment branch ──────────────────

def test_pod_chaos_experiment_adds_pod_count_and_restart_stability_checks():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-pod-kill",
    )
    assert "Pod Count (pre-fault)" in checks
    assert "Restart Stability" in checks
    # Only pod-kill/failure/container-kill/crashloop get restart-stability;
    # container-existence check only added when container_name is given too.
    assert not any(k.startswith("Container Exists") for k in checks)


def test_pod_count_closure_fails_when_no_running_ready_pods():
    # aks-pod-kill routes pod listing through _list_pods -> _PYTHON_CLIENT_EXPERIMENTS,
    # not directly through _kubectl, so patch _list_pods itself.
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-pod-kill",
    )
    pods = [_pod("p1", phase="Pending", ready=False)]
    with patch.object(aks_safety_checks, "_list_pods", return_value=(pods, None)):
        passed, detail = checks["Pod Count (pre-fault)"]()
    assert passed is False
    assert "No Running+Ready pods" in detail


def test_container_exists_check_added_for_container_kill_with_name():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x",
        experiment_id="aks-container-kill", container_name="sidecar",
    )
    assert "Container Exists (sidecar)" in checks


# ── build_steady_state_checks: stress-chaos experiment branch ───────────────

def test_cpu_stress_experiment_adds_cpu_specific_checks():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-cpu-stress",
    )
    assert "No OOMKilled Containers" in checks
    assert "CPU Requests & Limits" in checks
    assert "CPU Baseline (current usage)" in checks
    assert "CPU Headroom (node)" in checks
    assert "Memory Requests & Limits" not in checks


def test_memory_stress_experiment_adds_oom_history_check():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-memory-stress",
    )
    assert "OOM History" in checks


def test_oom_history_closure_fails_when_container_previously_oomkilled():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-memory-stress",
    )
    pods = {"items": [{
        "metadata": {"name": "p1"},
        "status": {"containerStatuses": [{
            "name": "app",
            "state": {},
            "lastState": {"terminated": {"reason": "OOMKilled", "finishedAt": "2026-09-01T00:00:00Z"}},
        }]},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pods))):
        passed, detail = checks["OOM History"]()
    assert passed is False
    assert "OOM history" in detail


# ── build_steady_state_checks: network-targeting exact-pod selection ───────

def test_network_delay_with_exact_pod_targeting_uses_field_selector():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-network-delay",
        target_mode="pod", exact_pod_name="pod-a",
    )
    pdb_pods = {"items": []}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(pdb_pods))) as mock_kubectl:
        checks["PodDisruptionBudget"]()
    field_selector_calls = [
        c for c in mock_kubectl.call_args_list
        if "--field-selector" in c.args
    ]
    assert field_selector_calls, "expected field-selector targeting for exact pod pinning"


# ── run_parallel_steady_state ───────────────────────────────────────────────

def test_run_parallel_steady_state_uses_provided_session():
    fake_session = MagicMock()
    fake_session.run_checks.return_value = {"Nodes Ready": {"passed": True, "detail": "ok"}}

    with patch.object(aks_safety_checks, "build_steady_state_checks", return_value={}):
        result = aks_safety_checks.run_parallel_steady_state(
            "ctx", namespace="ns", deployment="dep", session=fake_session,
        )

    assert result is True
    fake_session.run_checks.assert_called_once()


def test_run_parallel_steady_state_creates_temporary_session_when_none_given():
    fake_tmp = MagicMock()
    fake_tmp.run_checks.return_value = {"Nodes Ready": {"passed": True, "detail": "ok"}}

    with patch.object(aks_safety_checks, "build_steady_state_checks", return_value={}), \
         patch("chaosforge.providers.azure.components.aks.experiments.chaos_studio.validation_logger.ValidationSession", return_value=fake_tmp):
        result = aks_safety_checks.run_parallel_steady_state("ctx", namespace="ns", deployment="dep")

    assert result is True
    fake_tmp.start.assert_called_once()
    fake_tmp.stop.assert_called_once()


def test_run_parallel_steady_state_warns_but_does_not_raise_on_advisory_failure():
    fake_session = MagicMock()
    fake_session.run_checks.return_value = {
        "CPU Requests & Limits": {"passed": False, "detail": "no limit set"},
    }
    with patch.object(aks_safety_checks, "build_steady_state_checks", return_value={}):
        with pytest.warns(UserWarning, match="CPU Requests & Limits"):
            result = aks_safety_checks.run_parallel_steady_state(
                "ctx", namespace="ns", deployment="dep", session=fake_session,
            )
    assert result is True


def test_run_parallel_steady_state_raises_runtime_error_on_hard_failure():
    fake_session = MagicMock()
    fake_session.run_checks.return_value = {
        "Nodes Ready": {"passed": False, "detail": "node-a NOT Ready"},
    }
    with patch.object(aks_safety_checks, "build_steady_state_checks", return_value={}):
        with pytest.raises(RuntimeError, match="Nodes Ready"):
            aks_safety_checks.run_parallel_steady_state(
                "ctx", namespace="ns", deployment="dep", session=fake_session,
            )


# ── packet-loss / bandwidth-limit / packet-corruption / packet-duplication /
#    network-partition pre-checks — each branch defines its own closures for
#    "NetworkChaos CRD Installed" and "No Existing NetworkChaos", so each
#    experiment_id must be exercised separately to cover its own copy.

@pytest.mark.parametrize("experiment_id", [
    "aks-packet-loss", "aks-bandwidth-limit", "aks-packet-corruption",
    "aks-packet-duplication", "aks-network-partition",
])
def test_network_fault_crd_installed_fails_when_crd_and_resources_absent(experiment_id):
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id=experiment_id,
    )
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(returncode=1, stderr="not found")):
        passed, detail = checks["NetworkChaos CRD Installed"]()
    assert passed is False
    assert "not installed" in detail


@pytest.mark.parametrize("experiment_id", [
    "aks-packet-loss", "aks-bandwidth-limit", "aks-packet-corruption",
    "aks-packet-duplication", "aks-network-partition",
])
def test_network_fault_no_existing_networkchaos_auto_cleans_stale_resource(experiment_id):
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id=experiment_id,
    )
    stale = {"items": [{"metadata": {"name": "stale-nc"}, "status": {"conditions": []}}]}
    responses = [_cp(stdout=json.dumps(stale)), _cp()]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["No Existing NetworkChaos"]()
    assert passed is True
    assert "auto-deleted" in detail


@pytest.mark.parametrize("experiment_id", [
    "aks-packet-loss", "aks-bandwidth-limit", "aks-packet-corruption",
    "aks-packet-duplication", "aks-network-partition",
])
def test_network_fault_no_existing_networkchaos_blocks_when_actively_injecting(experiment_id):
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id=experiment_id,
    )
    live = {"items": [{
        "metadata": {"name": "live-nc"},
        "status": {"conditions": [{"type": "AllInjected", "status": "True"}]},
    }]}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(live))):
        passed, detail = checks["No Existing NetworkChaos"]()
    assert passed is False
    assert "actively injecting" in detail


def test_partition_replica_safety_fails_for_single_replica_deployment():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-network-partition",
    )
    dep = {"spec": {"replicas": 1}, "status": {"readyReplicas": 1}}
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=json.dumps(dep))):
        passed, detail = checks["Replica Count Safety (partition impact)"]()
    assert passed is False
    assert "complete service downtime" in detail


def test_partition_no_existing_iptables_chaos_blocks_on_stale_chain():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-network-partition",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    responses = [
        _cp(stdout=json.dumps(pods)),
        _cp(stdout="Chain CHAOS-XYZ (1 references)\n"),
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["No Existing iptables Chaos Rules"]()
    assert passed is False
    assert "stale partition" in detail


def test_packet_corruption_baseline_ping_fails_on_pre_existing_loss():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-packet-corruption",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    ping_output = "5 packets transmitted, 4 received, 20% packet loss\nrtt min/avg/max = 1/2/3 ms"

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "pods") and "-l" in args:
            return _cp(stdout=json.dumps(pods))
        if args[:2] == ("get", "pods"):
            return _cp(stdout="10.0.0.5")
        if args[:1] == ("exec",):
            return _cp(stdout=ping_output)
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router):
        passed, detail = checks["Baseline Ping (0% loss pre-fault)"]()
    assert passed is False
    assert "already 20%" in detail


def test_packet_duplication_baseline_ping_fails_when_dup_seen_pre_fault():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-packet-duplication",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    ping_output = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=0.1 ms (DUP!)"
    responses = [_cp(stdout=json.dumps(pods)), _cp(stdout=""), _cp(stdout=ping_output)]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["Baseline Ping (0 DUP! pre-fault)"]()
    assert passed is False
    assert "Duplicate ICMP replies" in detail


def test_bandwidth_no_existing_tc_rule_blocks_on_stale_tbf():
    checks = aks_safety_checks.build_steady_state_checks(
        "ctx", namespace="ns", deployment="dep",
        label_key="app", label_val="x", experiment_id="aks-bandwidth-limit",
    )
    pods = {"items": [{"metadata": {"name": "p1"}, "status": {"phase": "Running"}}]}
    responses = [_cp(stdout=json.dumps(pods)), _cp(stdout="qdisc tbf 8001: dev eth0 root rate 1mbit")]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        passed, detail = checks["No Existing tc Rule (tbf/netem)"]()
    assert passed is False
    assert "stale injection" in detail


# ── Delegated extended-check branches (TimeChaos/HTTPChaos/DNSChaos/IOChaos/
#    cluster-plane) — build_steady_state_checks merges in whatever the
#    corresponding aks_extended_checks builder returns; verify the delegation
#    happens for each experiment family.

def test_time_chaos_delegates_to_extended_checks_builder():
    fake_checks = {"Clock Skew Applied": lambda: (True, "ok")}
    with patch("chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended.build_time_chaos_pre_checks", return_value=fake_checks):
        checks = aks_safety_checks.build_steady_state_checks(
            "ctx", namespace="ns", deployment="dep",
            experiment_id="aks-clock-skew-forward",
        )
    assert "Clock Skew Applied" in checks


def test_http_chaos_delegates_to_extended_checks_builder():
    fake_checks = {"HTTP Delay Baseline": lambda: (True, "ok")}
    with patch("chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended.build_http_chaos_pre_checks", return_value=fake_checks):
        checks = aks_safety_checks.build_steady_state_checks(
            "ctx", namespace="ns", deployment="dep",
            experiment_id="aks-http-delay",
        )
    assert "HTTP Delay Baseline" in checks


def test_dns_chaos_delegates_to_extended_checks_builder():
    fake_checks = {"DNS Pattern Baseline": lambda: (True, "ok")}
    with patch("chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended.build_dns_chaos_pre_checks", return_value=fake_checks):
        checks = aks_safety_checks.build_steady_state_checks(
            "ctx", namespace="ns", deployment="dep",
            experiment_id="aks-dns-failure",
        )
    assert "DNS Pattern Baseline" in checks


def test_io_chaos_delegates_to_extended_checks_builder():
    fake_checks = {"IOChaos Sidecar Present": lambda: (True, "ok")}
    with patch("chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended.build_io_chaos_pre_checks", return_value=fake_checks):
        checks = aks_safety_checks.build_steady_state_checks(
            "ctx", namespace="ns", deployment="dep",
            experiment_id="aks-io-latency",
        )
    assert "IOChaos Sidecar Present" in checks


def test_cluster_plane_chaos_delegates_to_extended_checks_builder():
    fake_checks = {"CoreDNS Replica Count": lambda: (True, "ok")}
    with patch("chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended.build_cluster_plane_chaos_pre_checks", return_value=fake_checks):
        checks = aks_safety_checks.build_steady_state_checks("ctx", experiment_id="aks-coredns-kill")
    assert "CoreDNS Replica Count" in checks
