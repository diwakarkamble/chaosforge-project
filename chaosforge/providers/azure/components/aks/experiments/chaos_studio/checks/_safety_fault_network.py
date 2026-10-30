"""Live NetworkChaos probes, parameterized by safety.py dependency thunks."""

import json

_NETWORK_IDS = frozenset({
    "aks-network-delay", "aks-packet-loss", "aks-packet-corruption",
    "aks-bandwidth-limit", "aks-packet-duplication", "aks-network-partition",
})


def build_network_live_probe(*, kubectl, find_svc_name, select_live_probe_pod,
                             annotate_network_result):
    """Build a probe without capturing safety.py's monkeypatchable dependencies."""

    def probe(experiment_id, aks_context, namespace, deployment, label_key,
              label_val, session, selection_args, lines, total, target_pod_names,
              restart_baseline):
        if experiment_id not in _NETWORK_IDS:
            return None

        run = kubectl()
        service_for = find_svc_name()
        select_pod = select_live_probe_pod()
        annotate = annotate_network_result()
        pod_name = select_pod(lines, target_pod_names)
        is_partition = experiment_id == "aks-network-partition"
        kind = {
            "aks-network-delay": ("netem", "", "tc-netem", "ACTIVE"),
            "aks-packet-loss": ("netem", "loss", "tc-netem", "ACTIVE loss rule"),
            "aks-packet-corruption": ("netem", "corrupt", "tc-netem", "ACTIVE corrupt rule"),
            "aks-bandwidth-limit": ("tbf", "", "tc-tbf", "ACTIVE"),
            "aks-packet-duplication": ("netem", "duplicate", "tc-netem", "ACTIVE duplicate rule"),
        }.get(experiment_id)

        crd_injected = False
        rc = run("get", "networkchaos", "-n", "chaos-testing", "-o", "json",
                 context=aks_context)
        if rc.returncode == 0:
            try:
                crd_injected = any(
                    condition.get("type") == "AllInjected" and condition.get("status") == "True"
                    for item in json.loads(rc.stdout).get("items", [])
                    for condition in (item.get("status", {}).get("conditions") or [])
                )
            except ValueError:
                pass

        active = False
        active_detail = ""
        if is_partition:
            if pod_name:
                rule = run("exec", pod_name, "-n", namespace, "--", "iptables", "-L", "-n",
                           context=aks_context)
                if rule.returncode == 0:
                    chaos_lines = [line for line in rule.stdout.splitlines() if "chaos" in line.lower()]
                    active = bool(chaos_lines)
                    active_detail = " | ".join(chaos_lines[:2])
        elif pod_name:
            rule = run("exec", pod_name, "-n", namespace, "--", "tc", "qdisc", "show", "dev", "eth0",
                       context=aks_context)
            if rule.returncode == 0:
                active_detail = rule.stdout.strip().replace("\n", " ")[:80]
                active = kind[0] in rule.stdout and (not kind[1] or kind[1] in rule.stdout)

        retrans_now = dsack_now = None
        if experiment_id in {"aks-packet-loss", "aks-packet-corruption", "aks-packet-duplication"} and pod_name:
            snmp = run("exec", pod_name, "-n", namespace, "--", "cat", "/proc/net/snmp",
                       context=aks_context)
            if snmp.returncode == 0:
                retrans_now = _counter(snmp.stdout, "Tcp:", "RetransSegs")
            if experiment_id == "aks-packet-duplication":
                netstat = run("exec", pod_name, "-n", namespace, "--", "cat", "/proc/net/netstat",
                              context=aks_context)
                if netstat.returncode == 0:
                    dsack_now = _counter(netstat.stdout, "TcpExt:", "TCPDSACKRecv")

        running_pods = sum(1 for line in lines if len(line.split()) >= 3 and line.split()[2] == "Running")
        ready_pods = sum(
            1 for line in lines if len(line.split()) >= 2 and "/" in line.split()[1]
            and line.split()[1].split("/")[0] == line.split()[1].split("/")[-1]
        )
        not_ready = total - ready_pods
        endpoint_count = endpoint_total = None
        service_name, service_found = service_for(namespace, label_key, label_val, deployment, aks_context)
        if service_found:
            endpoints = run("get", "endpoints", service_name, "-n", namespace, "-o", "json",
                            context=aks_context)
            if endpoints.returncode == 0:
                try:
                    subsets = json.loads(endpoints.stdout).get("subsets") or []
                    endpoint_count = sum(len(item.get("addresses") or []) for item in subsets)
                    endpoint_total = endpoint_count + sum(
                        len(item.get("notReadyAddresses") or []) for item in subsets
                    )
                except ValueError:
                    pass

        events = run("get", "events", "-n", namespace, "--field-selector", "reason=Unhealthy",
                     "--no-headers", context=aks_context)
        unhealthy_count = len([line for line in events.stdout.strip().splitlines() if line.strip()]) \
            if events.returncode == 0 else 0
        restart_total = 0
        restarts = run("get", "pods", "-n", namespace, *selection_args, "-o", "json",
                       context=aks_context)
        if restarts.returncode == 0:
            try:
                restart_total = sum(
                    status.get("restartCount", 0)
                    for pod in json.loads(restarts.stdout).get("items", [])
                    for status in pod.get("status", {}).get("containerStatuses", [])
                )
            except ValueError:
                pass

        status_parts = [f"pods: {running_pods}/{total} Running  ready: {ready_pods}/{total}"]
        status_parts.append("NetworkChaos AllInjected=True" if crd_injected else "NetworkChaos: injection status unknown")
        if is_partition:
            if active:
                status_parts.append(f"iptables CHAOS chain ACTIVE ({active_detail})")
            elif pod_name:
                status_parts.append("iptables: chaos chain not detected (iptables may be unavailable in image — CRD status is authoritative)")
        elif active:
            status_parts.append(f"{kind[2]} {kind[3]} ({active_detail})")
        elif pod_name:
            missing = {
                "aks-network-delay": "tc-netem: not detected (tc may be unavailable in image)",
                "aks-packet-loss": "tc-netem: loss rule not detected (tc may be unavailable in image)",
                "aks-packet-corruption": "tc-netem corrupt: not detected (tc may be unavailable in image)",
                "aks-bandwidth-limit": "tc-tbf: not detected on eth0 (tc may be unavailable in image)",
                "aks-packet-duplication": "tc-netem: duplicate rule not detected (tc may be unavailable in image)",
            }
            status_parts.append(missing[experiment_id])

        if retrans_now is not None:
            retrans_detail = {
                "aks-packet-loss": "growing = packets being dropped and retransmitted",
                "aks-packet-corruption": "growing = corruption forcing retransmits",
                "aks-packet-duplication": "rising = dup-ACK fast retransmit active",
            }[experiment_id]
            status_parts.append(f"TCP RetransSegs={retrans_now} ({retrans_detail})")
        if dsack_now is not None:
            status_parts.append(f"TCPDSACKRecv={dsack_now} (rising = kernel receiving duplicate segments)")
        if endpoint_count is not None:
            endpoint_message = f"endpoints ready: {endpoint_count}"
            if is_partition and endpoint_count == 0:
                endpoint_message += " — all partitioned pods removed from Service routing (expected)"
            status_parts.append(endpoint_message)
        if is_partition and not_ready > 0:
            status_parts.append(f"✔ {not_ready} pod(s) NotReady — expected under full network partition")
        elif not_ready > 0:
            status_parts.append(_not_ready_message(experiment_id, not_ready))
        if unhealthy_count > 0:
            status_parts.append(_unhealthy_message(experiment_id, unhealthy_count))
        if restart_total > 0:
            status_parts.append(_restart_message(experiment_id, restart_total))

        if experiment_id == "aks-network-delay":
            dns = run("get", "service", "kube-dns", "-n", "kube-system",
                      "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
            rtt_ms = _ping_rtt(run, pod_name, namespace, aks_context, dns.stdout.strip()) if dns.returncode == 0 else None
        else:
            rtt_ms = None
        net_rows = _rows(experiment_id, retrans_now, dsack_now, endpoint_count, endpoint_total,
                         service_found, restart_total, unhealthy_count, not_ready, crd_injected,
                         active, rtt_ms, pod_name)
        severity = "CHAOS" if (active or crd_injected) else "WARNING"
        if session:
            session.log_event(severity, " | ".join(status_parts))
        return annotate({"severity": severity, "message": " | ".join(status_parts), "net_rows": net_rows},
                        lines, target_pod_names, restart_baseline)

    return probe


def _counter(output, prefix, name):
    lines = output.strip().splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.startswith(prefix):
            keys, values = line.split(), lines[index + 1].split()
            if name in keys:
                position = keys.index(name)
                return values[position] if position < len(values) else None
            return None
    return None


def _ping_rtt(run, pod_name, namespace, context, dns_ip):
    if not pod_name or not dns_ip:
        return None
    response = run("exec", pod_name, "-n", namespace, "--", "ping", "-c", "1", "-W", "2", dns_ip,
                   context=context)
    if response.returncode == 0:
        for line in response.stdout.splitlines():
            if "time=" in line:
                try:
                    return float(line.split("time=")[1].split()[0])
                except (IndexError, ValueError):
                    return None
    return None


def _not_ready_message(experiment_id, count):
    details = {
        "aks-network-delay": "removed from Service endpoints",
        "aks-packet-loss": "retransmit delays exceeding probe timeout",
        "aks-packet-corruption": "retransmit cascade exceeding probe timeout",
        "aks-bandwidth-limit": "probe response body too large for rate cap",
        "aks-packet-duplication": "dup-ACK fast-retransmit delay may have exceeded probe timeout",
    }
    return f"⚠ {count} pod(s) NotReady — {details[experiment_id]}"


def _unhealthy_message(experiment_id, count):
    details = {
        "aks-network-delay": " (readiness probes failing under delay)",
        "aks-packet-loss": "",
        "aks-packet-corruption": " (retransmit delays exceeding probe timeout)",
        "aks-bandwidth-limit": " (large-payload probe response throttled past timeout)",
        "aks-packet-duplication": "",
        "aks-network-partition": " — all probes failing under partition (expected)",
    }
    return f"Unhealthy probe events: {count}{details[experiment_id]}"


def _restart_message(experiment_id, count):
    details = {
        "aks-network-delay": "liveness probe may be timing out",
        "aks-packet-loss": "liveness probe killing containers — retransmit delay exceeded timeout",
        "aks-packet-corruption": "liveness kills from bit-corruption-induced retransmit delays",
        "aks-bandwidth-limit": "liveness kills — slow response body exceeded probe timeout under rate cap",
        "aks-packet-duplication": "liveness kills triggered by dup-ACK fast-retransmit delays",
        "aks-network-partition": "liveness kills triggered by partition",
    }
    return f"container restarts: {count} ({details[experiment_id]})"


def _rows(experiment_id, retrans, dsack, endpoint_count, endpoint_total, service_found,
          restarts, unhealthy, not_ready, injected, active, rtt, pod_name):
    endpoint = f"{endpoint_count} / {endpoint_total}" if endpoint_count is not None else (
        "N/A — no Service" if not service_found else "—"
    )
    rows = []
    if experiment_id == "aks-network-delay":
        if rtt is not None:
            rows.append(("Measured RTT (ping)", f"{rtt:.0f} ms", f"+{rtt - 1:.0f}ms vs ~1ms baseline" if rtt > 5 else "normal"))
        elif pod_name:
            rows.append(("Measured RTT (ping)", "unavailable", "ping not in container image"))
    if retrans is not None:
        details = {
            "aks-packet-loss": "↑ growing = TCP retransmitting dropped packets",
            "aks-packet-corruption": "↑ growing = corruption forcing retransmits",
            "aks-packet-duplication": "↑ rising = dup-ACK fast retransmit active",
        }
        rows.append(("TCP RetransSegs", retrans, details[experiment_id]))
    elif experiment_id in {"aks-packet-loss", "aks-packet-corruption", "aks-packet-duplication"}:
        rows.append(("TCP RetransSegs", "exec blocked by fault", "packet fault disrupted the measurement exec"))
    if experiment_id == "aks-packet-duplication":
        rows.append(("TCP DSACKRecv", dsack if dsack is not None else "exec blocked by fault",
                     "↑ rising = kernel receiving duplicate segments" if dsack is not None else "duplication disrupted the measurement exec"))
    rows.append(("Endpoints ready", endpoint,
                 "↓ partitioned pods removed from Service" if experiment_id == "aks-network-partition" and endpoint_count is not None and endpoint_total is not None and endpoint_count < endpoint_total else ""))
    if unhealthy > 0:
        rows.append(("Unhealthy probe events", str(unhealthy), _unhealthy_message(experiment_id, unhealthy).split(": ", 1)[1]))
    rows.append(("Container restarts", str(restarts), "" if restarts == 0 else "liveness kills"))
    rows.append(("NetworkChaos injected", "YES" if injected else "unknown", "AllInjected condition on CRD"))
    if experiment_id == "aks-network-partition" and active:
        rows.append(("iptables CHAOS chain", "ACTIVE", "Chaos Mesh iptables rule confirmed"))
    if experiment_id == "aks-bandwidth-limit":
        rows.append(("Throughput", "see post-check", "curl -m 10 too slow for live loop"))
    return rows
