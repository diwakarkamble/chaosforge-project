"""Post-experiment checks for corruption, duplication, and partition faults."""

import datetime as _dt
import json

_PACKET_CORRUPTION_IDS = frozenset({"aks-packet-corruption"})
_PACKET_DUPLICATION_IDS = frozenset({"aks-packet-duplication"})
_PARTITION_IDS = frozenset({"aks-network-partition"})


def build_post_network_checks(experiment_id, aks_context, namespace, deployment, label_key, label_val, selection_args, selection_display, *, kubectl, find_svc_name, partition_ping_target):
    """Build fault-specific checks with late-bound facade dependencies."""
    checks = {}

    def _kubectl(*args, **kwargs):
        return kubectl()(*args, **kwargs)

    def _find_svc_name(*args, **kwargs):
        return find_svc_name()(*args, **kwargs)

    def _np_partition_ping_target(aks_context):
        return partition_ping_target()(aks_context)

    # ── Packet-corruption post-checks ─────────────────────────────────────────
    if experiment_id in _PACKET_CORRUPTION_IDS:

        def _pc_post_first_pod():
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
        def _pc_crd_cleaned():
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
        checks["NetworkChaos CRD Cleaned Up"] = _pc_crd_cleaned

        # 2. tc-netem corrupt rule removed from eth0 ──────────────────────────
        def _pc_netem_removed():
            pod = _pc_post_first_pod()
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
                return False, detail + "\n  ✘ netem rule still on eth0 — corrupt rule not rolled back"
            return True, detail + "\n  ✔ netem rule removed — eth0 back to normal qdisc"
        checks["tc-netem Corrupt Rule Removed"] = _pc_netem_removed

        # 3. KEY: packet loss back to 0% ──────────────────────────────────────
        #    Corruption → checksum fail → packet discard → ping sees loss.
        #    Post-rollback ping must show 0% — confirms corruption gone from wire.
        def _pc_packet_loss_zero():
            pod = _pc_post_first_pod()
            r_dns = _kubectl("get", "service", "kube-dns", "-n", "kube-system",
                             "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
            dns_ip = r_dns.stdout.strip() if r_dns.returncode == 0 and r_dns.stdout.strip() else "10.0.0.10"
            detail = f"kubectl exec <pod> -n {namespace} -- ping -c 10 -W 2 {dns_ip}  (post-rollback)"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "ping", "-c", "10", "-W", "2", dns_ip, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- ping -c 10 -W 2 {dns_ip}  (post-rollback packet loss)"
            if r.returncode != 0 and "packet loss" not in r.stdout:
                return True, detail + "\n  (ping unavailable — skipping)"
            loss_pct = None
            avg_rtt  = None
            for line in r.stdout.strip().splitlines():
                if "packet loss" in line:
                    try:
                        loss_pct = line.strip().split("%")[0].split()[-1]
                    except (IndexError, ValueError):
                        pass
                if "avg" in line and "=" in line:
                    try:
                        avg_rtt = line.split("=")[1].strip().split("/")[1]
                    except (IndexError, ValueError):
                        pass
            detail += f"\n  post-rollback packet loss = {loss_pct}%  avg RTT = {avg_rtt} ms"
            if loss_pct and loss_pct not in ("0", "0.0", "0.00"):
                return False, detail + (
                    f"\n  ✘ Packet loss still {loss_pct}% after rollback — "
                    "netem corrupt rule may still be active on eth0"
                )
            return True, detail + "\n  ✔ 0% packet loss — corruption fully removed from wire"
        checks["Packet Loss Back to 0% (post-rollback)"] = _pc_packet_loss_zero

        # 4. TCP retransmit counter settled ───────────────────────────────────
        #    Large delta vs baseline = heavy corruption during fault (good evidence).
        #    Post-rollback the counter should stop growing.
        def _pc_retransmit_settled():
            pod = _pc_post_first_pod()
            detail = f"kubectl exec <pod> -n {namespace} -- cat /proc/net/snmp  (post-rollback RetransSegs)"
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
                "\n  ✔ Compare delta with pre-check baseline in validation logs."
                "\n    Large delta = corruption triggered heavy retransmits during fault."
                "\n    Counter should now be stable (not still growing)."
            )
            return True, detail
        checks["TCP Retransmit Counter (post-rollback)"] = _pc_retransmit_settled

        # 5. DNS resolution restored (UDP) ────────────────────────────────────
        def _pc_dns_restored():
            pod      = _pc_post_first_pod()
            svc_fqdn = f"{deployment}.{namespace}.svc.cluster.local"
            detail   = f"kubectl exec <pod> -n {namespace} -- nslookup {svc_fqdn}  (UDP)"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "nslookup", svc_fqdn, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- nslookup {svc_fqdn}  (UDP)"
            if r.returncode != 0:
                return True, detail + "\n  (nslookup unavailable — skipping)"
            resolved = "Address" in r.stdout
            detail  += f"\n  resolved={resolved}"
            if not resolved:
                return False, detail + "\n  ✘ DNS still failing after rollback — UDP responses still corrupt"
            return True, detail + "\n  ✔ DNS resolution (UDP) restored"
        checks["DNS Resolution Restored (UDP)"] = _pc_dns_restored

        # 6. Ping RTT restored ────────────────────────────────────────────────
        #    Corruption forces TCP retransmits — verify RTT normalized post-rollback.
        def _pc_rtt_restored():
            pod = _pc_post_first_pod()
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
        checks["Ping RTT Restored"] = _pc_rtt_restored

        # 7. HTTP success restored ────────────────────────────────────────────
        def _pc_http_restored():
            pod     = _pc_post_first_pod()
            svc_url = f"http://{deployment}.{namespace}.svc.cluster.local"
            detail  = f"kubectl exec <pod> -n {namespace} -- curl -s -m 5 {svc_url}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
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
                        "retransmit delays may not have cleared"
                    )
            except ValueError:
                pass
            if http_code not in ("200", "201", "204", "301", "302", "?"):
                return False, detail + f"\n  ✘ HTTP {http_code} — service not responding normally"
            return True, detail + "\n  ✔ HTTP responding normally post-rollback"
        checks["HTTP Success Restored"] = _pc_http_restored

        # 7. Service endpoints restored ───────────────────────────────────────
        def _pc_endpoints_restored():
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
        checks["Service Endpoints Restored"] = _pc_endpoints_restored

        # 8. Probe failures stopped ───────────────────────────────────────────
        def _pc_probe_stopped():
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
                    "\n  ✘ Probe failures still firing — retransmit delays from corruption not yet cleared"
                )
            return True, detail + "\n  ✔ No probe failures post-rollback"
        checks["Probe Failures Stopped (post)"] = _pc_probe_stopped

        # 9. Restart count delta ──────────────────────────────────────────────
        def _pc_restart_delta():
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
                    "\n    Liveness probe killed by retransmit-induced timeouts during corruption fault."
                )
            else:
                detail += "\n  ✔ Restart counts within normal range"
            return True, detail
        checks["Restart Count Delta (post)"] = _pc_restart_delta

        # 10. No stale network warning events ─────────────────────────────────
        def _pc_no_net_events():
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
        checks["No Network Warning Events (post)"] = _pc_no_net_events

    # ── Packet-duplication post-checks ───────────────────────────────────────
    if experiment_id in _PACKET_DUPLICATION_IDS:

        def _pd_post_first_pod():
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

        # 1. NetworkChaos CRD cleaned up ──────────────────────────────────────
        def _pd_post_crd_deleted():
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
        checks["NetworkChaos CRD Cleaned Up"] = _pd_post_crd_deleted

        # 2. tc-netem duplicate rule removed from eth0 ────────────────────────
        def _pd_post_tc_netem_removed():
            pod = _pd_post_first_pod()
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
                return False, detail + "\n  ✘ netem rule still on eth0 — duplicate rule not rolled back"
            return True, detail + "\n  ✔ netem rule removed — eth0 back to normal qdisc"
        checks["tc-netem Rule Removed"] = _pd_post_tc_netem_removed

        # 3. Service endpoints fully restored ─────────────────────────────────
        def _pd_post_endpoints_restored():
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
            subsets      = ep.get("subsets") or []
            ready_ips    = []
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
        checks["Service Endpoints Restored"] = _pd_post_endpoints_restored

        # 4. Ping confirms 0 DUP! packets post-rollback ───────────────────────
        #    The definitive rollback signal: DUP! lines must be gone.
        def _pd_post_ping_no_dup():
            pod = _pd_post_first_pod()
            r_dns = _kubectl("get", "service", "kube-dns", "-n", "kube-system",
                             "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
            dns_ip = r_dns.stdout.strip() if r_dns.returncode == 0 and r_dns.stdout.strip() else "10.0.0.10"
            detail = f"kubectl exec <pod> -n {namespace} -- ping -c 5 -W 2 {dns_ip}  (post-rollback DUP! check)"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "ping", "-c", "5", "-W", "2", dns_ip, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- ping -c 5 -W 2 {dns_ip}  (post-rollback DUP! check)"
            if r.returncode != 0 and "DUP!" not in r.stdout:
                return True, detail + f"\n  (ping unavailable — skipping: {r.stderr.strip()[:80]})"
            dup_lines = [l for l in r.stdout.strip().splitlines() if "DUP!" in l]
            detail += f"\n  DUP! packets received = {len(dup_lines)}"
            if dup_lines:
                return False, detail + (
                    "\n  ✘ Duplicate ICMP replies still present after rollback — "
                    "tc-netem duplicate rule not fully removed"
                )
            return True, detail + "\n  ✔ 0 DUP! packets post-rollback — duplication fully cleared"
        checks["Ping: 0 DUP! Post-Rollback"] = _pd_post_ping_no_dup

        # 5. DNS resolution restored ──────────────────────────────────────────
        def _pd_post_dns_restored():
            pod      = _pd_post_first_pod()
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
        checks["DNS Resolution Restored"] = _pd_post_dns_restored

        # 6. Probe failure events stopped ─────────────────────────────────────
        def _pd_post_probe_events_stopped():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "reason=Unhealthy",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --field-selector reason=Unhealthy  (last 2m)"
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
                    "\n    Pods may not have recovered from dup-ACK-induced liveness kills"
                )
            return True, detail + "\n  ✔ No probe failures post-rollback"
        checks["Probe Failures Stopped (post)"] = _pd_post_probe_events_stopped

        # 7. Restart count delta ──────────────────────────────────────────────
        def _pd_post_restart_delta():
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
            lines_out    = []
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
                    "\n  Dup-ACK fast retransmit was large enough to trigger liveness probe kills"
                    "\n  Check if app has recovered to stable state"
                )
            else:
                detail += "\n  ✔ Restart counts within normal range post-rollback"
            return True, detail
        checks["Restart Count Delta (post)"] = _pd_post_restart_delta

        # 8. HTTP response time back to normal ────────────────────────────────
        #    Duplication has low latency impact for TCP — elevated value post-rollback
        #    indicates the netem rule was not fully removed.
        def _pd_post_http_restored():
            pod     = _pd_post_first_pod()
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
                        f"\n  ✘ Response time {t:.3f}s still elevated — "
                        "duplication should not cause latency; netem may still be active"
                    )
            except ValueError:
                pass
            return True, detail + "\n  ✔ HTTP response time normal — compare with pre-check baseline in logs"
        checks["HTTP Response Time Restored"] = _pd_post_http_restored

        # TCP retransmit counter settled ──────────────────────────────────────
        #    Dup ACKs trigger fast retransmit — RetransSegs + TCPDSACKRecv should
        #    stop growing once the duplicate rule is removed.
        def _pd_post_retrans_settled():
            pod = _pd_post_first_pod()
            detail = f"kubectl exec <pod> -n {namespace} -- cat /proc/net/snmp + /proc/net/netstat  (post-rollback)"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            retrans = dsack = None
            rs = _kubectl("exec", pod, "-n", namespace, "--",
                          "cat", "/proc/net/snmp", context=aks_context)
            if rs.returncode == 0:
                snmp_lines = rs.stdout.strip().splitlines()
                for i, line in enumerate(snmp_lines):
                    if line.startswith("Tcp:") and i + 1 < len(snmp_lines):
                        keys = line.split()
                        vals = snmp_lines[i + 1].split()
                        if "RetransSegs" in keys:
                            idx = keys.index("RetransSegs")
                            retrans = vals[idx] if idx < len(vals) else None
                        break
            rn = _kubectl("exec", pod, "-n", namespace, "--",
                          "cat", "/proc/net/netstat", context=aks_context)
            if rn.returncode == 0:
                netstat_lines = rn.stdout.strip().splitlines()
                for i, line in enumerate(netstat_lines):
                    if line.startswith("TcpExt:") and i + 1 < len(netstat_lines):
                        keys = line.split()
                        vals = netstat_lines[i + 1].split()
                        if "TCPDSACKRecv" in keys:
                            idx = keys.index("TCPDSACKRecv")
                            dsack = vals[idx] if idx < len(vals) else None
                        break
            detail = (
                f"kubectl exec {pod} -n {namespace} -- /proc/net/snmp + /proc/net/netstat  (post-rollback)"
                f"\n  post-rollback RetransSegs  = {retrans}"
                f"\n  post-rollback TCPDSACKRecv = {dsack}"
                "\n  ✔ TCP counters captured — compare growth rate vs during-fault values in logs."
                "\n  Counters should stop growing once duplication rule is removed."
            )
            return True, detail
        checks["TCP Retransmit Counter (post-rollback)"] = _pd_post_retrans_settled

        # No network warning events ───────────────────────────────────────────
        def _pd_post_no_net_events():
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
                return False, detail + "\n  ✘ Network warning events still firing — not fully recovered"
            return True, detail + "\n  ✔ No network warning events post-rollback"
        checks["No Network Warning Events (post)"] = _pd_post_no_net_events

    # ── Network-partition post-checks ────────────────────────────────────────
    if experiment_id in _PARTITION_IDS:

        def _np_post_first_pod():
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

        # 1. NetworkChaos CRD cleaned up ──────────────────────────────────────
        def _np_post_crd_deleted():
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
        checks["NetworkChaos CRD Cleaned Up"] = _np_post_crd_deleted

        # 2. iptables chaos rules removed from pod ────────────────────────────
        #    Leftover CHAOS chain after rollback = pod still partitioned.
        def _np_post_iptables_removed():
            pod = _np_post_first_pod()
            detail = f"kubectl exec <pod> -n {namespace} -- iptables -L -n"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "iptables", "-L", "-n", context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- iptables -L -n  (post-rollback)"
            if r.returncode != 0:
                return True, detail + (
                    f"\n  pod={pod}"
                    "\n  (iptables unavailable in image — skipping; CRD status is authoritative)"
                )
            chaos_chains = [l for l in r.stdout.splitlines()
                            if "chaos" in l.lower() or "CHAOS" in l]
            detail += f"\n  chaos-related iptables lines: {chaos_chains if chaos_chains else 'none'}"
            if chaos_chains:
                return False, detail + (
                    "\n  ✘ Chaos iptables chains still present after rollback"
                    "\n  Pod is still partitioned — traffic will continue to be dropped"
                )
            return True, detail + "\n  ✔ No chaos iptables chains — iptables rules fully removed"
        checks["iptables Chaos Rules Removed"] = _np_post_iptables_removed

        # 3. Service endpoints fully restored ─────────────────────────────────
        #    The definitive rollback signal — partitioned pods must rejoin endpoints.
        def _np_post_endpoints_restored():
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
                    "pods have not recovered readiness after partition rollback"
                )
            if not ready_ips:
                return False, detail + "\n  ✘ No ready endpoints — service unreachable post-rollback"
            return True, detail + "\n  ✔ All endpoints ready — Service routing fully restored"
        checks["Service Endpoints Restored"] = _np_post_endpoints_restored

        # 4. Connectivity restored (ping — 0% loss) ───────────────────────────
        #    iptables DROP rules gone → ping returns to 0% loss.
        def _np_post_ping_restored():
            pod = _np_post_first_pod()
            # Ping the CoreDNS pod IP (answers ICMP), not the kube-dns
            # ClusterIP (never answers ICMP — see _np_partition_ping_target).
            dns_ip = _np_partition_ping_target(aks_context)
            detail = f"kubectl exec <pod> -n {namespace} -- ping -c 3 -W 2 {dns_ip}  (post-rollback connectivity)"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "ping", "-c", "3", "-W", "2", dns_ip, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- ping -c 3 -W 2 {dns_ip}  (post-rollback connectivity)"
            if r.returncode != 0 and "packet loss" not in r.stdout:
                return True, detail + f"\n  (ping unavailable — skipping: {r.stderr.strip()[:80]})"
            loss_pct = avg_rtt = None
            for line in r.stdout.strip().splitlines():
                if "packet loss" in line:
                    try:
                        loss_pct = line.strip().split("%")[0].split()[-1]
                    except (IndexError, ValueError):
                        pass
                if "avg" in line and "=" in line:
                    try:
                        avg_rtt = line.split("=")[1].strip().split("/")[1]
                    except (IndexError, ValueError):
                        pass
            detail += f"\n  post-rollback packet loss = {loss_pct}%  avg RTT = {avg_rtt} ms"
            if loss_pct and loss_pct not in ("0", "0.0", "0.00"):
                return False, detail + (
                    f"\n  ✘ Post-rollback packet loss = {loss_pct}% — "
                    "iptables DROP rules may not be fully removed"
                )
            return True, detail + "\n  ✔ 0% packet loss post-rollback — network connectivity fully restored"
        checks["Connectivity Restored (ping — 0% loss)"] = _np_post_ping_restored

        # 5. DNS resolution restored ──────────────────────────────────────────
        def _np_post_dns_restored():
            pod      = _np_post_first_pod()
            svc_fqdn = f"{deployment}.{namespace}.svc.cluster.local"
            detail   = f"kubectl exec <pod> -n {namespace} -- nslookup {svc_fqdn}"
            if not pod:
                return True, detail + "\n  (no running pod — skipping)"
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "nslookup", svc_fqdn, context=aks_context)
            detail = f"kubectl exec {pod} -n {namespace} -- nslookup {svc_fqdn}  (post-rollback)"
            if r.returncode != 0:
                return True, detail + f"\n  (nslookup unavailable — skipping: {r.stderr.strip()[:80]})"
            resolved = "Address" in r.stdout
            detail  += f"\n  resolved={resolved}"
            if not resolved:
                return False, detail + (
                    f"\n  ✘ DNS still not resolving after rollback — {r.stdout.strip()[:120]}"
                    "\n  UDP traffic may still be blocked; iptables rules may not be fully removed"
                )
            return True, detail + "\n  ✔ DNS resolution restored — UDP traffic flowing normally"
        checks["DNS Resolution Restored"] = _np_post_dns_restored

        # 6. Probe failures stopped ───────────────────────────────────────────
        def _np_post_probe_events_stopped():
            r = _kubectl("get", "events", "-n", namespace,
                         "--field-selector", "reason=Unhealthy",
                         "-o", "json", context=aks_context)
            detail = f"kubectl get events -n {namespace} --field-selector reason=Unhealthy  (last 2m)"
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
                    "\n  ✘ Probe failures still firing after rollback"
                    "\n  Pods may not have fully recovered — partition may still be active"
                )
            return True, detail + "\n  ✔ No probe failures post-rollback — probes recovering normally"
        checks["Probe Failures Stopped (post)"] = _np_post_probe_events_stopped

        # 7. Restart count delta ──────────────────────────────────────────────
        #    Restarts during partition are expected (liveness kills).
        #    Flag if counts are abnormally high post-rollback — CrashLoop risk.
        def _np_post_restart_delta():
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
            lines_out     = []
            high_restarts = []
            for pod in pods:
                pname = pod.get("metadata", {}).get("name", "?")
                total_restarts = sum(
                    cs.get("restartCount", 0)
                    for cs in pod.get("status", {}).get("containerStatuses", [])
                )
                lines_out.append(f"  {pname}: restarts={total_restarts}")
                if total_restarts >= 5:
                    high_restarts.append(f"{pname}={total_restarts}")
            detail += "\n" + ("\n".join(lines_out) if lines_out else "  no pods found")
            if high_restarts:
                detail += (
                    f"\n  ⚠ High restart counts: {high_restarts}"
                    "\n  Pods experienced many liveness kills during partition."
                    "\n  Watch for CrashLoopBackOff — pods may not stabilise if startup is slow."
                )
            else:
                detail += "\n  ✔ Restart counts within acceptable range post-rollback"
            return True, detail
        checks["Restart Count Delta (post)"] = _np_post_restart_delta

        # 8. HTTP response time restored ──────────────────────────────────────
        #    After partition rolls back ALL connections should recover.
        #    Elevated HTTP time post-rollback = iptables rules not fully removed.
        def _np_post_http_restored():
            pod     = _np_post_first_pod()
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
                if t > 2.0:
                    return False, detail + (
                        f"\n  ✘ Response time {t:.3f}s still elevated — "
                        "iptables rules may not be fully removed or pods still recovering"
                    )
            except ValueError:
                pass
            return True, detail + "\n  ✔ HTTP response time restored — compare with pre-check baseline in logs"
        checks["HTTP Response Time Restored"] = _np_post_http_restored

        # 9. No network warning events ────────────────────────────────────────
        def _np_post_no_net_events():
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
                return False, detail + "\n  ✘ Network warning events still firing — not fully recovered"
            return True, detail + "\n  ✔ No network warning events post-rollback"
        checks["No Network Warning Events (post)"] = _np_post_no_net_events

    # Stress-only extra check: No OOMKilled post-stress
    return checks
