"""
Unit tests for verify_fault_active in actions/aks_safety_checks.py — the
in-fault polling probe called every poll_interval during a chaos experiment.
Covers the major experiment-type branches. Network-fault branches
(delay/loss/corruption/duplication/bandwidth) share near-identical
structure — delay, loss and bandwidth are covered directly here as
representative samples of that shared code path.
"""

import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as aks_safety_checks,
)


def _cp(stdout="", returncode=0, stderr=""):
    return CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_returns_empty_string_when_no_namespace():
    result = aks_safety_checks.verify_fault_active("aks-pod-kill", "ctx", "", "dep")
    assert result == ""


# ── Python-client experiments (pod-kill / pod-failure) ──────────────────────

def test_pod_kill_reports_terminating_and_running_counts():
    pods = [
        {"metadata": {"name": "p1", "deletionTimestamp": "2026-09-21T00:00:00Z"}, "status": {"phase": "Terminating"}},
        {"metadata": {"name": "p2"}, "status": {"phase": "Running"}},
    ]
    with patch("chaosforge.providers.azure.components.aks.kubernetes.get_pods", return_value=(pods, None)):
        result = aks_safety_checks.verify_fault_active(
            "aks-pod-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert result["severity"] in ("CHAOS", "WARNING", "INFO", "EVENT")
    assert "1" in result["message"] or "terminating" in result["message"].lower()


def test_pod_kill_logs_dedup_kill_event_once_per_pod():
    pods = [{"metadata": {"name": "p1", "deletionTimestamp": "now"}, "status": {"phase": "Terminating"}}]
    fake_session = MagicMock()
    seen = set()
    with patch("chaosforge.providers.azure.components.aks.kubernetes.get_pods", return_value=(pods, None)):
        aks_safety_checks.verify_fault_active(
            "aks-pod-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
            session=fake_session, _seen_killed=seen,
        )
        aks_safety_checks.verify_fault_active(
            "aks-pod-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
            session=fake_session, _seen_killed=seen,
        )
    assert fake_session.log_event.call_count == 1
    assert "p1" in seen


def test_pod_failure_reports_not_ready_containers():
    pods = [{"metadata": {"name": "p1"}, "status": {"containerStatuses": [{"ready": False}]}}]
    with patch("chaosforge.providers.azure.components.aks.kubernetes.get_pods", return_value=(pods, None)):
        result = aks_safety_checks.verify_fault_active(
            "aks-pod-failure", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "message" in result


def test_pod_kill_reports_warning_when_client_returns_no_data():
    with patch("chaosforge.providers.azure.components.aks.kubernetes.get_pods", return_value=(None, "connection refused")):
        result = aks_safety_checks.verify_fault_active(
            "aks-pod-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert result["severity"] == "WARNING"
    assert "connection refused" in result["message"]


# ── container-kill / crashloop (kubectl no-headers restart column) ─────────

def test_container_kill_reports_pods_with_nonzero_restarts():
    stdout = "pod-a  1/1  Running  3\npod-b  1/1  Running  0\n"
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout=stdout)):
        result = aks_safety_checks.verify_fault_active(
            "aks-container-kill", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "pod-a=3" in result["message"] or "pod-a=3" in str(result)


# ── stress-chaos (cpu/memory) ───────────────────────────────────────────────

def test_cpu_stress_returns_pod_rows_and_node_rows():
    pods_stdout = "pod-a  1/1  Running  0\n"
    stresschaos_json = json.dumps({"items": [{"status": {"conditions": [
        {"type": "AllInjected", "status": "True"}
    ]}}]})
    top_pods_stdout = "pod-a  stress-ng  950m  200Mi\n"
    nodeName_stdout = "node-a"
    top_nodes_stdout = "node-a  1900m  95%  3000Mi  40%\n"
    responses = [
        _cp(stdout=pods_stdout),        # get pods --no-headers
        _cp(stdout=stresschaos_json),   # get stresschaos -o json
        _cp(stdout=top_pods_stdout),    # top pods --containers
        _cp(stdout=nodeName_stdout),    # get pods jsonpath nodeName
        _cp(stdout=top_nodes_stdout),   # top nodes
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses):
        result = aks_safety_checks.verify_fault_active(
            "aks-cpu-stress", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert result["severity"] == "INFO"
    assert result["pod_rows"] == [("pod-a", "stress-ng", "950m", "200Mi")]
    assert result["node_rows"] == [("node-a", "1900m", "95%", "3000Mi", "40%")]


# ── network-delay (full branch: tc, CRD, endpoints, restarts, events, ping) ─

def test_network_delay_reports_netem_active_and_crd_injected():
    networkchaos = {"items": [{"status": {"conditions": [{"type": "AllInjected", "status": "True"}]}}]}
    endpoints = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}], "notReadyAddresses": []}]}
    pods_json = {"items": [{"status": {"containerStatuses": [{"restartCount": 2}]}}]}

    def _kubectl_router(*args, **kwargs):
        if args[:1] == ("exec",) and args[5:7] == ("tc", "qdisc"):
            return _cp(stdout="qdisc netem 8001: dev eth0 root refcnt 2 limit 1000 delay 500ms")
        if args[:2] == ("get", "networkchaos"):
            return _cp(stdout=json.dumps(networkchaos))
        if args[:2] == ("get", "endpoints"):
            return _cp(stdout=json.dumps(endpoints))
        if args[:2] == ("get", "events"):
            return _cp(stdout="")
        if args[:2] == ("get", "pods") and "-o" in args and "json" in args:
            return _cp(stdout=json.dumps(pods_json))
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _cp(stdout="pod-a  1/1  Running  0\n")
        if args[:2] == ("get", "service"):
            return _cp(stdout="10.0.0.10")
        if args[:1] == ("exec",) and args[5:7] == ("ping", "-c"):
            return _cp(stdout="64 bytes: icmp_seq=1 ttl=63 time=501 ms")
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("svc-a", True)):
        result = aks_safety_checks.verify_fault_active(
            "aks-network-delay", "ctx", "ns", "dep", label_key="app", label_val="x",
        )

    assert result["severity"] == "CHAOS"
    assert "tc-netem ACTIVE" in result["message"]
    assert "NetworkChaos AllInjected=True" in result["message"]
    assert any(row[0] == "Endpoints ready" for row in result["net_rows"])


def test_network_delay_reports_unknown_injection_when_crd_not_found():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout="pod-a  1/1  Running  0\n")), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        result = aks_safety_checks.verify_fault_active(
            "aks-network-delay", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "NetworkChaos: injection status unknown" in result["message"]
    assert result["severity"] == "WARNING"


# ── packet-loss (tc netem "loss" keyword + /proc/net/snmp RetransSegs) ──────

def test_packet_loss_reads_retrans_segs_from_proc_net_snmp():
    def _kubectl_router(*args, **kwargs):
        if args[:1] == ("exec",) and args[5:7] == ("tc", "qdisc"):
            return _cp(stdout="qdisc netem 8001: dev eth0 root loss 25%")
        if args[:1] == ("exec",) and args[5:7] == ("cat", "/proc/net/snmp"):
            return _cp(stdout="Tcp: RtoAlgorithm RtoMin RetransSegs\nTcp: 1 200 42\n")
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _cp(stdout="pod-a  1/1  Running  0\n")
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        result = aks_safety_checks.verify_fault_active(
            "aks-packet-loss", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "RetransSegs=42" in result["message"]
    assert result["severity"] == "CHAOS"


# ── bandwidth-limit (tc tbf keyword; no live throughput measurement) ────────

def test_bandwidth_limit_detects_tbf_rule_and_defers_throughput_to_post_check():
    def _kubectl_router(*args, **kwargs):
        if args[:1] == ("exec",) and args[5:7] == ("tc", "qdisc"):
            return _cp(stdout="qdisc tbf 8001: dev eth0 root rate 1mbit burst 1600b")
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _cp(stdout="pod-a  1/1  Running  0\n")
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        result = aks_safety_checks.verify_fault_active(
            "aks-bandwidth-limit", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "tc-tbf ACTIVE" in result["message"]
    assert any(row[0] == "Throughput" for row in result["net_rows"])


# ── packet-corruption (tc netem "corrupt" keyword) ──────────────────────────

def test_packet_corruption_detects_netem_corrupt_rule():
    def _kubectl_router(*args, **kwargs):
        if args[:1] == ("exec",) and args[5:7] == ("tc", "qdisc"):
            return _cp(stdout="qdisc netem 8001: dev eth0 root corrupt 10%")
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _cp(stdout="pod-a  1/1  Running  0\n")
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        result = aks_safety_checks.verify_fault_active(
            "aks-packet-corruption", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "tc-netem ACTIVE corrupt rule" in result["message"]
    assert result["severity"] == "CHAOS"


def test_packet_corruption_reports_not_detected_when_no_netem():
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout="pod-a  1/1  Running  0\n")), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        result = aks_safety_checks.verify_fault_active(
            "aks-packet-corruption", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "not detected" in result["message"]
    assert result["severity"] == "WARNING"


# ── packet-duplication (tc netem "duplicate" keyword + DSACK) ───────────────

def test_packet_duplication_reports_retrans_and_dsack_counters():
    def _kubectl_router(*args, **kwargs):
        if args[:1] == ("exec",) and args[5:7] == ("tc", "qdisc"):
            return _cp(stdout="qdisc netem 8001: dev eth0 root duplicate 50%")
        if args[:1] == ("exec",) and args[5:7] == ("cat", "/proc/net/snmp"):
            return _cp(stdout="Tcp: RtoAlgorithm RtoMin RetransSegs\nTcp: 1 200 7\n")
        if args[:1] == ("exec",) and args[5:7] == ("cat", "/proc/net/netstat"):
            return _cp(stdout="TcpExt: SyncookiesSent TCPDSACKRecv\nTcpExt: 0 13\n")
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _cp(stdout="pod-a  1/1  Running  0\n")
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("", False)):
        result = aks_safety_checks.verify_fault_active(
            "aks-packet-duplication", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "tc-netem ACTIVE duplicate rule" in result["message"]
    assert "TCP RetransSegs=7" in result["message"]
    assert "TCPDSACKRecv=13" in result["message"]
    assert result["severity"] == "CHAOS"


# ── network-partition (iptables CHAOS chain, NotReady is expected/not a warn) ─

def test_partition_reports_iptables_chaos_chain_and_zero_endpoints_as_expected():
    networkchaos = {"items": [{"status": {"conditions": [{"type": "AllInjected", "status": "True"}]}}]}
    endpoints = {"subsets": [{"addresses": [], "notReadyAddresses": [{"ip": "10.0.0.1"}]}]}

    def _kubectl_router(*args, **kwargs):
        if args[:1] == ("exec",) and args[5:7] == ("iptables", "-L"):
            return _cp(stdout="Chain CHAOS-XYZ (1 references)\nDROP  all  --  0.0.0.0/0  0.0.0.0/0\n")
        if args[:2] == ("get", "networkchaos"):
            return _cp(stdout=json.dumps(networkchaos))
        if args[:2] == ("get", "endpoints"):
            return _cp(stdout=json.dumps(endpoints))
        if args[:2] == ("get", "pods") and "--no-headers" in args:
            return _cp(stdout="pod-a  1/1  Running  0\n")
        return _cp(stdout="")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router), \
         patch.object(aks_safety_checks, "_find_svc_name", return_value=("svc-a", True)):
        result = aks_safety_checks.verify_fault_active(
            "aks-network-partition", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert result["severity"] == "CHAOS"
    assert "all partitioned pods removed from Service routing (expected)" in result["message"]
    assert "iptables CHAOS chain ACTIVE" in result["message"]


# ── IOChaos (aks-io-latency / aks-io-errors) ────────────────────────────────

def test_iochaos_warns_when_crd_not_yet_injected():
    pods_json = {"items": [{"spec": {"initContainers": []}, "status": {"containerStatuses": []}}]}

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "iochaos"):
            return _cp(stdout=json.dumps({"items": []}))
        if args[:2] == ("get", "pods"):
            return _cp(stdout=json.dumps(pods_json))
        return _cp(stdout="pod-a  1/1  Running  0\n")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router):
        result = aks_safety_checks.verify_fault_active(
            "aks-io-latency", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert "IOChaos: injection pending" in result["message"]
    assert result["severity"] == "WARNING"


def test_iochaos_reports_chaos_when_crd_injected_and_surfaces_restarts():
    pods_json = {"items": [{"spec": {"initContainers": [{"name": "chaos-fs"}]},
                             "status": {"containerStatuses": [{"restartCount": 2}]}}]}
    iochaos = {"items": [{"status": {"conditions": [{"type": "AllInjected", "status": "True"}]}}]}

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "iochaos"):
            return _cp(stdout=json.dumps(iochaos))
        if args[:2] == ("get", "pods"):
            return _cp(stdout=json.dumps(pods_json))
        return _cp(stdout="pod-a  1/1  Running  0\n")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router):
        result = aks_safety_checks.verify_fault_active(
            "aks-io-errors", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert result["severity"] == "CHAOS"
    assert "IOChaos AllInjected=True" in result["message"]
    assert "container restarts: 2" in result["message"]


# ── DNS failure (aks-dns-failure) ───────────────────────────────────────────

def test_dns_failure_reports_chaos_when_resolution_fails():
    dnschaos = {"items": [{
        "metadata": {"uid": "uid-1"},
        "status": {
            "conditions": [{"type": "AllInjected", "status": "True"}],
            "experiment": {"containerRecords": [{"id": "ns/pod-a/app"}]},
        },
    }]}

    def _kubectl_router(*args, **kwargs):
        if args[:2] == ("get", "dnschaos") and "jsonpath={.items[0].spec.patterns[0]}" in args:
            return _cp(stdout="*.example.com")
        if args[:2] == ("get", "dnschaos") and any("containerRecords" in a for a in args):
            return _cp(stdout="ns/pod-a/app")
        if args[:2] == ("get", "dnschaos"):
            return _cp(stdout=json.dumps(dnschaos))
        if args[:1] == ("exec",) and "nslookup" in " ".join(args):
            return _cp(returncode=1, stdout="", stderr="** server can't find kubernetes.default.svc.cluster.local: NXDOMAIN")
        return _cp(stdout="pod-a  1/1  Running  0\n")

    with patch.object(aks_safety_checks, "_kubectl", side_effect=_kubectl_router):
        result = aks_safety_checks.verify_fault_active(
            "aks-dns-failure", "ctx", "ns", "dep", label_key="app", label_val="x",
        )
    assert result["severity"] == "CHAOS"
    assert "chaos injecting" in result["message"]


def test_dns_failure_reports_warning_when_no_pattern_available():
    # Distinct namespace/deployment from the other dns-failure test above —
    # verify_fault_active tracks "ever observed chaos" per aks_context/ns/deployment
    # in a module-level dict, so reusing the same target would leak state across tests.
    with patch.object(aks_safety_checks, "_kubectl", return_value=_cp(stdout="pod-a  1/1  Running  0\n")):
        result = aks_safety_checks.verify_fault_active(
            "aks-dns-failure", "ctx", "ns2", "dep2", label_key="app", label_val="x",
        )
    assert result["severity"] == "WARNING"
    assert "DNSChaos: injection pending" in result["message"]
