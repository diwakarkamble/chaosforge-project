"""Focused coverage for previously unexecuted AKS safety-check branches."""

import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

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
    _safety_post_network_delay_loss_bandwidth as post_network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_corruption_duplication_partition as pre_destructive,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    _safety_pre_network_delay_loss_bandwidth as pre_network,
)
from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import event_log


def _result(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _json(value):
    return _result(json.dumps(value))


def _running_pods(restarts=0):
    return _json({
        "items": [{
            "metadata": {"name": "api-0"},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
                "containerStatuses": [{"restartCount": restarts}],
            },
            "spec": {"containers": [{"name": "api"}]},
        }],
    })


def _build_pre(module, experiment_id, responder, service=("api", True)):
    kwargs = {
        "kubectl": lambda: MagicMock(side_effect=responder),
        "find_svc_name": lambda: lambda *_: service,
    }
    args = (
        experiment_id, "ctx", "app", "api", "app", "api",
        ("-l", "app=api"), "-l app=api",
    )
    if module is pre_destructive:
        kwargs["partition_ping_target"] = lambda: lambda _: "10.0.0.53"
    return module.build_pre_network_checks(*args, **kwargs)


def test_delay_prechecks_cover_api_fallback_stale_cleanup_and_parse_failures():
    calls = []

    def responder(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("get", "crd", "networkchaoses.chaos-mesh.org"):
            return _result(returncode=1)
        if args[:3] == ("get", "networkchaos", "--all-namespaces"):
            return _result("api available")
        if args[:2] == ("get", "networkchaos"):
            return _json({"items": [{"metadata": {"name": "stale"}}]})
        if args[:2] == ("delete", "networkchaos"):
            return _result()
        if args[:2] == ("get", "pods"):
            return _result("not-json")
        if args[:2] == ("get", "deployment"):
            return _result("not-json")
        raise AssertionError(args)

    checks = _build_pre(pre_network, "aks-network-delay", responder)
    assert checks["NetworkChaos CRD Installed"]() == (
        True,
        "kubectl get networkchaos --all-namespaces --no-headers\n  NetworkChaos API available",
    )
    assert "auto-deleted" in checks["No Existing NetworkChaos"]()[1]
    assert "no running pod" in checks["No Existing tc-netem Rule"]()[1]
    assert "could not parse" in checks["Probe Timeouts vs Delay (impact analysis)"]()[1]
    assert "parse failed" in checks["Pod Restart Baseline"]()[1]
    assert "no running pod" in checks["Baseline HTTP Response Time"]()[1]
    assert any(call[:2] == ("delete", "networkchaos") for call in calls)


@pytest.mark.parametrize("experiment_id", ["aks-network-delay", "aks-bandwidth-limit"])
def test_delay_prechecks_cover_endpoint_and_exec_advisories(experiment_id):
    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _running_pods()
        if args[:2] == ("get", "endpoints"):
            return _json({"subsets": []})
        if args[:3] == ("get", "service", "kube-dns"):
            return _result(returncode=1)
        if args[:1] == ("exec",):
            return _result(returncode=127, stderr="not installed")
        raise AssertionError(args)

    checks = _build_pre(pre_network, experiment_id, responder)
    assert checks["Service Endpoints (baseline)"]()[0] is False
    tc_name = next(name for name in checks if name.startswith("No Existing tc"))
    assert "unavailable" in checks[tc_name]()[1]
    ping_name = next(name for name in checks if name.startswith("Baseline Ping"))
    assert "command unavailable" in checks[ping_name]()[1]


def test_delay_prechecks_cover_query_failures_and_absent_service():
    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _running_pods()
        return _result(returncode=1, stderr="denied")

    checks = _build_pre(
        pre_network,
        "aks-packet-loss",
        responder,
        service=("", False),
    )
    assert "query failed" in checks["No Existing NetworkChaos"]()[1]
    assert "skipping endpoint" in checks["Service Endpoints (baseline)"]()[1]
    assert "not applicable" in checks["Baseline DNS Resolution (UDP)"]()[1]


def test_destructive_prechecks_cover_stale_resources_rules_and_unsafe_baselines():
    def responder(*args, **kwargs):
        if args[:3] == ("get", "crd", "networkchaoses.chaos-mesh.org"):
            return _result(returncode=1)
        if args[:3] == ("get", "networkchaos", "--all-namespaces"):
            return _result(returncode=1)
        if args[:3] == ("get", "networkchaos", "-n") and "--no-headers" in args:
            return _result(returncode=1)
        if args[:2] == ("get", "networkchaos"):
            return _json({"items": [{"metadata": {"name": "stale"}}]})
        if args[:2] == ("delete", "networkchaos"):
            return _result()
        if args[:2] == ("get", "pods"):
            return _running_pods()
        if args[:2] == ("get", "endpoints"):
            return _result("bad-json")
        if args[:2] == ("get", "deployment"):
            return _json({"spec": {"replicas": 1}})
        if args[:1] == ("exec",) and "iptables" in args:
            return _result("Chain CHAOS-DROP")
        if args[:1] == ("exec",) and "ping" in args:
            return _result("3 packets transmitted, 2 received, 33% packet loss")
        if args[:1] == ("exec",):
            return _result(returncode=127)
        return _result(returncode=1)

    checks = _build_pre(pre_destructive, "aks-network-partition", responder)
    assert checks["NetworkChaos CRD Installed"]()[0] is False
    assert "auto-deleted" in checks["No Existing NetworkChaos"]()[1]
    assert checks["No Existing iptables Chaos Rules"]()[0] is False
    assert checks["Service Endpoints (baseline)"]()[0] is False
    assert checks["Replica Count Safety (partition impact)"]()[0] is False
    assert checks["Baseline Connectivity (ping — 0% loss pre-fault)"]()[0] is False
    assert "command unavailable" in checks["Baseline DNS Resolution"]()[1]


def test_destructive_prechecks_cover_malformed_and_missing_pod_paths():
    checks = _build_pre(
        pre_destructive,
        "aks-packet-duplication",
        lambda *args, **kwargs: _result("not-json"),
    )
    assert "parse failed" in checks["No Existing NetworkChaos"]()[1]
    assert "no running pod" in checks["No Existing tc-netem Rule"]()[1]
    assert "no running pod" in checks["Baseline Ping (0 DUP! pre-fault)"]()[1]
    assert "parse failed" in checks["Pod Restart Baseline"]()[1]


def _build_post(experiment_id, responder, service=("api", True)):
    return post_network.build_post_network_checks(
        experiment_id, "ctx", "app", "api", "app", "api",
        ("-l", "app=api"), "-l app=api",
        kubectl=lambda: MagicMock(side_effect=responder),
        find_svc_name=lambda: lambda *_: service,
    )


def _degraded_post_responder(experiment_id):
    recent_warning = {
        "type": "Warning",
        "lastTimestamp": "not-a-timestamp",
        "reason": "NetworkNotReady",
        "message": "network timeout continues",
        "involvedObject": {"name": "api-0"},
    }

    def responder(*args, **kwargs):
        if args[:2] == ("get", "networkchaos"):
            return _result("fault-a\nfault-b\n")
        if args[:2] == ("delete", "networkchaos"):
            return _result()
        if args[:2] == ("get", "pods"):
            return _running_pods(restarts=5)
        if args[:3] == ("get", "service", "kube-dns"):
            return _result("10.0.0.10")
        if args[:2] == ("get", "endpoints"):
            return _json({"subsets": [{
                "addresses": [{"ip": "10.0.0.1"}],
                "notReadyAddresses": [{"ip": "10.0.0.2"}],
            }]})
        if args[:2] == ("get", "events"):
            return _json({"items": [recent_warning]})
        if args[:1] == ("exec",) and "tc" in args:
            return _result("qdisc tbf netem dev eth0")
        if args[:1] == ("exec",) and "nslookup" in args:
            return _result("server can't find api: NXDOMAIN")
        if args[:1] == ("exec",) and "ping" in args:
            return _result("0% packet loss\nrtt avg = malformed")
        if args[:1] == ("exec",) and "/proc/net/snmp" in args:
            return _result("Tcp: RetransSegs\nTcp: 17")
        if args[:1] == ("exec",) and "curl" in args:
            if experiment_id == "aks-network-delay":
                return _result("1.750")
            if experiment_id == "aks-bandwidth-limit" and "10" in args:
                return _result("1024 2.0 1024")
            return _result("503 6.5")
        raise AssertionError(args)

    return responder


@pytest.mark.parametrize(
    ("experiment_id", "rule_name", "key_failure"),
    [
        ("aks-network-delay", "tc-netem Rule Removed", "HTTP Response Time Restored"),
        ("aks-packet-loss", "tc-netem Rule Removed", "HTTP Success Restored"),
        ("aks-bandwidth-limit", "tc-tbf Rule Removed", "Throughput Restored (KB/s)"),
    ],
)
def test_post_network_checks_report_multiple_independent_recovery_failures(
    experiment_id, rule_name, key_failure
):
    checks = _build_post(experiment_id, _degraded_post_responder(experiment_id))
    results = {name: check() for name, check in checks.items()}

    assert "auto-deleted" in results["NetworkChaos CRD Cleaned Up"][1]
    assert results[rule_name][0] is False
    assert results[key_failure][0] is False
    assert results["Service Endpoints Restored"][0] is False
    assert results["Probe Failures Stopped (post)"][0] is False
    assert results["No Network Warning Events (post)"][0] is False
    assert "High restart" in results["Restart Count Delta (post)"][1]
    dns_name = (
        "DNS Resolution Restored (UDP)"
        if experiment_id == "aks-packet-loss"
        else "DNS Resolution Restored"
    )
    assert results[dns_name][0] is False


@pytest.mark.parametrize("experiment_id", ["aks-packet-loss", "aks-bandwidth-limit"])
def test_post_network_service_dependent_checks_skip_without_service(experiment_id):
    def responder(*args, **kwargs):
        if args[:2] == ("get", "pods"):
            return _running_pods()
        raise AssertionError(args)

    checks = _build_post(experiment_id, responder, service=("", False))
    dependent = (
        ["DNS Resolution Restored (UDP)", "HTTP Success Restored"]
        if experiment_id == "aks-packet-loss"
        else ["Throughput Restored (KB/s)", "HTTP Success Restored", "DNS Resolution Restored"]
    )
    for name in dependent:
        passed, detail = checks[name]()
        assert passed is True
        assert "not applicable" in detail


def test_event_log_formats_console_tables_banners_and_status_variants():
    console = MagicMock()
    live = MagicMock(console=console)

    with patch.object(event_log, "_ts", return_value="12:34:56"):
        event_log.log_line(live, "custom", "message")
        event_log.log_console_line(console, "warning", "careful")
        event_log.log_crashloop_event(console, "event", "restart", ts="01:02:03")
        banner = event_log.format_experiment_start(
            "custom-fault", "app", "api", 30, True,
            target_summary=["selector app=api"],
        )

    event_log.log_stress_metrics(live, "12:00:00", {
        "summary": "stress active",
        "pod_rows": [("api-0", "api", "10m", "20Mi")],
        "node_rows": [("node-a", "100m", "10%", "1Gi", "20%")],
    })
    event_log.log_net_metrics(live, "12:00:01", {"message": "empty"})
    event_log.log_net_metrics(live, "12:00:02", {
        "severity": "WARNING",
        "message": "degraded",
        "net_rows": [("loss", "20%"), ("rtt", "50ms", "high")],
    })

    rendered = "\n".join(str(call.args[0]) for call in console.print.call_args_list)
    assert "CUSTOM" in rendered and "bold white" in rendered
    assert "POD" in rendered and "NODE" in rendered and "METRIC" in rendered
    assert "high" in rendered
    assert "DRY RUN PREVIEW" in banner[0]
    assert "selector app=api" in banner[-1]

    assert event_log.pod_kill_status(1, 2, 1)["severity"] == "EVENT"
    assert event_log.pod_kill_status(2, 2, 0)["severity"] == "INFO"
    assert event_log.pod_kill_event("api-0")["severity"] == "CHAOS"
    assert event_log.pod_recovery_event("api-1")["severity"] == "RECOVERY"
    assert event_log.pod_failure_status(1, 2, 1)["severity"] == "EVENT"
    assert event_log.pod_failure_status(2, 2, 0)["severity"] == "RECOVERY"
    assert event_log.container_kill_status(2, ["api-0=1"])["severity"] == "EVENT"
    assert event_log.container_kill_status(2, [])["severity"] == "INFO"
    assert "#3" in event_log.crashloop_kill_event(3, "api-0", 10)["message"]
    assert "CrashLoopBackOff" in event_log.crashloop_restart_detected("api-0", 4)["message"]
    assert event_log.stress_summary(1, 2, "cpu", "95%")["severity"] == "WARNING"
    assert event_log.stress_summary(2, 2, "memory")["severity"] == "INFO"


def test_http_extended_checks_cover_advisory_and_missing_resource_paths():
    checks = http.build_http_chaos_pre_checks("ctx", "app", "api", injected_delay="2s")
    with patch.object(http, "_get_deployment_json", return_value=(None, "forbidden")):
        assert "skipping probe" in checks["Liveness Probe vs Injected Delay"]()[1]
        assert "skipping probe" in checks["Readiness Probe vs Injected Delay"]()[1]
        assert "skipping port" in checks["HTTP Target Port (80) Exists"]()[1]

    no_probes = {"spec": {"template": {"spec": {"containers": [{"name": "api"}]}}}}
    with patch.object(http, "_get_deployment_json", return_value=(no_probes, None)):
        assert "No liveness probes" in checks["Liveness Probe vs Injected Delay"]()[1]
        assert "No readiness probes" in checks["Readiness Probe vs Injected Delay"]()[1]

    abort = http.build_http_chaos_pre_checks(
        "ctx", "app", "api", experiment_id="aks-http-abort", http_port="80"
    )
    probe = {"spec": {"template": {"spec": {"containers": [{
        "name": "api", "livenessProbe": {"httpGet": {"port": 80}}
    }]}}}}
    with patch.object(http, "_kubectl", return_value=_result("inject-v1-pod")), patch.object(
        http, "_get_deployment_json", return_value=(probe, None)
    ):
        passed, detail = abort["Liveness Probe vs Injected Delay"]()
    assert passed is True
    assert "Sidecar-injection install" in detail


def test_http_post_events_filter_irrelevant_old_and_malformed_timestamps():
    checks = http.build_http_chaos_post_checks("ctx", "app", "api")
    events = {"items": [
        {"type": "Normal", "reason": "Unhealthy"},
        {"type": "Warning", "reason": "Other"},
        {
            "type": "Warning", "reason": "Unhealthy",
            "lastTimestamp": "2000-01-01T00:00:00Z", "message": "old",
        },
        {
            "type": "Warning", "reason": "ProbeWarning",
            "lastTimestamp": "invalid", "message": "still failing",
            "involvedObject": {"name": "api-0"},
        },
    ]}
    with patch.object(http, "_kubectl", return_value=_json(events)):
        passed, detail = checks["No Probe Failures Post-HTTP Chaos"]()
    assert passed is False
    assert "api-0" in detail
    assert "old" not in detail


def test_dns_extended_checks_cover_tool_acme_latency_and_event_edges():
    empty = dns.build_dns_chaos_pre_checks("ctx", "app", "api", dns_pattern="")
    assert "empty" in empty["DNS Pre-Resolution (not set)"]()[1]

    checks = dns.build_dns_chaos_pre_checks("ctx", "app", "api", dns_pattern="example.com")
    with patch.object(dns, "_first_running_pod", return_value="api-0"), patch.object(
        dns, "_kubectl", return_value=_result()
    ):
        assert "No DNS tools" in checks[
            "Shell Present in Target Pod (DNSChaos Requirement)"
        ]()[1]
        assert "Could not verify" in checks["DNS Pre-Resolution (example.com)"]()[1]

    issuers = {"items": [{"spec": {"acme": {"server": "https://acme.test/directory"}}}]}
    with patch.object(dns, "_kubectl", return_value=_json(issuers)):
        assert "does not overlap" in checks[
            "cert-manager ACME Issuer Domain (Advisory)"
        ]()[1]

    post = dns.build_dns_chaos_post_checks("ctx", "app", "api", dns_pattern="example.com")
    events = {"items": [
        {"type": "Normal", "message": "dns lookup"},
        {
            "type": "Warning", "lastTimestamp": "2000-01-01T00:00:00Z",
            "message": "old dns lookup",
        },
        {
            "type": "Warning", "lastTimestamp": "invalid", "reason": "Failed",
            "message": "DNS lookup timed out", "involvedObject": {"name": "api-0"},
        },
    ]}
    with patch.object(dns, "_kubectl", return_value=_json(events)):
        passed, detail = post["No DNS Error Events Post-Chaos"]()
    assert passed is False
    assert "api-0" in detail
    assert "old dns" not in detail


def test_io_extended_checks_cover_mount_replica_and_exec_failures():
    checks = io.build_io_chaos_pre_checks("ctx", "app", "api", volume_path="/data")

    with patch.object(io, "_first_running_pod", return_value="api-0"), patch.object(
        io, "_kubectl", return_value=_result("MISSING")
    ):
        assert checks["Volume Mount Path Exists"]()[0] is False
    with patch.object(io, "_kubectl", return_value=_result(returncode=1)):
        assert "query failed" in checks["Replica Count Safety (I/O impact)"]()[1]
    with patch.object(io, "_kubectl", return_value=_json({"spec": {"replicas": 1}})):
        assert "Only 1 replica" in checks["Replica Count Safety (I/O impact)"]()[1]

    post = io.build_io_chaos_post_checks("ctx", "app", "api")
    with patch.object(io, "_first_running_pod", return_value="api-0"), patch.object(
        io, "_kubectl", return_value=_result(
            returncode=1, stderr="OCI runtime exec failed"
        )
    ):
        passed, detail = post["Residual I/O Fault Check"]()
    assert passed is True
    assert "exec unavailable" in detail
