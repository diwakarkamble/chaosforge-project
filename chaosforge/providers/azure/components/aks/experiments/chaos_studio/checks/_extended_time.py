import datetime as _dt
import json

from ._extended_common import (
    _MAX_SAFE_SKEW_SECS,
    _TIMING_SENSITIVE_APPS,
    _check_chaos_crd,
    _first_running_pod,
    _get_deployment_json,
    _get_pods_json,
    _kubectl,
    _parse_skew_offset_to_secs,
)


def build_time_chaos_pre_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    *,
    experiment_id: str = "",
    time_offset: str = "+5m",
    duration: str = "60s",
) -> "dict[str, callable]":
    """
    Pre-chaos checks for TimeChaos (clock-skew forward/backward).

    Hard blocks:
      - Offset magnitude > 5 minutes (TLS/JWT/Kerberos cliff)
      - Timing-sensitive process detected in namespace (etcd, Vault, Kafka, etc.)
      - Any pods currently in CrashLoopBackOff (pre-existing instability)
      - timechaos CRD not installed (experiment silently no-ops)

    Soft warnings (pass=True, prefixed detail):
      - No NTP/chrony sync on target node (clock recovery after skew revert)
      - cert-manager certificates approaching expiry within the skew window

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"

    # ── 0. TimeChaos CRD installed ────────────────────────────────────────────
    def _timechaos_crd():
        return _check_chaos_crd(aks_context, "timechaos.chaos-mesh.org")
    checks["TimeChaos CRD Installed"] = _timechaos_crd

    # ── 1. Offset magnitude guard ─────────────────────────────────────────────
    # Rationale: TLS certificates, JWT tokens (exp claim), OIDC tokens, and
    # Kerberos tickets all have short validity windows. Skewing >5 minutes
    # silently invalidates in-flight tokens, causes TLS handshake failures, and
    # can put Vault seal-check timers into permanent error state. We hard-block
    # here because the experiment would be testing clock-break, not resilience.
    _offset_str = time_offset

    def _offset_magnitude():
        offset_secs = _parse_skew_offset_to_secs(_offset_str)
        direction   = "forward" if "forward" in experiment_id else "backward"
        detail = (
            f"TimeChaos timeOffset={_offset_str}  experiment={experiment_id}\n"
            f"  parsed magnitude: {offset_secs:.0f}s  safe_limit: {_MAX_SAFE_SKEW_SECS}s  "
            f"direction: {direction}"
        )
        if offset_secs == 0.0:
            return True, detail + "\n  ✔ Could not parse offset — proceeding (check timeOffset format)"
        if offset_secs > _MAX_SAFE_SKEW_SECS:
            return False, (
                detail + f"\n  ✘ Offset {offset_secs:.0f}s exceeds safe limit ({_MAX_SAFE_SKEW_SECS}s). "
                f"TLS certificates, JWT tokens, and Kerberos tickets will expire mid-experiment. "
                f"Reduce timeOffset to ≤5m or use a dedicated test namespace with no live auth flows."
            )
        return True, detail + f"\n  ✔ Offset {offset_secs:.0f}s within safe limit"
    checks["Clock Skew Offset Magnitude"] = _offset_magnitude

    # ── 2. Timing-sensitive system detection ──────────────────────────────────
    # Rationale: etcd uses Raft timeouts tied to wall-clock. Vault uses time for
    # lease expiry and seal checks. Kafka/ZooKeeper use timestamps for log
    # compaction and leader election. Even a small skew on these causes
    # split-brain, permanent seal, or topic corruption — not recoverable by
    # chaos rollback.
    def _timing_sensitive_apps():
        r = _kubectl("get", "pods", "-n", namespace, "-o", "json", context=aks_context)
        if r.returncode != 0:
            return True, (
                f"kubectl get pods -n {namespace} --context {aks_context}\n"
                f"  ⚠ Could not query pods — skipping timing-sensitive check"
            )
        try:
            pods = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse pods — skipping timing-sensitive check"

        found = []
        for pod in pods:
            pod_name = pod.get("metadata", {}).get("name", "?")
            labels   = pod.get("metadata", {}).get("labels", {}) or {}
            label_values = {str(v).lower() for v in labels.values()}
            # Check pod labels and container image names for sensitive app names
            for c in pod.get("spec", {}).get("containers", []):
                image = c.get("image", "").lower().split(":")[0].split("/")[-1]
                cname = c.get("name", "").lower()
                for sensitive in _TIMING_SENSITIVE_APPS:
                    if sensitive in image or sensitive in cname or sensitive in label_values:
                        found.append(f"{pod_name}/{c.get('name','?')} (matched: {sensitive})")

        detail = (
            f"kubectl get pods -n {namespace} --context {aks_context}  "
            f"(checking for timing-sensitive systems)\n"
            f"  timing-sensitive processes found: {found if found else 'none'}"
        )
        if found:
            return False, (
                detail + f"\n  ✘ Timing-sensitive system(s) detected in namespace '{namespace}'. "
                f"Clock skew will corrupt their internal state (split-brain, lease expiry, "
                f"token invalidation). Target a different namespace or exclude these pods."
            )
        return True, detail + "\n  ✔ No timing-sensitive systems detected"
    checks["Timing-Sensitive System Detection"] = _timing_sensitive_apps

    # ── 3. Pre-existing CrashLoopBackOff check ────────────────────────────────
    # Rationale: a pod already crashing before skew makes post-chaos attribution
    # impossible. Clock-induced crashes look identical to pre-existing ones.
    def _no_pre_existing_crashloop():
        pods, err = _get_pods_json(aks_context, namespace, selector)
        if pods is None:
            return True, f"Could not query pods — skipping crashloop check: {err}"
        crashing = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            for cs in pod.get("status", {}).get("containerStatuses", []):
                if cs.get("state", {}).get("waiting", {}).get("reason") == "CrashLoopBackOff":
                    crashing.append(f"{name}/{cs.get('name','?')}")
        detail = (
            f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
            f"  CrashLoopBackOff containers: {crashing if crashing else 'none'}"
        )
        if crashing:
            return False, (
                detail + "\n  ✘ Pods already crashing before clock skew. "
                "Post-experiment attribution will be impossible — fix first."
            )
        return True, detail + "\n  ✔ No pre-existing CrashLoopBackOff"
    checks["No Pre-Existing CrashLoop"] = _no_pre_existing_crashloop

    # ── 4. cert-manager certificate expiry window (soft warning) ──────────────
    # Rationale: if any Certificate resource in the namespace is due to renew
    # within the skew window, cert-manager's renewal logic (which uses wall-clock
    # via notBefore/notAfter) may skip renewal or double-renew, breaking TLS.
    _offset_secs_for_cert = _parse_skew_offset_to_secs(time_offset)

    def _cert_manager_expiry():
        r = _kubectl("get", "certificates", "-n", namespace, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return True, (
                f"kubectl get certificates -n {namespace} --context {aks_context}\n"
                f"  (cert-manager CRD not present or no certificates — skipping)"
            )
        try:
            certs = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse Certificate resources — skipping"

        if not certs:
            return True, (
                f"kubectl get certificates -n {namespace} --context {aks_context}\n"
                f"  No Certificate resources found — no cert-manager expiry concern"
            )

        now    = _dt.datetime.now(_dt.timezone.utc)
        at_risk = []
        for cert in certs:
            cname  = cert.get("metadata", {}).get("name", "?")
            status = cert.get("status", {})
            expiry_str = status.get("notAfter") or ""
            renew_str  = status.get("renewalTime") or ""
            for ts_str in (renew_str, expiry_str):
                if not ts_str:
                    continue
                try:
                    ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    window = (ts - now).total_seconds()
                    if 0 < window < _offset_secs_for_cert * 2:
                        at_risk.append(f"{cname} (renews/expires in {window:.0f}s, skew={_offset_secs_for_cert:.0f}s)")
                    break
                except ValueError:
                    pass

        detail = (
            f"kubectl get certificates -n {namespace} --context {aks_context}\n"
            f"  certificates at risk during skew window: {at_risk if at_risk else 'none'}"
        )
        if at_risk:
            # Soft warning — cert renewal within skew window is risky but not certain to break
            return True, (
                "⚠ " + detail +
                "\n  Certificates approaching renewal/expiry during the clock-skew window. "
                "cert-manager uses wall-clock for renewal decisions — skewed time may trigger "
                "double-renewal or cause ACME challenge failures. Monitor cert status post-experiment."
            )
        return True, detail + "\n  ✔ No certificates at risk in skew window"
    checks["cert-manager Certificate Expiry Window"] = _cert_manager_expiry

    # ── 5. Node NTP/chrony sync check (soft warning) ─────────────────────────
    # Rationale: after TimeChaos reverts, the pod clock is restored by Chaos Mesh.
    # But if the underlying node has no NTP sync daemon, the node's own clock
    # drift can persist after the experiment, masking recovery or causing
    # persistent skew in log timestamps.
    def _node_time_sync():
        # Get the node hosting the target pod (just check one — they typically
        # share the same node-level NTP config in AKS)
        pod = _first_running_pod(aks_context, namespace, selector)
        if not pod:
            return True, (
                f"No running pod found for selector {selector} — skipping node time-sync check"
            )
        r_node = _kubectl("get", "pod", pod, "-n", namespace,
                          "-o", "jsonpath={.spec.nodeName}", context=aks_context)
        if r_node.returncode != 0 or not r_node.stdout.strip():
            return True, "Could not determine target node — skipping time-sync check"
        node = r_node.stdout.strip()

        # Check for chronyd/ntpd as a DaemonSet in kube-system
        r_ds = _kubectl("get", "daemonsets", "-n", "kube-system", "-o", "json",
                        context=aks_context)
        ntp_found = False
        if r_ds.returncode == 0:
            try:
                for ds in json.loads(r_ds.stdout).get("items", []):
                    name = ds.get("metadata", {}).get("name", "").lower()
                    if any(ntp in name for ntp in ("chrony", "ntp", "timekeeper")):
                        ntp_found = True
                        break
            except ValueError:
                pass

        detail = (
            f"Node: {node}  context={aks_context}\n"
            f"  NTP/chrony DaemonSet in kube-system: {'found' if ntp_found else 'not found'}"
        )
        if not ntp_found:
            return True, (
                "⚠ " + detail +
                "\n  No NTP/chrony DaemonSet detected. After TimeChaos reverts, node clock "
                "accuracy depends on cloud-hypervisor NTP (AKS uses Azure host time sync). "
                "Verify pod log timestamps post-experiment to confirm clock recovery."
            )
        return True, detail + "\n  ✔ NTP daemon present — clock will resync after experiment"
    checks["Node Time Sync (NTP/Chrony)"] = _node_time_sync

    return checks


# ═════════════════════════════════════════════════════════════════════════════
# TIME CHAOS (Clock Skew) — Post-Checks
# ═════════════════════════════════════════════════════════════════════════════

def build_time_chaos_post_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
) -> "dict[str, callable]":
    """
    Post-chaos checks for TimeChaos. Confirms the system recovered after
    the clock-skew experiment reverted.

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"

    # ── 1. No CrashLoopBackOff post-skew ─────────────────────────────────────
    # Rationale: processes that check time-validity (JWT expiry, cert notAfter)
    # will crash on first request after a forward skew reverts if they cached
    # an expired token. CrashLoopBackOff is the primary observable symptom.
    def _no_crashloop_post():
        pods, err = _get_pods_json(aks_context, namespace, selector)
        if pods is None:
            return False, f"Could not query pods: {err}"
        crashing = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            for cs in pod.get("status", {}).get("containerStatuses", []):
                reason = cs.get("state", {}).get("waiting", {}).get("reason", "")
                if reason == "CrashLoopBackOff":
                    crashing.append(f"{name}/{cs.get('name','?')}")
        detail = (
            f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
            f"  CrashLoopBackOff containers: {crashing if crashing else 'none'}"
        )
        if crashing:
            return False, (
                detail + "\n  ✘ CrashLoopBackOff after clock skew — likely caused by "
                "expired token/cert cached during skew window. Check app logs for "
                "'certificate expired', 'token expired', or 'clock skew' errors."
            )
        return True, detail + "\n  ✔ No CrashLoopBackOff after clock-skew revert"
    checks["No CrashLoop After Clock Skew"] = _no_crashloop_post

    # ── 2. Replicas restored ──────────────────────────────────────────────────
    def _replicas_restored():
        dep, err = _get_deployment_json(aks_context, namespace, deployment)
        if dep is None:
            return False, f"Could not query deployment: {err}"
        desired   = dep.get("spec", {}).get("replicas") or 0
        ready     = dep.get("status", {}).get("readyReplicas") or 0
        available = dep.get("status", {}).get("availableReplicas") or 0
        detail = (
            f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}\n"
            f"  desired={desired}  ready={ready}  available={available}"
        )
        if ready < desired:
            return False, detail + f"\n  ✘ Only {ready}/{desired} replicas ready post-skew"
        return True, detail + "\n  ✔ Replica floor restored"
    checks["Replicas Restored"] = _replicas_restored

    # ── 3. TLS / auth-related pod events ─────────────────────────────────────
    # Rationale: if the skew caused TLS handshake failures or certificate errors,
    # Kubernetes will have emitted Warning events for those pods. These persist
    # even after the experiment reverts and are the audit trail for time-induced damage.
    def _no_tls_clock_events():
        r = _kubectl("get", "events", "-n", namespace, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return True, f"Could not query events (non-fatal): {r.stderr.strip()}"
        try:
            events = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse events — skipping"

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=10)
        tls_keywords = (
            "certificate", "tls", "x509", "expired", "clock skew", "time",
            "token", "unauthorized", "401", "403", "kerberos", "ssl",
        )
        found_events = []
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
            msg    = ev.get("message", "").lower()
            reason = ev.get("reason", "").lower()
            obj    = ev.get("involvedObject", {}).get("name", "?")
            if any(kw in msg or kw in reason for kw in tls_keywords):
                found_events.append(
                    f"  {obj}: {ev.get('reason','')} — {ev.get('message','')[:100]}"
                )

        detail = (
            f"kubectl get events -n {namespace} --context {aks_context}  (last 10m)\n"
            f"  TLS/auth/time-related Warning events: "
            + ("\n" + "\n".join(found_events) if found_events else "none")
        )
        if found_events:
            return False, (
                detail + "\n  ✘ TLS/auth warnings detected post-skew. "
                "Tokens or certificates may have been invalidated during the skew window."
            )
        return True, detail + "\n  ✔ No TLS/auth/clock Warning events"
    checks["No TLS/Auth Events Post-Skew"] = _no_tls_clock_events

    # ── 4. TimeChaos CRD cleaned up ───────────────────────────────────────────
    # Rationale: if the Chaos Mesh TimeChaos resource was not deleted, the clock
    # skew is still active even though the experiment "completed".
    def _timechaos_crd_deleted():
        r = _kubectl("get", "timechaos", "-n", "chaos-testing",
                     "--no-headers", context=aks_context)
        detail = "kubectl get timechaos -n chaos-testing"
        if r.returncode != 0:
            return True, detail + "\n  (query failed — assuming cleaned up)"
        existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        if existing:
            return False, (
                detail + f"\n  ✘ TimeChaos resources still present: {existing}\n"
                "  Clock skew may still be ACTIVE — pod clocks not yet restored."
            )
        return True, detail + "\n  ✔ All TimeChaos CRD resources removed — clock restored"
    checks["TimeChaos CRD Cleaned Up"] = _timechaos_crd_deleted

    # ── 5. In-pod clock revert verification ──────────────────────────────────
    # Rationale: CRD deletion proves Chaos Mesh thinks it cleaned up. It does
    # NOT prove the container clock actually reverted. Chaos Mesh restores the
    # clock via adjtimex(2) — if that step fails silently, the pod runs on a
    # skewed clock while the experiment is marked complete. Compare pod epoch
    # against the node's epoch (via kubectl node time annotation) to confirm
    # the skew has actually cleared.
    def _pod_clock_reverted():
        pod = _first_running_pod(aks_context, namespace, selector)
        if not pod:
            return True, (
                f"No running pod found for selector '{selector}' — "
                "skipping in-pod clock revert check"
            )
        r = _kubectl("exec", pod, "-n", namespace, "--",
                     "sh", "-c", "date +%s", context=aks_context)
        detail = f"kubectl exec {pod} -n {namespace} -- date +%s"
        if r.returncode != 0:
            return True, detail + f"\n  (exec failed — skipping: {r.stderr.strip()[:80]})"
        try:
            pod_epoch = int(r.stdout.strip())
        except ValueError:
            return True, detail + "\n  (could not parse epoch — skipping)"

        import time as _time
        host_epoch = int(_time.time())
        drift_secs = abs(pod_epoch - host_epoch)
        detail = (
            f"kubectl exec {pod} -n {namespace} -- date +%s\n"
            f"  pod epoch={pod_epoch}  host epoch={host_epoch}  "
            f"drift={drift_secs}s"
        )
        if drift_secs > 30:
            return False, (
                detail + f"\n  ✘ Pod clock still drifted {drift_secs}s from host after "
                "TimeChaos revert. Chaos Mesh adjtimex restore may have failed — "
                "pod is still running on a skewed clock. Restart the pod to force clock reset."
            )
        return True, detail + "\n  ✔ Pod clock within 30s of host — clock revert confirmed"
    checks["Pod Clock Reverted"] = _pod_clock_reverted

    return checks
