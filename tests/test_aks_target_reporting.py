import io
import json
import re
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from rich.console import Console

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as aks_safety_checks,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.safety import (
    _annotate_network_result,
    _select_live_probe_pod,
    build_post_experiment_checks,
    build_steady_state_checks,
    validate_and_resolve_selector,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor import (
    _build_spec,
    _capture_missing_net_baseline,
    _extract_chaos_target_pods,
    _print_net_impact_summary,
    _print_network_outcome,
    _probe_recovery_status,
    _target_selection_preview,
)


def test_restart_baseline_does_not_block_other_initial_network_metrics():
    baseline = {"restarts": 3}

    _capture_missing_net_baseline(
        baseline,
        {"restarts": 4, "rtt_ms": 12.5, "endpoints_ready": 2},
    )

    assert baseline == {
        "restarts": 3,
        "rtt_ms": 12.5,
        "endpoints_ready": 2,
    }


def test_live_probe_prefers_an_actual_chaos_target():
    pod_lines = [
        "api-control 1/1 Running 0 10m",
        "api-target 1/1 Running 0 10m",
    ]

    assert _select_live_probe_pod(pod_lines, ["api-target"]) == "api-target"
    assert _select_live_probe_pod(pod_lines, []) == "api-control"


def test_skipped_probe_check_has_unknown_recovery_status():
    assert _probe_recovery_status({
        "Probe Failures Stopped (post)": {
            "passed": True,
            "detail": "Could not query probe events — advisory skipped",
        }
    }) is None
    assert _probe_recovery_status({
        "Probe Failures Stopped (post)": {
            "passed": True,
            "detail": "No recent probe failures",
        }
    }) is True


def test_network_outcome_separates_injection_impact_and_recovery():
    captured = io.StringIO()
    test_console = Console(file=captured, width=240, no_color=True)
    with patch("chaosforge.interfaces.cli.interactive.ui.console.console", test_console):
        _print_network_outcome(
            True,
            {"endpoints_ready": 1, "restarts": 0},
            {"endpoints_ready": 0, "restarts": 2},
            ["Containers Ready", "Service Endpoints Restored"],
        )

    output = " ".join(captured.getvalue().split())
    assert "SUCCESS Fault injection" in output
    assert "OBSERVED Application impact" in output
    assert "FAILED Immediate recovery validation: Containers Ready, Service Endpoints Restored" in output
    assert "NOT ASSESSED Delayed/final recovery" in output
    assert "DEVIATED Overall resilience result" in output


def test_extracts_pods_from_all_supported_chaos_mesh_record_formats():
    crds = [
        {
            "status": {
                "experiment": {
                    "containerRecords": [
                        {"id": "app-ns/api-abc/app"},
                        {"id": "app-ns/api-def/sidecar"},
                    ]
                }
            }
        },
        {
            "status": {
                "experiment": {
                    "podRecords": {
                        "app-ns/api-ghi": {},
                        "app-ns/api-abc": {},
                    }
                }
            }
        },
        {
            "status": {
                "experiment": {
                    "records": [{"podName": "api-jkl"}]
                }
            }
        },
    ]

    assert _extract_chaos_target_pods(crds) == [
        "api-abc",
        "api-def",
        "api-ghi",
        "api-jkl",
    ]


def test_selection_preview_does_not_claim_random_candidates_are_targets():
    pods = ["api-a  (Running)", "api-b  (Running)", "api-c  (Running)"]

    assert _target_selection_preview(pods, "one", "") == (
        [],
        ["1 pod will be randomly selected by Chaos Mesh from 3 matching pod(s)"],
    )
    assert _target_selection_preview(pods, "fixed", "2") == (
        [],
        ["2 pod(s) will be randomly selected by Chaos Mesh from 3 matching pod(s)"],
    )
    assert _target_selection_preview(pods, "fixed-percent", "50") == (
        [],
        ["selector matched 3 pod(s); Chaos Mesh mode=fixed-percent, value=50"],
    )
    assert _target_selection_preview(pods, "all", "") == (pods, [])


def test_network_result_separates_actual_targets_controls_and_restart_delta():
    result = {
        "severity": "CHAOS",
        "message": (
            "pods: 3/3 Running | container restarts: 12 "
            "(liveness probe killing containers)"
        ),
        "net_rows": [
            ("Endpoints ready", "3 / 3", ""),
            ("Container restarts", "12", "liveness kills"),
        ],
    }
    pod_lines = [
        "api-a 1/1 Running 0 10m",
        "api-b 0/1 Running 0 10m",
        "api-c 1/1 Running 0 10m",
    ]

    annotated = _annotate_network_result(
        result, pod_lines, ["api-a", "api-b"], restart_baseline=12
    )

    assert ("Targeted pods ready", "1 / 2", "actual targets: api-a, api-b") in annotated["net_rows"]
    assert ("Control pods ready", "1 / 1", "matching pods not selected by Chaos Mesh") in annotated["net_rows"]
    assert ("Container restarts", "12", "baseline=12; new during fault=0") in annotated["net_rows"]
    assert "liveness probe killing containers" not in annotated["message"]
    assert "targeted ready: 1/2" in annotated["message"]
    assert "control ready: 1/1" in annotated["message"]


def test_pod_mode_spec_uses_exact_field_selector():
    spec, _, kind = _build_spec(
        "aks-packet-loss",
        {
            "namespace": "app-ns",
            "deployment": "api-abc",
            "label_key": "app",
            "label_val": "api",
            "target_mode": "pod",
            "exact_pod_name": "api-abc",
            "chaos_mode": "fixed",
            "chaos_value": "2",
            "duration": 60,
        },
    )

    assert kind == "NetworkChaos"
    assert spec["mode"] == "one"
    assert "value" not in spec
    assert "labelSelectors" not in spec["selector"]
    assert spec["selector"]["fieldSelectors"] == {"metadata.name": "api-abc"}


@pytest.mark.parametrize(
    ("experiment_id", "time_offset", "expected_kind"),
    [
        ("aks-clock-skew-forward", "+10m", "TimeChaos"),
        ("aks-clock-skew-backward", "-10m", "TimeChaos"),
    ],
)
def test_clock_skew_uses_runtime_offset_and_selected_application_selector(
    experiment_id, time_offset, expected_kind
):
    spec, _, kind = _build_spec(
        experiment_id,
        {
            "namespace": "app-ns",
            "deployment": "api-abc",
            "label_key": "app",
            "label_val": "api",
            "chaos_mode": "one",
            "duration": 60,
            "time_offset": time_offset,
        },
    )

    assert kind == expected_kind
    assert spec["timeOffset"] == time_offset
    assert spec["selector"]["namespaces"] == ["app-ns"]
    assert spec["selector"]["labelSelectors"] == {"app": "api"}


def test_clock_skew_rejects_invalid_runtime_offset():
    with pytest.raises(ValueError, match="Time offset"):
        _build_spec(
            "aks-clock-skew-forward",
            {
                "namespace": "app-ns",
                "deployment": "api-abc",
                "label_key": "app",
                "label_val": "api",
                "duration": 60,
                "time_offset": "10 minutes",
            },
        )


@pytest.mark.parametrize(
    ("experiment_id", "time_offset", "expected_offset"),
    [
        ("aks-clock-skew-forward", "5m", "+5m"),
        ("aks-clock-skew-backward", "5m", "-5m"),
    ],
)
def test_clock_skew_normalizes_unsigned_offsets(
    experiment_id, time_offset, expected_offset
):
    spec, _, _ = _build_spec(
        experiment_id,
        {
            "namespace": "app-ns",
            "deployment": "api-abc",
            "label_key": "app",
            "label_val": "api",
            "duration": 60,
            "time_offset": time_offset,
        },
    )

    assert spec["timeOffset"] == expected_offset


@pytest.mark.parametrize(
    ("experiment_id", "time_offset"),
    [
        ("aks-clock-skew-forward", "-5m"),
        ("aks-clock-skew-backward", "+5m"),
    ],
)
def test_clock_skew_rejects_wrong_direction_offset(experiment_id, time_offset):
    with pytest.raises(ValueError, match="must be"):
        _build_spec(
            experiment_id,
            {
                "namespace": "app-ns",
                "deployment": "api-abc",
                "label_key": "app",
                "label_val": "api",
                "duration": 60,
                "time_offset": time_offset,
            },
        )


def test_non_network_pod_kill_now_pins_to_exact_pod():
    """
    Regression test for a real blast-radius bug: previously, "By Pod" mode on
    Pod Kill (and Pod Failure / Container Kill) silently kept using the
    Deployment's label selector, which matches every sibling replica — not
    just the one pod the operator explicitly chose. Now it pins to the exact
    pod via fieldSelectors, exactly like Network Chaos already did.
    """
    spec, _, _ = _build_spec(
        "aks-pod-kill",
        {
            "namespace": "app-ns",
            "deployment": "api-abc",
            "label_key": "app",
            "label_val": "api",
            "target_mode": "pod",
            "exact_pod_name": "api-abc",
            "chaos_mode": "fixed",
            "chaos_value": "2",
            "duration": 60,
        },
    )

    assert spec["selector"]["fieldSelectors"] == {"metadata.name": "api-abc"}
    assert "labelSelectors" not in spec["selector"]
    assert spec["mode"] == "one"


def test_pod_kill_pod_mode_without_resolved_exact_pod_name_raises():
    """Pod mode must never silently fall back to a broad label selector if
    pre-checks failed to resolve an exact pod name for some reason."""
    with pytest.raises(ValueError, match="exact pod name"):
        _build_spec(
            "aks-pod-kill",
            {
                "namespace": "app-ns",
                "deployment": "api-abc",
                "label_key": "app",
                "label_val": "api",
                "target_mode": "pod",
                "chaos_mode": "fixed",
                "chaos_value": "2",
                "duration": 60,
            },
        )


def test_pod_mode_resolution_returns_non_overridable_exact_target():
    completed = CompletedProcess([], 0, stdout="api-abc", stderr="")

    with patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery"), patch.object(
        aks_safety_checks, "_kubectl", return_value=completed
    ):
        result = validate_and_resolve_selector(
            "ctx", "app-ns", "api-abc", "pod", "app", "api",
            exact_pod_targeting=True,
        )

    assert result["ok"] is True
    assert result["exact_pod_name"] == "api-abc"
    assert result["hard_block"] is False


def test_network_pdb_check_ignores_budget_that_does_not_select_target_pod():
    target_pod = {
        "items": [{
            "metadata": {
                "name": "gateway-helper",
                "labels": {
                    "app.kubernetes.io/instance": "gateway",
                    "app.kubernetes.io/role": "helper",
                },
            },
        }],
    }
    gateway_pdb = {
        "items": [{
            "metadata": {"name": "gateway-pdb"},
            "spec": {
                "selector": {
                    "matchLabels": {
                        "app.kubernetes.io/instance": "gateway",
                        "app.kubernetes.io/role": "gateway",
                    },
                },
            },
            "status": {"disruptionsAllowed": 0},
        }],
    }

    with patch.object(
        aks_safety_checks,
        "_kubectl",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(target_pod), stderr=""),
            CompletedProcess([], 0, stdout=json.dumps(gateway_pdb), stderr=""),
        ],
    ):
        checks = build_steady_state_checks(
            "ctx", "app-ns", "gateway-helper",
            "app.kubernetes.io/instance", "gateway", "aks-packet-loss",
            target_mode="pod", exact_pod_name="gateway-helper",
        )
        passed, detail = checks["PodDisruptionBudget"]()

    assert passed is True
    assert "No matching PDB found" in detail


def test_post_checks_query_only_the_exact_pod():
    pod = {
        "metadata": {"name": "api-abc"},
        "status": {"phase": "Running", "containerStatuses": [{"ready": True}]},
    }
    completed = CompletedProcess([], 0, stdout=json.dumps({"items": [pod]}), stderr="")

    with patch.object(aks_safety_checks, "_kubectl", return_value=completed) as kubectl:
        checks = build_post_experiment_checks(
            "aks-packet-loss",
            "ctx",
            "app-ns",
            "api-abc",
            "app",
            "api",
            target_mode="pod",
            exact_pod_name="api-abc",
        )
        passed, _ = checks["Containers Ready"]()

    assert passed is True
    assert "--field-selector" in kubectl.call_args.args
    assert "metadata.name=api-abc" in kubectl.call_args.args
    assert "-l" not in kubectl.call_args.args


def test_network_restart_post_checks_query_only_the_exact_pod():
    pod = {
        "metadata": {"name": "api-abc"},
        "status": {"containerStatuses": [{"restartCount": 0}]},
    }
    completed = CompletedProcess([], 0, stdout=json.dumps({"items": [pod]}), stderr="")

    for experiment_id in ("aks-packet-loss", "aks-bandwidth-limit"):
        with patch.object(
            aks_safety_checks, "_kubectl", return_value=completed
        ) as kubectl:
            checks = build_post_experiment_checks(
                experiment_id,
                "ctx",
                "app-ns",
                "api-abc",
                "app",
                "api",
                target_mode="pod",
                exact_pod_name="api-abc",
            )
            checks["Restart Count Delta (post)"]()

        assert "--field-selector" in kubectl.call_args.args
        assert "metadata.name=api-abc" in kubectl.call_args.args
        assert "-l" not in kubectl.call_args.args


def test_packet_loss_post_dns_resolves_actual_service_name():
    pod_result = CompletedProcess(
        [],
        0,
        stdout=json.dumps({
            "items": [{
                "metadata": {"name": "backend-api-abc"},
                "status": {"phase": "Running"},
            }]
        }),
        stderr="",
    )
    service_result = CompletedProcess(
        [],
        0,
        stdout=json.dumps({
            "items": [{
                "metadata": {"name": "backend-service"},
                "spec": {"selector": {"app": "backend-api"}},
            }]
        }),
        stderr="",
    )
    dns_result = CompletedProcess([], 0, stdout="Address: 10.0.0.1", stderr="")

    with patch.object(
        aks_safety_checks,
        "_kubectl",
        side_effect=[pod_result, service_result, dns_result],
    ) as kubectl:
        checks = build_post_experiment_checks(
            "aks-packet-loss",
            "ctx",
            "app-ns",
            "backend-api-abc",
            "app",
            "backend-api",
            target_mode="pod",
            exact_pod_name="backend-api-abc",
        )
        checks["DNS Resolution Restored (UDP)"]()

    assert "backend-service.app-ns.svc.cluster.local" in kubectl.call_args.args
    assert "backend-api.app-ns.svc.cluster.local" not in kubectl.call_args.args
    assert "backend-api-abc.app-ns.svc.cluster.local" not in kubectl.call_args.args


def test_packet_loss_precheck_resolves_actual_service_name():
    pod_result = CompletedProcess(
        [],
        0,
        stdout=json.dumps({
            "items": [{
                "metadata": {"name": "backend-api-abc"},
                "status": {"phase": "Running"},
            }]
        }),
        stderr="",
    )
    service_result = CompletedProcess(
        [],
        0,
        stdout=json.dumps({
            "items": [{
                "metadata": {"name": "backend-service"},
                "spec": {"selector": {"app": "backend-api"}},
            }]
        }),
        stderr="",
    )
    dns_result = CompletedProcess([], 0, stdout="Address: 10.0.0.1", stderr="")

    with patch.object(
        aks_safety_checks,
        "_kubectl",
        side_effect=[pod_result, service_result, dns_result],
    ) as kubectl:
        checks = build_steady_state_checks(
            "ctx",
            "app-ns",
            "backend-api-abc",
            "app",
            "backend-api",
            "aks-packet-loss",
            target_mode="pod",
            exact_pod_name="backend-api-abc",
        )
        checks["Baseline DNS Resolution (UDP)"]()

    assert "backend-service.app-ns.svc.cluster.local" in kubectl.call_args.args
    assert "backend-api.app-ns.svc.cluster.local" not in kubectl.call_args.args


def test_bandwidth_post_dns_resolves_actual_service_name():
    pod_result = CompletedProcess(
        [],
        0,
        stdout=json.dumps({
            "items": [{
                "metadata": {"name": "backend-api-abc"},
                "status": {"phase": "Running"},
            }]
        }),
        stderr="",
    )
    service_result = CompletedProcess(
        [],
        0,
        stdout=json.dumps({
            "items": [{
                "metadata": {"name": "backend-service"},
                "spec": {"selector": {"app": "backend-api"}},
            }]
        }),
        stderr="",
    )
    dns_result = CompletedProcess([], 0, stdout="Address: 10.0.0.1", stderr="")

    with patch.object(
        aks_safety_checks,
        "_kubectl",
        side_effect=[pod_result, service_result, dns_result],
    ) as kubectl:
        checks = build_post_experiment_checks(
            "aks-bandwidth-limit",
            "ctx",
            "app-ns",
            "backend-api-abc",
            "app",
            "backend-api",
            target_mode="pod",
            exact_pod_name="backend-api-abc",
        )
        checks["DNS Resolution Restored"]()

    assert "backend-service.app-ns.svc.cluster.local" in kubectl.call_args.args
    assert "backend-api-abc.app-ns.svc.cluster.local" not in kubectl.call_args.args


def test_network_kubectl_request_timeout_precedes_exec_separator():
    with patch(
        "chaosforge.providers.azure.components.aks.kubernetes.dispatch_kubectl",
        return_value=None,
    ), patch(
        "chaosforge.providers.azure.components.aks.kubernetes.subprocess.run"
    ) as safety_run:
        aks_safety_checks._kubectl(
            "exec", "api-abc", "-n", "app-ns", "--", "curl", "http://api",
            context="ctx",
        )
    command = safety_run.call_args.args[0]
    timeout_index = next(
        index for index, value in enumerate(command)
        if value.startswith("--request-timeout=")
    )
    assert timeout_index < command.index("--")
    assert command.index("--context") < command.index("--")


def test_summary_does_not_claim_probe_recovery_when_advisory_failed():
    captured = io.StringIO()
    test_console = Console(file=captured, width=240, no_color=True)
    with patch("chaosforge.interfaces.cli.interactive.ui.console.console", test_console):
        _print_net_impact_summary(
            "aks-packet-loss",
            {"restarts": 0},
            {"restarts": 0, "probe_failures": 2},
            60,
            True,
            ["api-abc"],
            probe_recovered=False,
        )

    output = re.sub(r"\x1b\[[0-9;]*m", "", captured.getvalue())
    normalized = " ".join(output.split())
    assert "Recent probe events remain (advisory)" in normalized
    assert "All probes healthy" not in normalized


def test_packet_corruption_baseline_ping_targets_a_real_pod_ip_not_clusterip():
    """
    Regression test for a real false-positive bug: the packet-corruption
    "Baseline Ping (0% loss pre-fault)" check pinged the kube-dns Service's
    ClusterIP. A ClusterIP is a virtual address realized purely via
    kube-proxy iptables/IPVS DNAT rules scoped to the ports the Service
    declares (UDP/TCP 53 for kube-dns) — there is no rule for ICMP echo, so
    pinging it always reports 100% packet loss on any healthy AKS cluster,
    regardless of real network health. This made the pre-check permanently
    fail with "Pre-fault packet loss already 100%" even on a perfectly
    healthy cluster.

    The fix reuses the same CoreDNS-pod-IP resolution already used by the
    network-partition check (_np_partition_ping_target), which answers ICMP
    normally.
    """
    target_pod = {
        "items": [{
            "metadata": {"name": "web-app-abc"},
            "status": {"phase": "Running"},
        }]
    }
    healthy_ping_output = (
        "PING 10.244.1.5 (10.244.1.5): 56 data bytes\n"
        "--- 10.244.1.5 ping statistics ---\n"
        "10 packets transmitted, 10 packets received, 0% packet loss\n"
        "round-trip min/avg/max = 0.05/0.08/0.12 ms\n"
    )

    with patch.object(
        aks_safety_checks,
        "_kubectl",
        side_effect=[
            CompletedProcess([], 0, stdout=json.dumps(target_pod), stderr=""),
            # CoreDNS pod IP lookup (real pod IP — answers ICMP)
            CompletedProcess([], 0, stdout="10.244.1.5", stderr=""),
            CompletedProcess([], 0, stdout=healthy_ping_output, stderr=""),
        ],
    ) as kubectl:
        checks = build_steady_state_checks(
            "ctx", "app-ns", "web-app", "app", "web-app", "aks-packet-corruption",
        )
        passed, detail = checks["Baseline Ping (0% loss pre-fault)"]()

    assert passed is True
    assert "baseline packet loss = 0%" in detail
    # The actual ping exec call must target the real pod IP, never the
    # ClusterIP-style fallback "10.0.0.10".
    ping_call_args = kubectl.call_args_list[-1].args
    assert "10.244.1.5" in ping_call_args
    assert "10.0.0.10" not in ping_call_args
    # The IP-resolution call itself must query the CoreDNS *pod* (which
    # answers ICMP), not the kube-dns *Service* ClusterIP (which never
    # answers ICMP). This is the actual behavioral difference between the
    # old buggy resolver and the fixed one — asserting only the final ping
    # target wouldn't catch a regression back to the ClusterIP lookup.
    dns_lookup_call_args = kubectl.call_args_list[1].args
    assert "pods" in dns_lookup_call_args
    assert "k8s-app=kube-dns" in dns_lookup_call_args
    assert "service" not in dns_lookup_call_args
