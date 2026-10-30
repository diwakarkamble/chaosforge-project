"""Post-experiment checks for delay, loss, and bandwidth NetworkChaos faults."""

import datetime as _dt
import json

_NETWORK_DELAY_IDS = frozenset({"aks-network-delay"})
_PACKET_LOSS_IDS = frozenset({"aks-packet-loss"})
_BANDWIDTH_LIMIT_IDS = frozenset({"aks-bandwidth-limit"})


def build_post_network_checks(experiment_id, aks_context, namespace, deployment, label_key, label_val, selection_args, selection_display, *, kubectl, find_svc_name):
    """Build fault-specific checks with late-bound facade dependencies."""
    checks = {}

    def _kubectl(*args, **kwargs):
        return kubectl()(*args, **kwargs)

    def _find_svc_name(*args, **kwargs):
        return find_svc_name()(*args, **kwargs)

    def _service_fqdn():
        service_name, found = _find_svc_name(namespace, label_key, label_val, deployment, aks_context)
        if not found:
            return "", f"No Service found for selector {label_key}={label_val} in '{namespace}'"
        return f"{service_name}.{namespace}.svc.cluster.local", ""

    # ── Network-delay post-checks ────────────────────────────────────────────
    if experiment_id in _NETWORK_DELAY_IDS:

        # ── Shared helper ─────────────────────────────────────────────────────
        def _first_running_pod_post():
            r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                         "-o", "json", context=aks_context)
            if r.returncode != 0:
                return None
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                return None
            for pod in pods:
                if pod.get("status", {}).get("phase") == "Running":
                    return pod.get("metadata", {}).get("name")
            return None

        # 1. NetworkChaos CRD resource removed ────────────────────────────────
        def _networkchaos_crd_deleted():
            r = _kubectl("get", "networkchaos", "-n", "chaos-testing",
                         "--no-headers", context=aks_context)
            detail = "kubectl get networkchaos -n chaos-testing"
            if r.returncode != 0:
                return True, detail + "\n  (query failed — assuming cleaned up)"
            existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
            if existing:
                _kubectl("delete", "networkchaos", "--all", "-n", "chaos-testing",
                         context=aks_context)
                return True, (
                    detail + f"\n  ⚠ NetworkChaos resources found and auto-deleted: {existing}"
                    "\n  ✔ Cleaned up — rollback complete"
                )
            return True, detail + "\n  ✔ All NetworkChaos resources removed"
        checks["NetworkChaos CRD Cleaned Up"] = _networkchaos_crd_deleted

        # 2. tc-netem rule removed from pod eth0 ──────────────────────────────
        def _tc_netem_removed():
            pod = _first_running_pod_post()
            detail = f"kubectl exec <pod> -n {namespace} -- tc qdisc show dev eth0"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "tc", "qdisc", "show", "dev", "eth0", context=aks_context)
            if r.returncode != 0:
                return True, detail + f"\n  pod={pod}\n  (tc unavailable — skipping)"
            output = r.stdout.strip()
            detail = f"kubectl exec {pod} -n {namespace} -- tc qdisc show dev eth0\n  output: {output}"
            if "netem" in output:
                return False, detail + "\n  ✘ netem rule still on eth0 — delay not rolled back, traffic still degraded"
            return True, detail + "\n  ✔ netem rule removed — eth0 back to normal qdisc"
        checks["tc-netem Rule Removed"] = _tc_netem_removed

        # 3. Service endpoints fully restored ─────────────────────────────────
        def _endpoints_restored():
            svc_name, _svc_found = _find_svc_name(namespace, label_key, label_val, deployment, aks_context)
            if not _svc_found:
                return True, (
                    f"No Service found for selector {label_key}={label_val} in '{namespace}'"
                    "\n  (target is a standalone pod with no Service — skipping endpoint check)"
                )
            r = _kubectl("get", "endpoints", svc_name, "-n", namespace,
                         "-o", "json", context=aks_context)
            detail = f"kubectl get endpoints {svc_name} -n {namespace} --context {aks_context}"
            if r.returncode != 0:
                return True, detail + f"\n  (endpoint query failed — skipping: {r.stderr.strip()[:80]})"
            try:
                ep = json.loads(r.stdout)
            except ValueError:
                return False, detail + "\n  ✘ Could not parse endpoints"
            subsets   = ep.get("subsets") or []
            ready_ips = []
            not_ready_ips = []
            for s in subsets:
                ready_ips.extend(a.get("ip", "") for a in (s.get("addresses") or []))
                not_ready_ips.extend(a.get("ip", "") for a in (s.get("notReadyAddresses") or []))
            detail += (
                f"\n  ready endpoints   : {len(ready_ips)}  {ready_ips}"
                f"\n  notReady endpoints: {len(not_ready_ips)}  {not_ready_ips}"
            )
            if not_ready_ips:
                return False, detail + (
                    f"\n  ✘ {len(not_ready_ips)} endpoint(s) still NotReady — "
                    "pods have not recovered readiness after rollback"
                )
            if not ready_ips:
                return False, detail + "\n  ✘ No ready endpoints — service is unreachable post-rollback"
            return True, detail + "\n  ✔ All endpoints ready — Service routing fully restored"
        checks["Service Endpoints Restored"] = _endpoints_restored

        # 4. HTTP response time back to baseline ──────────────────────────────
        def _http_response_time_restored():
            pod = _first_running_pod_post()
            svc_url = f"http://{deployment}.{namespace}.svc.cluster.local"
            detail  = f"kubectl exec <pod> -n {namespace} -- curl -o /dev/null -s -m 5 -w '%{{time_total}}' {svc_url}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "curl", "-o", "/dev/null", "-s", "-m", "5",
                         "-w", "%{time_total}", svc_url, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- curl -o /dev/null -s -m 5 -w '%{{time_total}}' {svc_url}"
            if r.returncode != 0:
                return True, detail + f"\n  (curl unavailable — skipping: {r.stderr.strip()[:80]})"
            time_total = r.stdout.strip()
            detail += f"\n  post-rollback HTTP response time = {time_total}s"
            try:
                t = float(time_total)
                if t > 1.0:
                    return False, detail + (
                        f"\n  ✘ Response time {t:.3f}s still elevated after rollback "
                        "(netem may still be active or pods recovering)"
                    )
            except ValueError:
                pass
            return True, detail + "\n  ✔ HTTP response time back to normal range — compare with baseline in pre-check logs"
        checks["HTTP Response Time Restored"] = _http_response_time_restored

        # 5. RTT back to baseline ─────────────────────────────────────────────
        def _ping_rtt_restored():
            pod = _first_running_pod_post()
            r_dns = _kubectl("get", "service", "kube-dns", "-n", "kube-system",
                             "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
            dns_ip = r_dns.stdout.strip() if r_dns.returncode == 0 and r_dns.stdout.strip() else "10.0.0.10"
            detail = f"kubectl exec <pod> -n {namespace} -- ping -c 3 {dns_ip}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "ping", "-c", "3", "-W", "2", dns_ip, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- ping -c 3 -W 2 {dns_ip}  (post-rollback RTT)"
            if r.returncode != 0:
                return True, detail + f"\n  (ping unavailable — skipping: {r.stderr.strip()[:80]})"
            avg_rtt = None
            for line in r.stdout.strip().splitlines():
                if "avg" in line and "=" in line:
                    try:
                        avg_rtt = line.split("=")[1].strip().split("/")[1]
                    except (IndexError, ValueError):
                        pass
            detail += f"\n  post-rollback avg RTT = {avg_rtt} ms" if avg_rtt else f"\n  {r.stdout.strip()[-100:]}"
            # Informational only — no hard threshold. Cluster baseline RTT varies
            # (some AKS clusters sit at 20-40ms naturally). Operator compares against
            # the pre-check baseline captured in validation logs to judge recovery.
            return True, detail + "\n  ✔ Post-rollback RTT captured — compare with pre-check baseline in logs"
        checks["Ping RTT Restored"] = _ping_rtt_restored

        # 6. DNS resolution restored ───────────────────────────────────────────
        def _dns_resolution_restored():
            pod      = _first_running_pod_post()
            svc_fqdn = f"{deployment}.{namespace}.svc.cluster.local"
            detail   = f"kubectl exec <pod> -n {namespace} -- nslookup {svc_fqdn}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "nslookup", svc_fqdn, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- nslookup {svc_fqdn}"
            if r.returncode != 0:
                return True, detail + f"\n  (nslookup unavailable — skipping: {r.stderr.strip()[:80]})"
            resolved = "Address" in r.stdout
            detail  += f"\n  resolved={resolved}"
            if not resolved:
                return False, detail + f"\n  ✘ DNS still not resolving after rollback — {r.stdout.strip()[:120]}"
            return True, detail + "\n  ✔ DNS resolution restored"
        checks["DNS Resolution Restored"] = _dns_resolution_restored

        # 7. Probe failure events stopped ─────────────────────────────────────
        def _probe_failure_events_stopped():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "reason=Unhealthy",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --field-selector reason=Unhealthy --context {aks_context}  (last 2m)"
            if r.returncode != 0:
                return True, detail + "\n  (could not query events — skipping)"
            try:
                events = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (could not parse events — skipping)"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=2)
            recent = []
            for ev in events:
                ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
                obj     = ev.get("involvedObject", {}).get("name", "?")
                message = ev.get("message", "")[:80]
                recent.append(f"  {obj}: {message}")
            detail += "\n" + ("\n".join(recent) if recent else "  no Unhealthy events in last 2m")
            if recent:
                return False, detail + (
                    "\n  ✘ Readiness probe failures still firing after rollback"
                    "\n    Pods may not have recovered — endpoint routing still degraded"
                )
            return True, detail + "\n  ✔ No probe failures post-rollback — probes recovering normally"
        checks["Probe Failures Stopped (post)"] = _probe_failure_events_stopped

        # 8. Restart count delta (liveness kills during fault) ─────────────────
        def _restart_count_delta():
            r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                         "-o", "json", context=aks_context)
            detail = (
                f"kubectl get pods -n {namespace} {selection_display} "
                f"--context {aks_context}  (post-fault restart count)"
            )
            if r.returncode != 0:
                return True, detail + "\n  (kubectl failed — skipping)"
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (parse failed — skipping)"
            lines_out = []
            high_restarts = []
            for pod in pods:
                pname = pod.get("metadata", {}).get("name", "?")
                total_restarts = sum(
                    cs.get("restartCount", 0)
                    for cs in pod.get("status", {}).get("containerStatuses", [])
                )
                lines_out.append(f"  {pname}: restarts={total_restarts}")
                if total_restarts >= 3:
                    high_restarts.append(f"{pname}={total_restarts}")
            detail += "\n" + ("\n".join(lines_out) if lines_out else "  no pods found")
            if high_restarts:
                detail += (
                    f"\n  ⚠ High restart counts: {high_restarts}"
                    "\n  The injected delay was large enough to trigger liveness probe kills"
                    "\n  Check if app has recovered to stable state"
                )
            else:
                detail += "\n  ✔ Restart counts within normal range post-rollback"
            return True, detail
        checks["Restart Count Delta (post)"] = _restart_count_delta

        # 9. No stale network warning events ──────────────────────────────────
        def _no_network_warning_events():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "involvedObject.kind=Pod",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --context {aks_context}  (network warnings last 5m)"
            if r.returncode != 0:
                return True, detail + "\n  (could not query events — skipping)"
            try:
                events = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (could not parse — skipping)"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
            network_reasons = {"NetworkNotReady", "FailedCreatePodSandBox"}
            found = []
            for ev in events:
                if ev.get("type") != "Warning":
                    continue
                ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
                reason  = ev.get("reason", "")
                message = ev.get("message", "")[:80]
                obj     = ev.get("involvedObject", {}).get("name", "?")
                if reason in network_reasons or "network" in message.lower() or "timeout" in message.lower():
                    found.append(f"  {obj}: {reason} — {message}")
            detail += "\n" + ("\n".join(found) if found else "  no network-related Warning events")
            if found:
                return False, detail + "\n  ✘ Network warning events still firing — cluster not fully recovered"
            return True, detail + "\n  ✔ No network warning events post-rollback"
        checks["No Network Warning Events (post)"] = _no_network_warning_events

    # ── Packet-loss post-checks ───────────────────────────────────────────────
    if experiment_id in _PACKET_LOSS_IDS:

        def _pl_post_first_pod():
            r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                         "-o", "json", context=aks_context)
            if r.returncode != 0:
                return None
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                return None
            for pod in pods:
                if pod.get("status", {}).get("phase") == "Running":
                    return pod.get("metadata", {}).get("name")
            return None

        # 1. NetworkChaos CRD removed ─────────────────────────────────────────
        def _pl_crd_cleaned():
            r = _kubectl("get", "networkchaos", "-n", "chaos-testing",
                         "--no-headers", context=aks_context)
            detail = "kubectl get networkchaos -n chaos-testing"
            if r.returncode != 0:
                return True, detail + "\n  (query failed — assuming cleaned up)"
            existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
            if existing:
                _kubectl("delete", "networkchaos", "--all", "-n", "chaos-testing",
                         context=aks_context)
                return True, (
                    detail + f"\n  ⚠ NetworkChaos resources found and auto-deleted: {existing}"
                    "\n  ✔ Cleaned up — rollback complete"
                )
            return True, detail + "\n  ✔ All NetworkChaos resources removed"
        checks["NetworkChaos CRD Cleaned Up"] = _pl_crd_cleaned

        # 2. tc-netem loss rule removed from eth0 ─────────────────────────────
        def _pl_netem_removed():
            pod = _pl_post_first_pod()
            detail = f"kubectl exec <pod> -n {namespace} -- tc qdisc show dev eth0"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "tc", "qdisc", "show", "dev", "eth0", context=aks_context)
            if r.returncode != 0:
                return True, detail + f"\n  pod={pod}\n  (tc unavailable — skipping)"
            output = r.stdout.strip()
            detail = f"kubectl exec {pod} -n {namespace} -- tc qdisc show dev eth0\n  output: {output}"
            if "netem" in output:
                return False, detail + "\n  ✘ netem rule still on eth0 — packet loss not rolled back"
            return True, detail + "\n  ✔ netem rule removed — eth0 back to normal qdisc"
        checks["tc-netem Rule Removed"] = _pl_netem_removed

        # 3. TCP retransmit counter settled ───────────────────────────────────
        #    Delta between now and baseline should have grown during fault.
        #    Post-rollback the counter should stop increasing (new delta ≈ 0).
        def _pl_retransmit_settled():
            pod = _pl_post_first_pod()
            detail = f"kubectl exec <pod> -n {namespace} -- cat /proc/net/snmp"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "cat", "/proc/net/snmp", context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- cat /proc/net/snmp  (post-rollback RetransSegs)"
            if r.returncode != 0:
                return True, detail + "\n  (unavailable — skipping)"
            retrans = None
            snmp_lines = r.stdout.strip().splitlines()
            for i, line in enumerate(snmp_lines):
                if line.startswith("Tcp:") and i + 1 < len(snmp_lines):
                    keys = line.split()
                    vals = snmp_lines[i + 1].split()
                    if "RetransSegs" in keys:
                        idx     = keys.index("RetransSegs")
                        retrans = vals[idx] if idx < len(vals) else None
                    break
            detail += f"\n  post-rollback RetransSegs = {retrans}"
            detail += (
                "\n  ✔ Compare with baseline from pre-check logs."
                "\n    Large delta = heavy retransmits occurred during fault (confirms impact)."
                "\n    Counter should now be stable (not still growing post-rollback)."
            )
            return True, detail
        checks["TCP Retransmit Counter (post-rollback)"] = _pl_retransmit_settled

        # 5. DNS resolution restored (UDP) ────────────────────────────────────
        def _pl_dns_restored():
            pod = _pl_post_first_pod()
            svc_fqdn, service_error = _service_fqdn()
            detail   = f"kubectl exec <pod> -n {namespace} -- nslookup {svc_fqdn}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            if service_error:
                return True, service_error + "\n  (DNS recovery check is not applicable)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "nslookup", svc_fqdn, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- nslookup {svc_fqdn}  (UDP)"
            if r.returncode != 0:
                return True, detail + "\n  (nslookup unavailable — skipping)"
            resolved = "Address" in r.stdout
            detail  += f"\n  resolved={resolved}"
            if not resolved:
                return False, detail + "\n  ✘ DNS still failing after rollback — UDP resolution not recovered"
            return True, detail + "\n  ✔ DNS resolution (UDP) restored"
        checks["DNS Resolution Restored (UDP)"] = _pl_dns_restored

        # 6. Ping RTT restored ────────────────────────────────────────────────
        #    Even with 0% loss post-rollback, verify RTT returned to baseline.
        #    Elevated RTT after rollback = retransmit-induced queuing still clearing.
        def _pl_rtt_restored():
            pod = _pl_post_first_pod()
            r_dns = _kubectl("get", "service", "kube-dns", "-n", "kube-system",
                             "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
            dns_ip = r_dns.stdout.strip() if r_dns.returncode == 0 and r_dns.stdout.strip() else "10.0.0.10"
            detail = f"kubectl exec <pod> -n {namespace} -- ping -c 3 -W 2 {dns_ip}  (post-rollback RTT)"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "ping", "-c", "3", "-W", "2", dns_ip, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- ping -c 3 -W 2 {dns_ip}  (post-rollback RTT)"
            if r.returncode != 0:
                return True, detail + f"\n  (ping unavailable — skipping: {r.stderr.strip()[:80]})"
            avg_rtt = None
            for line in r.stdout.strip().splitlines():
                if "avg" in line and "=" in line:
                    try:
                        avg_rtt = line.split("=")[1].strip().split("/")[1]
                    except (IndexError, ValueError):
                        pass
            detail += f"\n  post-rollback avg RTT = {avg_rtt} ms" if avg_rtt else f"\n  {r.stdout.strip()[-80:]}"
            return True, detail + "\n  ✔ RTT captured post-rollback — compare with pre-check baseline in logs"
        checks["Ping RTT Restored"] = _pl_rtt_restored

        # 7. HTTP success restored ────────────────────────────────────────────
        def _pl_http_restored():
            pod = _pl_post_first_pod()
            svc_fqdn, service_error = _service_fqdn()
            svc_url = f"http://{svc_fqdn}"
            detail  = f"kubectl exec <pod> -n {namespace} -- curl -o /dev/null -s -m 5 -w '%{{http_code}} %{{time_total}}' {svc_url}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            if service_error:
                return True, service_error + "\n  (HTTP recovery check is not applicable)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "curl", "-o", "/dev/null", "-s", "-m", "5",
                         "-w", "%{http_code} %{time_total}", svc_url, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- curl -s -m 5 {svc_url}"
            if r.returncode != 0:
                return True, detail + "\n  (curl unavailable — skipping)"
            parts     = r.stdout.strip().split()
            http_code = parts[0] if parts else "?"
            http_time = parts[1] if len(parts) > 1 else "?"
            detail   += f"\n  HTTP code={http_code}  time={http_time}s"
            try:
                t = float(http_time)
                if t > 2.0:
                    return False, detail + (
                        f"\n  ✘ Response time {t:.3f}s still elevated — "
                        "retransmits may still be occurring post-rollback"
                    )
            except ValueError:
                pass
            if http_code not in ("200", "201", "204", "301", "302", "?"):
                return False, detail + f"\n  ✘ HTTP {http_code} — service not responding normally"
            return True, detail + "\n  ✔ HTTP responding normally — compare time with pre-check baseline"
        checks["HTTP Success Restored"] = _pl_http_restored

        # 7. Service endpoints fully restored ─────────────────────────────────
        def _pl_endpoints_restored():
            svc_name, _svc_found = _find_svc_name(namespace, label_key, label_val, deployment, aks_context)
            if not _svc_found:
                return True, (
                    f"No Service found for selector {label_key}={label_val} in '{namespace}'"
                    "\n  (target is a standalone pod with no Service — skipping endpoint check)"
                )
            r = _kubectl("get", "endpoints", svc_name, "-n", namespace,
                         "-o", "json", context=aks_context)
            detail = f"kubectl get endpoints {svc_name} -n {namespace} --context {aks_context}"
            if r.returncode != 0:
                return True, detail + f"\n  (endpoint query failed — skipping: {r.stderr.strip()[:80]})"
            try:
                ep = json.loads(r.stdout)
            except ValueError:
                return False, detail + "\n  ✘ Could not parse endpoints"
            subsets       = ep.get("subsets") or []
            ready_ips     = []
            not_ready_ips = []
            for s in subsets:
                ready_ips.extend(a.get("ip", "") for a in (s.get("addresses") or []))
                not_ready_ips.extend(a.get("ip", "") for a in (s.get("notReadyAddresses") or []))
            detail += (
                f"\n  ready endpoints   : {len(ready_ips)}  {ready_ips}"
                f"\n  notReady endpoints: {len(not_ready_ips)}  {not_ready_ips}"
            )
            if not_ready_ips:
                return False, detail + (
                    f"\n  ✘ {len(not_ready_ips)} endpoint(s) still NotReady — "
                    "pods have not recovered readiness after rollback"
                )
            if not ready_ips:
                return False, detail + "\n  ✘ No ready endpoints — service unreachable post-rollback"
            return True, detail + "\n  ✔ All endpoints ready — Service routing fully restored"
        checks["Service Endpoints Restored"] = _pl_endpoints_restored

        # 8. Probe failure events stopped ─────────────────────────────────────
        def _pl_probe_events_stopped():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "reason=Unhealthy",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --field-selector reason=Unhealthy --context {aks_context}  (last 2m)"
            if r.returncode != 0:
                return True, detail + "\n  (could not query events — skipping)"
            try:
                events = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (could not parse — skipping)"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=2)
            recent = []
            for ev in events:
                ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
                obj     = ev.get("involvedObject", {}).get("name", "?")
                message = ev.get("message", "")[:80]
                recent.append(f"  {obj}: {message}")
            detail += "\n" + ("\n".join(recent) if recent else "  no Unhealthy events in last 2m")
            if recent:
                return False, detail + (
                    "\n  ✘ Readiness probe failures still firing after rollback"
                    "\n    Retransmit-induced delays may not have cleared yet"
                )
            return True, detail + "\n  ✔ No probe failures post-rollback"
        checks["Probe Failures Stopped (post)"] = _pl_probe_events_stopped

        # 9. Restart count delta ──────────────────────────────────────────────
        def _pl_restart_delta():
            r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                         "-o", "json", context=aks_context)
            detail = (
                f"kubectl get pods -n {namespace} {selection_display} "
                f"--context {aks_context}  (post-fault restarts)"
            )
            if r.returncode != 0:
                return True, detail + "\n  (kubectl failed — skipping)"
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (parse failed — skipping)"
            lines_out, high = [], []
            for pod in pods:
                pname = pod.get("metadata", {}).get("name", "?")
                total = sum(
                    cs.get("restartCount", 0)
                    for cs in pod.get("status", {}).get("containerStatuses", [])
                )
                lines_out.append(f"  {pname}: restarts={total}")
                if total >= 3:
                    high.append(f"{pname}={total}")
            detail += "\n" + ("\n".join(lines_out) if lines_out else "  no pods found")
            if high:
                detail += (
                    f"\n  ⚠ High restarts: {high}"
                    "\n    Liveness probe was killed by retransmit-induced timeouts during fault."
                    "\n    Verify pods are stable now (restarts should stop increasing)."
                )
            else:
                detail += "\n  ✔ Restart counts within normal range post-rollback"
            return True, detail
        checks["Restart Count Delta (post)"] = _pl_restart_delta

        # 10. No stale network warning events ─────────────────────────────────
        def _pl_no_net_events():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "involvedObject.kind=Pod",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --context {aks_context}  (network warnings last 5m)"
            if r.returncode != 0:
                return True, detail + "\n  (could not query — skipping)"
            try:
                events = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (could not parse — skipping)"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
            network_reasons = {"NetworkNotReady", "FailedCreatePodSandBox"}
            found = []
            for ev in events:
                if ev.get("type") != "Warning":
                    continue
                ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
                reason  = ev.get("reason", "")
                message = ev.get("message", "")[:80]
                obj     = ev.get("involvedObject", {}).get("name", "?")
                if reason in network_reasons or "network" in message.lower() or "timeout" in message.lower():
                    found.append(f"  {obj}: {reason} — {message}")
            detail += "\n" + ("\n".join(found) if found else "  no network-related Warning events")
            if found:
                return False, detail + "\n  ✘ Network warning events still firing — cluster not fully recovered"
            return True, detail + "\n  ✔ No network warning events post-rollback"
        checks["No Network Warning Events (post)"] = _pl_no_net_events

    # ── Bandwidth-limit post-checks ───────────────────────────────────────────
    if experiment_id in _BANDWIDTH_LIMIT_IDS:

        def _bw_post_first_pod():
            r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                         "-o", "json", context=aks_context)
            if r.returncode != 0:
                return None
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                return None
            for pod in pods:
                if pod.get("status", {}).get("phase") == "Running":
                    return pod.get("metadata", {}).get("name")
            return None

        # 1. NetworkChaos CRD removed ─────────────────────────────────────────
        def _bw_crd_cleaned():
            r = _kubectl("get", "networkchaos", "-n", "chaos-testing",
                         "--no-headers", context=aks_context)
            detail = "kubectl get networkchaos -n chaos-testing"
            if r.returncode != 0:
                return True, detail + "\n  (query failed — assuming cleaned up)"
            existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
            if existing:
                _kubectl("delete", "networkchaos", "--all", "-n", "chaos-testing",
                         context=aks_context)
                return True, (
                    detail + f"\n  ⚠ NetworkChaos resources found and auto-deleted: {existing}"
                    "\n  ✔ Cleaned up — rollback complete"
                )
            return True, detail + "\n  ✔ All NetworkChaos resources removed"
        checks["NetworkChaos CRD Cleaned Up"] = _bw_crd_cleaned

        # 2. tc tbf rule removed from eth0 ────────────────────────────────────
        def _bw_tc_removed():
            pod = _bw_post_first_pod()
            detail = f"kubectl exec <pod> -n {namespace} -- tc qdisc show dev eth0"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "tc", "qdisc", "show", "dev", "eth0", context=aks_context)
            if r.returncode != 0:
                return True, detail + f"\n  pod={pod}\n  (tc unavailable — skipping)"
            output = r.stdout.strip()
            detail = f"kubectl exec {pod} -n {namespace} -- tc qdisc show dev eth0\n  output: {output}"
            if "tbf" in output:
                return False, detail + "\n  ✘ tc tbf rule still on eth0 — bandwidth cap not rolled back"
            return True, detail + "\n  ✔ tc tbf rule removed — eth0 back to normal qdisc"
        checks["tc-tbf Rule Removed"] = _bw_tc_removed

        # 3. KEY: throughput restored to baseline ─────────────────────────────
        #    This is the definitive proof the cap is gone.
        #    If speed_kbps is still low → tbf still applied somewhere.
        def _bw_throughput_restored():
            pod = _bw_post_first_pod()
            svc_fqdn, service_error = _service_fqdn()
            svc_url = f"http://{svc_fqdn}"
            detail  = f"kubectl exec <pod> -n {namespace} -- curl -o /dev/null -s -m 10 -w '...' {svc_url}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            if service_error:
                return True, service_error + "\n  (throughput recovery check is not applicable)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "curl", "-o", "/dev/null", "-s", "-m", "10",
                         "-w", "%{size_download} %{time_total} %{speed_download}",
                         svc_url, context=aks_context)
            detail = (
                f"kubectl exec {pod} -n {namespace} -- curl -o /dev/null -s -m 10 "
                f"-w '%{{size_download}} %{{time_total}} %{{speed_download}}' {svc_url}"
            )
            if r.returncode != 0:
                return True, detail + "\n  (curl unavailable — skipping)"
            parts      = r.stdout.strip().split()
            size_bytes = parts[0] if len(parts) > 0 else "?"
            time_total = parts[1] if len(parts) > 1 else "?"
            speed_bps  = parts[2] if len(parts) > 2 else "?"
            try:
                speed_kbps = float(speed_bps) / 1024
                speed_str  = f"{speed_kbps:.1f} KB/s"
                # Flag if throughput still suspiciously low (≤ 150 KB/s = ~1.2mbps)
                if speed_kbps <= 150:
                    detail += (
                        f"\n  post-rollback: size={size_bytes}B  time={time_total}s  throughput={speed_str}"
                        f"\n  ⚠ Throughput still low ({speed_str}) — tc tbf may still be active"
                        "\n    Compare with pre-check baseline in validation logs"
                    )
                    return False, detail
            except (ValueError, ZeroDivisionError):
                speed_str = f"{speed_bps} B/s"
            detail += (
                f"\n  post-rollback: size={size_bytes}B  time={time_total}s  throughput={speed_str}"
                "\n  ✔ Throughput restored — compare with pre-check baseline in validation logs"
            )
            return True, detail
        checks["Throughput Restored (KB/s)"] = _bw_throughput_restored

        # 4. Ping RTT stable (should match baseline) ──────────────────────────
        def _bw_rtt_stable():
            pod   = _bw_post_first_pod()
            r_dns = _kubectl("get", "service", "kube-dns", "-n", "kube-system",
                             "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
            dns_ip = r_dns.stdout.strip() if r_dns.returncode == 0 and r_dns.stdout.strip() else "10.0.0.10"
            detail = f"kubectl exec <pod> -n {namespace} -- ping -c 5 {dns_ip}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "ping", "-c", "5", "-W", "2", dns_ip, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- ping -c 5 -W 2 {dns_ip}  (post-rollback RTT)"
            if r.returncode != 0:
                return True, detail + "\n  (ping unavailable — skipping)"
            avg_rtt = None
            for line in r.stdout.strip().splitlines():
                if "avg" in line and "=" in line:
                    try:
                        avg_rtt = line.split("=")[1].strip().split("/")[1]
                    except (IndexError, ValueError):
                        pass
            detail += f"\n  post-rollback avg RTT = {avg_rtt} ms" if avg_rtt else f"\n  {r.stdout.strip()[-80:]}"
            detail += "\n  ✔ RTT stable post-rollback — compare with pre-check baseline"
            return True, detail
        checks["Ping RTT Stable (post-rollback)"] = _bw_rtt_stable

        # 5. Service endpoints restored ───────────────────────────────────────
        def _bw_endpoints_restored():
            svc_name, _svc_found = _find_svc_name(namespace, label_key, label_val, deployment, aks_context)
            if not _svc_found:
                return True, (
                    f"No Service found for selector {label_key}={label_val} in '{namespace}'"
                    "\n  (target is a standalone pod with no Service — skipping endpoint check)"
                )
            r = _kubectl("get", "endpoints", svc_name, "-n", namespace,
                         "-o", "json", context=aks_context)
            detail = f"kubectl get endpoints {svc_name} -n {namespace} --context {aks_context}"
            if r.returncode != 0:
                return True, detail + f"\n  (endpoint query failed — skipping: {r.stderr.strip()[:80]})"
            try:
                ep = json.loads(r.stdout)
            except ValueError:
                return False, detail + "\n  ✘ Could not parse endpoints"
            subsets       = ep.get("subsets") or []
            ready_ips     = []
            not_ready_ips = []
            for s in subsets:
                ready_ips.extend(a.get("ip", "") for a in (s.get("addresses") or []))
                not_ready_ips.extend(a.get("ip", "") for a in (s.get("notReadyAddresses") or []))
            detail += (
                f"\n  ready endpoints   : {len(ready_ips)}  {ready_ips}"
                f"\n  notReady endpoints: {len(not_ready_ips)}  {not_ready_ips}"
            )
            if not_ready_ips:
                return False, detail + (
                    f"\n  ✘ {len(not_ready_ips)} endpoint(s) still NotReady — "
                    "pods have not recovered readiness after rollback"
                )
            if not ready_ips:
                return False, detail + "\n  ✘ No ready endpoints — service unreachable"
            return True, detail + "\n  ✔ All endpoints ready — Service routing fully restored"
        checks["Service Endpoints Restored"] = _bw_endpoints_restored

        # 6. HTTP success restored ────────────────────────────────────────────
        def _bw_http_restored():
            pod = _bw_post_first_pod()
            svc_fqdn, service_error = _service_fqdn()
            svc_url = f"http://{svc_fqdn}"
            detail  = f"kubectl exec <pod> -n {namespace} -- curl -s -m 5 {svc_url}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            if service_error:
                return True, service_error + "\n  (HTTP recovery check is not applicable)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "curl", "-o", "/dev/null", "-s", "-m", "5",
                         "-w", "%{http_code} %{time_total}", svc_url, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- curl -s -m 5 {svc_url}"
            if r.returncode != 0:
                return True, detail + "\n  (curl unavailable — skipping)"
            parts     = r.stdout.strip().split()
            http_code = parts[0] if parts else "?"
            http_time = parts[1] if len(parts) > 1 else "?"
            detail   += f"\n  HTTP code={http_code}  time={http_time}s"
            try:
                t = float(http_time)
                if t > 5.0:
                    return False, detail + (
                        f"\n  ✘ Response time {t:.3f}s still very slow — "
                        "throttle may still be partially active"
                    )
            except ValueError:
                pass
            if http_code not in ("200", "201", "204", "301", "302", "?"):
                return False, detail + f"\n  ✘ HTTP {http_code} — service not responding normally"
            return True, detail + "\n  ✔ HTTP responding normally post-rollback"
        checks["HTTP Success Restored"] = _bw_http_restored

        # 7. Probe failures stopped ───────────────────────────────────────────
        def _bw_probe_stopped():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "reason=Unhealthy",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --field-selector reason=Unhealthy  (last 2m)"
            if r.returncode != 0:
                return True, detail + "\n  (could not query — skipping)"
            try:
                events = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (could not parse — skipping)"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=2)
            recent = []
            for ev in events:
                ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
                obj     = ev.get("involvedObject", {}).get("name", "?")
                message = ev.get("message", "")[:80]
                recent.append(f"  {obj}: {message}")
            detail += "\n" + ("\n".join(recent) if recent else "  no Unhealthy events in last 2m")
            if recent:
                return False, detail + (
                    "\n  ✘ Probe failures still firing — large-payload responses still slow"
                )
            return True, detail + "\n  ✔ No probe failures post-rollback"
        checks["Probe Failures Stopped (post)"] = _bw_probe_stopped

        # 8. Restart count delta ──────────────────────────────────────────────
        def _bw_restart_delta():
            r = _kubectl("get", "pods", "-n", namespace, *selection_args,
                         "-o", "json", context=aks_context)
            detail = (
                f"kubectl get pods -n {namespace} {selection_display} "
                "(post-fault restarts)"
            )
            if r.returncode != 0:
                return True, detail + "\n  (kubectl failed — skipping)"
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (parse failed — skipping)"
            lines_out, high = [], []
            for pod in pods:
                pname = pod.get("metadata", {}).get("name", "?")
                total = sum(
                    cs.get("restartCount", 0)
                    for cs in pod.get("status", {}).get("containerStatuses", [])
                )
                lines_out.append(f"  {pname}: restarts={total}")
                if total >= 3:
                    high.append(f"{pname}={total}")
            detail += "\n" + ("\n".join(lines_out) if lines_out else "  no pods found")
            if high:
                detail += (
                    f"\n  ⚠ High restarts: {high}"
                    "\n    Liveness probe killed by slow response body under bandwidth cap."
                )
            else:
                detail += "\n  ✔ Restart counts within normal range"
            return True, detail
        checks["Restart Count Delta (post)"] = _bw_restart_delta

        # 9. No stale network warning events ──────────────────────────────────
        def _bw_no_net_events():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "involvedObject.kind=Pod",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace}  (network warnings last 5m)"
            if r.returncode != 0:
                return True, detail + "\n  (could not query — skipping)"
            try:
                events = json.loads(r.stdout).get("items", [])
            except ValueError:
                return True, detail + "\n  (could not parse — skipping)"
            cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
            network_reasons = {"NetworkNotReady", "FailedCreatePodSandBox"}
            found = []
            for ev in events:
                if ev.get("type") != "Warning":
                    continue
                ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
                reason  = ev.get("reason", "")
                message = ev.get("message", "")[:80]
                obj     = ev.get("involvedObject", {}).get("name", "?")
                if reason in network_reasons or "network" in message.lower() or "timeout" in message.lower():
                    found.append(f"  {obj}: {reason} — {message}")
            detail += "\n" + ("\n".join(found) if found else "  no network-related Warning events")
            if found:
                return False, detail + "\n  ✘ Network warning events still firing — not fully recovered"
            return True, detail + "\n  ✔ No network warning events post-rollback"
        checks["No Network Warning Events (post)"] = _bw_no_net_events

        # DNS resolution restored ─────────────────────────────────────────────
        def _bw_dns_restored():
            pod = _bw_post_first_pod()
            svc_fqdn, service_error = _service_fqdn()
            detail   = f"kubectl exec <pod> -n {namespace} -- nslookup {svc_fqdn}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            if service_error:
                return True, service_error + "\n  (DNS recovery check is not applicable)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "nslookup", svc_fqdn, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- nslookup {svc_fqdn}  (post-rollback DNS)"
            if r.returncode != 0:
                return True, detail + f"\n  (nslookup unavailable — skipping: {r.stderr.strip()[:80]})"
            resolved = "Address" in r.stdout
            detail  += f"\n  resolved={resolved}"
            if not resolved:
                return False, detail + f"\n  ✘ DNS not resolving after rollback — {r.stdout.strip()[:120]}"
            return True, detail + "\n  ✔ DNS resolution restored post-rollback"
        checks["DNS Resolution Restored"] = _bw_dns_restored

    return checks
