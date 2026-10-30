"""Behavioral coverage for the final AKS safety-check fallback paths."""

import builtins
import datetime as dt
import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_cluster_plane as cluster_plane,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_common as common,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_http as http,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _extended_time as time_checks,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_basic as basic,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_fault_network as fault_network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_corruption_duplication_partition as complex_post,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_post_network_delay_loss_bandwidth as simple_post,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_corruption_duplication_partition as complex_pre,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_delay_loss_bandwidth as simple_pre,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import safety


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _json(value):
    return _cp(json.dumps(value))


def _block_extended_import(monkeypatch):
    original_import = builtins.__import__

    def unavailable(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "extended" and level == 1:
            raise ImportError("optional checks unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", unavailable)


@pytest.mark.parametrize(
    ("experiment_id", "post"),
    [
        ("aks-clock-skew-forward", False),
        ("aks-http-delay", False),
        ("aks-dns-failure", False),
        ("aks-io-latency", False),
        ("aks-coredns-kill", False),
        ("aks-clock-skew-forward", True),
        ("aks-http-delay", True),
        ("aks-dns-failure", True),
        ("aks-io-latency", True),
        ("aks-coredns-kill", True),
    ],
)
def test_optional_extended_checks_are_skipped_when_the_module_is_unavailable(
    monkeypatch, experiment_id, post
):
    _block_extended_import(monkeypatch)

    if post:
        checks = safety.build_post_experiment_checks(
            experiment_id, "ctx", "app", "api", "app", "api"
        )
    else:
        checks = safety.build_steady_state_checks(
            "ctx", "app", "api", "app", "api", experiment_id
        )

    assert isinstance(checks, dict)


def test_time_offset_spec_failures_preserve_the_requested_offset(monkeypatch):
    extended = (
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended"
    )
    builder = MagicMock(return_value={})
    with patch(f"{extended}.build_time_chaos_pre_checks", builder):
        monkeypatch.setattr(builtins, "open", MagicMock(side_effect=OSError("unreadable")))
        safety.build_steady_state_checks(
            "ctx", "app", "api", "app", "api", "aks-clock-skew-forward",
            time_offset="",
        )

    assert builder.call_args.kwargs["time_offset"] == ""


def test_dns_live_probe_tolerates_pattern_and_container_record_query_errors():
    session = MagicMock()

    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _cp("api-0 1/1 Running 0\n")
        if args[:2] == ("get", "dnschaos") and any("patterns" in arg for arg in args):
            raise RuntimeError("pattern API unavailable")
        if args[:2] == ("get", "dnschaos") and any("containerRecords" in arg for arg in args):
            raise RuntimeError("status API unavailable")
        if args[:2] == ("get", "dnschaos"):
            return _json({"items": [{"metadata": {"uid": "run-1"}}]})
        raise AssertionError(args)

    with patch.object(safety, "_kubectl", side_effect=responder):
        result = safety.verify_fault_active(
            "aks-dns-failure", "ctx", "app", "api", "app", "api", session=session
        )

    assert result["severity"] == "WARNING"
    session.log_event.assert_called_once_with("WARNING", result["message"])


def test_exact_pod_probe_events_ignore_old_events_but_keep_bad_timestamps():
    checks = safety.build_post_experiment_checks(
        "aks-network-delay", "ctx", "app", "api", "app", "api",
        target_mode="pod", exact_pod_name="api-0",
    )
    events = {
        "items": [
            {
                "involvedObject": {"name": "api-0"},
                "lastTimestamp": "2000-01-01T00:00:00Z",
                "message": "old failure",
            },
            {
                "involvedObject": {"name": "other"},
                "lastTimestamp": "not-a-time",
                "message": "wrong pod",
            },
            {
                "involvedObject": {"name": "api-0"},
                "lastTimestamp": "not-a-time",
                "message": "timestamp unavailable",
            },
        ]
    }
    with patch.object(safety, "_kubectl", return_value=_json(events)):
        passed, detail = checks["Probe Failures Stopped (post)"]()

    assert passed is False
    assert "timestamp unavailable" in detail
    assert "old failure" not in detail


def test_common_helpers_cover_empty_samples_and_pending_canary():
    with patch.object(common, "_first_running_pod", return_value="api-0"), patch.object(
        common, "_kubectl", return_value=_cp("nslookup")
    ):
        assert common._measure_dns_latency("ctx", "app", "app=api", "example.com", n=0) is None

    pods = {
        "items": [
                {
                    "metadata": {"name": "pending", "namespace": "app"},
                "status": {"phase": "Pending", "conditions": []},
            },
                {
                    "metadata": {"name": "ready", "namespace": "app"},
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                },
            },
        ]
    }
    with patch.object(common, "_kubectl", return_value=_json(pods)):
        assert common._canary_pod("ctx") == ("ready", "app")


def test_cluster_plane_closures_skip_failed_crd_query_and_old_warning_event():
    pre = cluster_plane.build_cluster_plane_chaos_pre_checks("ctx", "aks-coredns-kill")
    with patch.object(cluster_plane, "_kubectl", return_value=_cp(returncode=1)):
        passed, detail = pre["No Existing Chaos CRD For Target"]()
    assert passed is True
    assert "No existing chaos resources" in detail

    post = cluster_plane.build_cluster_plane_chaos_post_checks("ctx", "aks-coredns-kill")
    old = {
        "type": "Warning",
        "involvedObject": {"name": "coredns-old"},
        "lastTimestamp": "2000-01-01T00:00:00Z",
        "reason": "Unhealthy",
        "message": "old warning",
    }
    with patch.object(cluster_plane, "_kubectl", return_value=_json({"items": [old]})):
        passed, detail = post["No CoreDNS Warning Events Post-Chaos"]()
    assert passed is True
    assert "old warning" not in detail


def test_kube_proxy_canary_uses_api_connectivity_probe():
    checks = cluster_plane.build_cluster_plane_chaos_pre_checks("ctx", "aks-kube-proxy-kill")
    with patch.object(cluster_plane, "_canary_pod", return_value=("witness", "app")), patch.object(
        cluster_plane, "_kubectl", return_value=_cp("200")
    ) as kubectl:
        passed, detail = checks["Cluster-Wide Canary Baseline"]()

    assert passed is True
    assert "baseline captured" in detail
    assert "curl" in kubectl.call_args.args[-1]


def test_cluster_plane_stress_observation_uses_kube_system_and_handles_invalid_crd_json():
    responses = [
        _cp("coredns-1 1/1 Running 0\n"),
        _cp("not-json"),
        _cp(),
        _cp(),
    ]
    with patch.object(safety, "_kubectl", side_effect=responses):
        result = safety.verify_fault_active("aks-coredns-cpu", "ctx", "", "coredns")

    assert result["severity"] == "WARNING"
    assert "stress NOT injected" in result["message"]


def test_http_nsexec_check_accepts_containers_without_privilege_block():
    checks = http.build_http_chaos_pre_checks(
        "ctx", "app", "api", experiment_id="aks-http-delay"
    )

    def responder(*args, **kwargs):
        if args[:2] == ("get", "mutatingwebhookconfigurations"):
            return _json({"items": []})
        if args[:2] == ("get", "deployment"):
            return _json({"spec": {"template": {"spec": {"containers": [{"name": "api"}]}}}})
        return _cp(returncode=1)

    with patch.object(http, "_kubectl", side_effect=responder):
        passed, detail = checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"]()
    assert passed is True
    assert "No privilege escalation block" in detail


def test_time_checks_ignore_bad_certificate_dates_and_irrelevant_or_old_events():
    pre = time_checks.build_time_chaos_pre_checks(
        "ctx", "app", "api", time_offset="5m"
    )
    certs = {"items": [{"metadata": {"name": "api-cert"}, "status": {"notAfter": "bad"}}]}
    with patch.object(time_checks, "_kubectl", return_value=_json(certs)):
        passed, detail = pre["cert-manager Certificate Expiry Window"]()
    assert passed is True
    assert "No certificates at risk" in detail

    post = time_checks.build_time_chaos_post_checks("ctx", "app", "api")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    events = {
        "items": [
            {"type": "Normal", "lastTimestamp": now, "message": "certificate renewed"},
            {
                "type": "Warning", "lastTimestamp": "2000-01-01T00:00:00Z",
                "message": "TLS timeout",
            },
            {
                "type": "Warning", "lastTimestamp": "bad-time", "message": "image pulled",
                "reason": "Pulled",
            },
        ]
    }
    with patch.object(time_checks, "_kubectl", return_value=_json(events)):
        passed, detail = post["No TLS/Auth Events Post-Skew"]()
    assert passed is True
    assert "TLS timeout" not in detail


def test_basic_system_pod_checks_raise_for_required_query_failure_and_warn_for_optional(capsys):
    with pytest.raises(RuntimeError, match="Could not query CoreDNS"):
        basic.check_system_pods_running("ctx", lambda *args, **kwargs: _cp(returncode=1))

    coredns = {
        "items": [{
            "metadata": {"name": "coredns"},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }]
    }

    def optional_unready(*args, **kwargs):
        if "k8s-app=kube-dns" in args:
            return _json(coredns)
        if "k8s-app=kube-proxy" in args:
            return _json({"items": [{"metadata": {"name": "proxy"}, "status": {}}]})
        return _cp(returncode=1)

    basic.check_system_pods_running("ctx", optional_unready)
    assert "kube-proxy pods exist but not Ready" in capsys.readouterr().out


def test_network_probe_handles_malformed_endpoints_and_reports_inactive_partition():
    def responder(*args, **kwargs):
        if args[:2] == ("get", "networkchaos"):
            return _json({"items": []})
        if args[:1] == ("exec",):
            return _cp("Chain INPUT")
        if args[:2] == ("get", "endpoints"):
            return _cp("not-json")
        if args[:2] == ("get", "events"):
            return _cp("")
        if args[:2] == ("get", "pods"):
            return _json({"items": []})
        raise AssertionError(args)

    probe = fault_network.build_network_live_probe(
        kubectl=lambda: responder,
        find_svc_name=lambda: lambda *args: ("api", True),
        select_live_probe_pod=lambda: lambda *args: "api-0",
        annotate_network_result=lambda: lambda result, *args: result,
    )
    result = probe(
        "aks-network-partition", "ctx", "app", "api", "app", "api", None,
        ["-l", "app=api"], ["api-0 1/1 Running 0"], 1, ["api-0"], 0,
    )
    assert "chaos chain not detected" in result["message"]


def _pre_checks(module, experiment_id, responder):
    kwargs = {
        "kubectl": lambda: responder,
        "find_svc_name": lambda: lambda *args: ("api", True),
    }
    args = (experiment_id, "ctx", "app", "api", "app", "api", ["-l", "app=api"], "-l app=api")
    if module is complex_pre:
        kwargs["partition_ping_target"] = lambda: lambda context: "10.0.0.53"
    return module.build_pre_network_checks(*args, **kwargs)


def test_pre_network_checks_handle_malformed_state_and_unavailable_commands():
    def malformed(*args, **kwargs):
        return _cp("not-json")

    delay = _pre_checks(simple_pre, "aks-network-delay", malformed)
    assert "parse failed" in delay["No Existing NetworkChaos"]()[1]
    assert "endpoint query failed" not in delay["Service Endpoints (baseline)"]()[1]

    def unavailable(*args, **kwargs):
        if args[:2] == ("get", "deployment"):
            return _cp("not-json")
        if args[:2] == ("get", "pods"):
            return _json({"items": []})
        return _cp(returncode=1)

    partition = _pre_checks(complex_pre, "aks-network-partition", unavailable)
    assert "no running pod" in partition[
        "Baseline Connectivity (ping — 0% loss pre-fault)"
    ]()[1]
    assert "could not parse" in partition["Replica Count Safety (partition impact)"]()[1]


@pytest.mark.parametrize(
    ("module", "experiment_id"),
    [
        (simple_post, "aks-network-delay"),
        (simple_post, "aks-packet-loss"),
        (simple_post, "aks-bandwidth-limit"),
        (complex_post, "aks-packet-corruption"),
        (complex_post, "aks-packet-duplication"),
        (complex_post, "aks-network-partition"),
    ],
)
def test_post_network_command_checks_skip_when_no_pod_is_running(module, experiment_id):
    responder = MagicMock(return_value=_json({"items": []}))
    kwargs = {
        "kubectl": lambda: responder,
        "find_svc_name": lambda: lambda *args: ("api", True),
    }
    args = (experiment_id, "ctx", "app", "api", "app", "api", ["-l", "app=api"], "-l app=api")
    if module is complex_post:
        kwargs["partition_ping_target"] = lambda: lambda context: "10.0.0.53"
    checks = module.build_post_network_checks(*args, **kwargs)

    command_check = next(
        check for label, check in checks.items()
        if label.startswith(("tc-", "iptables"))
    )
    passed, detail = command_check()
    assert passed is True
    assert "no running pod" in detail


def test_partition_ping_parser_tolerates_malformed_loss_and_rtt_lines():
    pods = _json({"items": [{"metadata": {"name": "api-0"}, "status": {"phase": "Running"}}]})

    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return pods
        if args[:1] == ("exec",):
            return _cp("% packet loss\nrtt min/avg/max = broken")
        raise AssertionError(args)

    checks = complex_post.build_post_network_checks(
        "aks-network-partition", "ctx", "app", "api", "app", "api",
        ["-l", "app=api"], "-l app=api", kubectl=lambda: responder,
        find_svc_name=lambda: lambda *args: ("api", True),
        partition_ping_target=lambda: lambda context: "10.0.0.53",
    )
    passed, detail = checks["Connectivity Restored (ping — 0% loss)"]()
    assert passed is True
    assert "packet loss = None%" in detail
