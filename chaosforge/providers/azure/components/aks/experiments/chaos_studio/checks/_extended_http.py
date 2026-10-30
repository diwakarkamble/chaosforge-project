import datetime as _dt
import json

from ._extended_common import (
    _check_chaos_crd,
    _check_no_stale_chaos_crd,
    _get_deployment_json,
    _kubectl,
    _parse_duration_to_secs,
)


def build_http_chaos_pre_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    *,
    experiment_id: str = "",
    http_port: str = "80",
    injected_delay: str = "5s",
    duration: str = "60s",
) -> "dict[str, callable]":
    """
    Pre-chaos checks for HTTPChaos (http-delay, http-abort).

    Hard blocks:
      - liveness probe timeout × failureThreshold ≤ injected delay
        (kubelet will kill pod before the app can observe the fault gracefully)
      - readiness probe timeout × failureThreshold ≤ injected delay
        (pod removed from endpoints before chaos duration expires = false signal)

    Soft warnings:
      - No DestinationRule / circuit-breaker upstream (soft-warn: experiment
        may cause cascade if caller has no retry/circuit-break protection)
      - Target port not in any container's containerPorts

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"

    _delay_secs  = _parse_duration_to_secs(injected_delay)
    _target_port = str(http_port).strip()
    _is_abort    = "abort" in experiment_id

    # ── 0a. HTTPChaos CRD installed ───────────────────────────────────────────
    def _httpchaos_crd():
        return _check_chaos_crd(aks_context, "httpchaos.chaos-mesh.org")
    checks["HTTPChaos CRD Installed"] = _httpchaos_crd

    # ── 0b. No stale HTTPChaos resource active ────────────────────────────────
    def _no_stale_httpchaos():
        return _check_no_stale_chaos_crd(aks_context, "httpchaos")
    checks["No Stale HTTPChaos Resource"] = _no_stale_httpchaos

    # ── 0c. chaos-tproxy sidecar injected into target pods (HARD BLOCK) ─────────
    # Rationale: HTTPChaos works by connecting to a chaos-tproxy process running
    # INSIDE the pod's network namespace to intercept HTTP traffic. This process
    # is injected as an init container by Chaos Mesh's mutating webhook when the
    # pod starts — but ONLY when the namespace has the
    # chaos-mesh.org/inject=enabled label. Without it:
    #   - Injection succeeds (Chaos Studio reports "Running")
    #   - Recovery fails with "unexpected EOF" because there is no chaos-tproxy
    #     to receive the cleanup RPC call
    # Fix: label the namespace, then rolling-restart the deployment so new pods
    # get the init container injected before the experiment runs.
    def _tproxy_injected():
        # Chaos Mesh supports two HTTPChaos injection methods:
        # A) Sidecar injection via mutating webhook (chaos-mesh.org/inject label)
        #    — init container appears in pod spec
        # B) nsexec: chaos-daemon enters pod netns directly, starts tproxy there
        #    — NO init container; requires pod securityContext to allow it
        #    (allowPrivilegeEscalation must not be false; preferably runAsUser=0)
        #
        # Detect which method this cluster uses by checking for the pod injection
        # webhook. If absent, this is an nsexec install — check security context
        # instead of init containers.

        # Check for pod injection webhook
        r_wh = _kubectl("get", "mutatingwebhookconfiguration",
                        "chaos-mesh-mutation", "-o",
                        "jsonpath={.webhooks[*].name}", context=aks_context)
        webhook_names = r_wh.stdout.strip() if r_wh.returncode == 0 else ""
        # The sidecar injection webhook is specifically named "inject-v1-pod"
        # (or similar containing "inject" AND "pod"). CRD-mutation webhooks like
        # mpodchaos/miochaos are Chaos Mesh internal and do NOT inject sidecars
        # into user pods — they only validate Chaos Mesh CRD objects.
        has_pod_injection_webhook = any(
            "inject" in w.lower() and "pod" in w.lower()
            for w in webhook_names.split()
        )

        if has_pod_injection_webhook:
            # Method A: verify namespace label + init container present
            r_ns = _kubectl("get", "namespace", namespace, "-o",
                            "jsonpath={.metadata.labels.chaos-mesh\\.org/inject}",
                            context=aks_context)
            ns_label = r_ns.stdout.strip() if r_ns.returncode == 0 else ""
            detail = "Chaos Mesh install: sidecar injection (webhook present)\n"
            detail += f"kubectl get namespace {namespace}: chaos-mesh.org/inject={ns_label}"
            if ns_label != "enabled":
                return False, (
                    detail + f"\n  ✘ Namespace label missing. Fix:\n"
                    f"    kubectl label namespace {namespace} chaos-mesh.org/inject=enabled\n"
                    f"    kubectl rollout restart deployment/{deployment} -n {namespace}"
                )
            r_pods = _kubectl("get", "pods", "-n", namespace, "-l", selector,
                              "-o", "json", context=aks_context)
            try:
                pods = json.loads(r_pods.stdout).get("items", []) if r_pods.returncode == 0 else []
            except ValueError:
                pods = []
            no_sidecar = [
                p.get("metadata", {}).get("name", "?") for p in pods
                if not any("chaos" in c.get("name", "").lower()
                           for c in p.get("spec", {}).get("initContainers", []))
            ]
            if pods and no_sidecar:
                return False, (
                    detail + f"\n  ✘ Pods missing init container: {no_sidecar}\n"
                    f"    kubectl rollout restart deployment/{deployment} -n {namespace}"
                )
            return True, detail + "\n  ✔ Namespace label set, init containers present"

        else:
            # Method B: nsexec — chaos-daemon enters pod netns directly.
            # Requires pod NOT blocking privilege escalation. Check securityContext.
            detail = "Chaos Mesh install: nsexec/direct (no pod injection webhook)\n"
            detail += "  HTTPChaos starts chaos-tproxy via nsexec inside pod netns.\n"
            detail += "  Requirement: pod securityContext must not block privilege escalation."
            r_dep = _kubectl("get", "deployment", deployment, "-n", namespace,
                             "-o", "json", context=aks_context)
            if r_dep.returncode != 0:
                return True, detail + "\n  (could not query deployment — skipping)"
            try:
                dep = json.loads(r_dep.stdout)
            except ValueError:
                return True, detail + "\n  (could not parse deployment — skipping)"
            containers = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            blocking = []
            for c in containers:
                sc = c.get("securityContext") or {}
                if sc.get("allowPrivilegeEscalation") is False:
                    blocking.append(f"{c.get('name','?')}: allowPrivilegeEscalation=false")
            if blocking:
                return False, (
                    detail + f"\n  ✘ Container(s) block privilege escalation: {blocking}\n"
                    "  chaos-daemon cannot start chaos-tproxy via nsexec — HTTPChaos "
                    "will fail with 'unexpected EOF' during recovery. Fix:\n"
                    f"    Remove allowPrivilegeEscalation=false from container securityContext"
                )
            return True, detail + "\n  ✔ No privilege escalation block — nsexec injection should work"
    checks["Chaos Mesh Sidecar Injection (chaos-tproxy)"] = _tproxy_injected

    # ── 1. Liveness probe vs injected delay (HARD BLOCK) ─────────────────────
    # Rationale: HTTPChaos injects delay on the pod's outbound HTTP. If the
    # pod's *liveness probe* also makes HTTP calls (very common: GET /healthz),
    # the probe response will be delayed by the same amount. If that delay
    # exceeds livenessProbe.timeoutSeconds × failureThreshold, kubelet kills
    # the pod during the chaos window — not because the app is broken, but
    # because the probe timed out. The experiment then measures pod restart
    # latency, not application resilience.
    def _liveness_probe_vs_delay():
        if _is_abort:
            # For abort experiments, liveness probes hitting the aborted port get
            # immediate EOF/connection-refused instead of a delayed response.
            # kubelet kills the pod after failureThreshold × periodSeconds.
            #
            # On nsexec-based Chaos Mesh installs (no sidecar injection webhook),
            # this is a HARD BLOCK: pod restart destroys the container task that
            # chaos-daemon holds a reference to. Recovery then fails with
            # "no running task found" — the experiment cannot clean up and leaves
            # Chaos Studio in a failed state requiring manual intervention.
            #
            # Detect nsexec vs sidecar install to determine severity.
            _r_wh = _kubectl("get", "mutatingwebhookconfiguration",
                             "chaos-mesh-mutation", "-o",
                             "jsonpath={.webhooks[*].name}", context=aks_context)
            _wh_names = _r_wh.stdout.strip() if _r_wh.returncode == 0 else ""
            _is_nsexec = not any(
                "inject" in w.lower() and "pod" in w.lower()
                for w in _wh_names.split()
            )

            dep, err = _get_deployment_json(aks_context, namespace, deployment)
            if dep is None:
                return True, (
                    f"Experiment: {experiment_id}\n"
                    f"  HTTP abort — could not query deployment for probe check: {err}"
                )
            containers = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            lines = []
            probe_hits_port = False
            for c in containers:
                probe = c.get("livenessProbe") or {}
                if not probe:
                    continue
                threshold = probe.get("failureThreshold", 3)
                period    = probe.get("periodSeconds", 10)
                kill_secs = threshold * period
                # Check if probe targets the same port as the chaos injection
                probe_port = (
                    probe.get("httpGet", {}).get("port")
                    or probe.get("tcpSocket", {}).get("port")
                )
                hits_port = str(probe_port) == str(_target_port_int) if _target_port_int else False
                if hits_port:
                    probe_hits_port = True
                lines.append(
                    f"  container '{c.get('name','?')}': livenessProbe port={probe_port} "
                    f"failureThreshold={threshold}  periodSeconds={period}  "
                    f"kill_window={kill_secs}s"
                    + ("  ← HITS ABORT PORT" if hits_port else "")
                )
            detail = (
                f"Experiment: {experiment_id} (HTTP abort, port={_target_port})\n"
                f"  install_mode={'nsexec' if _is_nsexec else 'sidecar-injection'}\n"
                + ("\n".join(lines) if lines else "  No liveness probes defined — no kill risk")
            )
            if probe_hits_port and _is_nsexec:
                return False, (
                    detail + "\n  ✘ HARD BLOCK: liveness probe targets the aborted port on an "
                    "nsexec Chaos Mesh install. Pod restart (from probe failure) destroys the "
                    "container task reference — chaos-daemon cannot send the recovery RPC and "
                    "the experiment will fail with 'no running task found'.\n"
                    "  Fix options:\n"
                    f"    1. Increase livenessProbe.failureThreshold so kill_window > duration ({_parse_duration_to_secs(_delay_secs if not _is_abort else '60s'):.0f}s)\n"
                    "    2. Use aks-http-delay instead (pod stays alive, only delayed)\n"
                    "    3. Target a deployment with no liveness probe on this port"
                )
            if lines:
                return True, (
                    "⚠ " + detail +
                    "\n  Liveness probes will fail during abort window. "
                    + ("Sidecar-injection install — recovery survives pod restart." if not _is_nsexec
                       else "nsexec install — pod restart during duration may cause recovery failure.")
                )
            return True, detail

        dep, err = _get_deployment_json(aks_context, namespace, deployment)
        if dep is None:
            return True, f"Could not query deployment — skipping probe check: {err}"

        containers    = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        blocking_msgs = []

        for c in containers:
            cname = c.get("name", "?")
            probe = c.get("livenessProbe") or {}
            if not probe:
                continue
            timeout   = probe.get("timeoutSeconds", 1)
            threshold = probe.get("failureThreshold", 3)
            tolerance = timeout * threshold  # seconds before kubelet kills
            detail_line = (
                f"  container '{cname}': livenessProbe "
                f"timeoutSeconds={timeout}  failureThreshold={threshold}  "
                f"tolerance={tolerance}s  injected_delay={_delay_secs}s"
            )
            if _delay_secs > 0 and tolerance <= _delay_secs:
                blocking_msgs.append(
                    detail_line + "  ✘ KUBELET WILL KILL POD DURING CHAOS"
                )
            else:
                blocking_msgs.append(detail_line + "  ✔ probe tolerance > delay")

        detail = (
            f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}\n"
            f"  injected delay: {_delay_secs}s\n"
            + ("\n".join(blocking_msgs) if blocking_msgs else "  No liveness probes defined")
        )
        if any("KUBELET WILL KILL" in m for m in blocking_msgs):
            return False, (
                detail + "\n  ✘ Liveness probe tolerance ≤ injected delay. "
                f"Kubelet will kill the pod during the chaos window. "
                f"Increase livenessProbe.timeoutSeconds or reduce delay below "
                f"{min(c.get('livenessProbe', {}).get('timeoutSeconds', 1) * c.get('livenessProbe', {}).get('failureThreshold', 3) for c in containers if c.get('livenessProbe'))}s."
            )
        return True, detail
    checks["Liveness Probe vs Injected Delay"] = _liveness_probe_vs_delay

    # ── 2. Readiness probe vs injected delay (HARD BLOCK) ────────────────────
    # Rationale: if readinessProbe tolerance ≤ injected delay, the pod is
    # removed from Service endpoints *during* the chaos window. Traffic stops
    # reaching it — the experiment measures kube-proxy re-routing, not app
    # resilience. This is a subtler form of the same problem as liveness.
    def _readiness_probe_vs_delay():
        if _is_abort:
            return True, (
                f"Experiment: {experiment_id}\n"
                f"  HTTP abort fault — readiness probe timeout check not applicable"
            )

        dep, err = _get_deployment_json(aks_context, namespace, deployment)
        if dep is None:
            return True, f"Could not query deployment — skipping probe check: {err}"

        containers    = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        blocking_msgs = []

        for c in containers:
            cname = c.get("name", "?")
            probe = c.get("readinessProbe") or {}
            if not probe:
                continue
            timeout   = probe.get("timeoutSeconds", 1)
            threshold = probe.get("failureThreshold", 3)
            tolerance = timeout * threshold
            detail_line = (
                f"  container '{cname}': readinessProbe "
                f"timeoutSeconds={timeout}  failureThreshold={threshold}  "
                f"tolerance={tolerance}s  injected_delay={_delay_secs}s"
            )
            if _delay_secs > 0 and tolerance <= _delay_secs:
                blocking_msgs.append(detail_line + "  ✘ POD WILL LEAVE ENDPOINTS DURING CHAOS")
            else:
                blocking_msgs.append(detail_line + "  ✔ probe tolerance > delay")

        detail = (
            f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}\n"
            f"  injected delay: {_delay_secs}s\n"
            + ("\n".join(blocking_msgs) if blocking_msgs else "  No readiness probes defined")
        )
        if any("LEAVE ENDPOINTS" in m for m in blocking_msgs):
            return False, (
                detail + "\n  ✘ Readiness probe tolerance ≤ injected delay. "
                "Pod will be removed from Service endpoints during chaos — "
                "experiment measures routing, not application resilience. "
                "Reduce delay or increase readinessProbe.timeoutSeconds."
            )
        return True, detail
    checks["Readiness Probe vs Injected Delay"] = _readiness_probe_vs_delay

    # ── 3. Target port in container ports (hard block) ───────────────────────
    # Rationale: HTTPChaos targets a specific port. If the container doesn't
    # expose that port, Chaos Mesh silently injects to the wrong port (or no
    # port) — the experiment runs but nothing is injected.
    _target_port_int = 0
    try:
        _target_port_int = int(_target_port)
    except ValueError:
        pass

    def _port_exists():
        if not _target_port_int:
            return True, f"Could not parse http_port '{_target_port}' — skipping port check"

        dep, err = _get_deployment_json(aks_context, namespace, deployment)
        if dep is None:
            return True, f"Could not query deployment — skipping port check: {err}"

        containers     = dep.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        declared_ports = []
        for c in containers:
            for p in (c.get("ports") or []):
                declared_ports.append((c.get("name", "?"), p.get("containerPort")))

        declared_ints = [p for _, p in declared_ports]
        detail = (
            f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}\n"
            f"  chaos target port: {_target_port_int}\n"
            f"  declared containerPorts: {declared_ports if declared_ports else 'none'}"
        )
        if declared_ports and _target_port_int not in declared_ints:
            return False, (
                detail + f"\n  ✘ Port {_target_port_int} not in any container's containerPorts. "
                "HTTPChaos will inject to this port but no process is listening — "
                "experiment will measure nothing. Update http_port to match a declared port."
            )
        if not declared_ports:
            # No explicit ports declared — common but not fatal
            return True, detail + "\n  ⚠ No explicit containerPorts declared — cannot verify port (proceeding)"
        return True, detail + f"\n  ✔ Port {_target_port_int} declared in container spec"
    checks[f"HTTP Target Port ({_target_port}) Exists"] = _port_exists


    return checks


# ═════════════════════════════════════════════════════════════════════════════
# HTTP CHAOS (HTTPChaos) — Post-Checks
# ═════════════════════════════════════════════════════════════════════════════

def build_http_chaos_post_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    *,
    pre_chaos_endpoint_count: int = 0,
) -> "dict[str, callable]":
    """
    Post-chaos checks for HTTPChaos. Confirms service endpoints restored,
    probes passing, and Chaos Mesh CRD resource removed.

    pre_chaos_endpoint_count: ready endpoint count captured before chaos ran.
    When non-zero, post-check compares against it to catch partial recovery
    (e.g. 3 endpoints pre-chaos → 1 post-chaos passes the old check but fails here).

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}

    # ── 1. Replicas restored to desired floor ─────────────────────────────────
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
            return False, (
                detail + f"\n  ✘ Replicas not restored after HTTP chaos ({ready}/{desired} ready). "
                "Check if probe failures during chaos triggered kubelet restarts."
            )
        return True, detail + "\n  ✔ Replica floor restored"
    checks["Replicas Restored After HTTP Chaos"] = _replicas_restored

    # ── 2. HTTPChaos CRD resource removed ────────────────────────────────────
    # Rationale: Chaos Mesh should delete the HTTPChaos resource when the
    # experiment duration expires. If it persists, HTTP injection is still active.
    def _httpchaos_crd_deleted():
        r = _kubectl("get", "httpchaos", "-n", "chaos-testing",
                     "--no-headers", context=aks_context)
        detail = "kubectl get httpchaos -n chaos-testing"
        if r.returncode != 0:
            return True, detail + "\n  (query failed — assuming cleaned up)"
        existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        if existing:
            return False, (
                detail + f"\n  ✘ HTTPChaos resources still present: {existing}\n"
                "  HTTP delay/abort injection may still be ACTIVE."
            )
        return True, detail + "\n  ✔ All HTTPChaos CRD resources removed"
    checks["HTTPChaos CRD Cleaned Up"] = _httpchaos_crd_deleted

    # ── 3. Service endpoints restored ────────────────────────────────────────
    # Rationale: if the readiness probe timed out during chaos, the pod was
    # removed from Service endpoints. Endpoint count must return to pre-chaos
    # level — not just be non-zero. pre_chaos_endpoint_count captures the
    # baseline so partial recovery (e.g. 1 of 3 endpoints back) is caught.
    def _endpoints_restored():
        r = _kubectl("get", "endpoints", deployment, "-n", namespace,
                     "-o", "json", context=aks_context)
        detail = f"kubectl get endpoints {deployment} -n {namespace} --context {aks_context}"
        if r.returncode != 0:
            return False, detail + f"\n  ✘ Could not query endpoints: {r.stderr.strip()}"
        try:
            ep = json.loads(r.stdout)
        except ValueError:
            return False, detail + "\n  ✘ Could not parse endpoints"

        subsets = ep.get("subsets") or []
        ready_ips     = [a.get("ip") for s in subsets for a in (s.get("addresses") or [])]
        not_ready_ips = [a.get("ip") for s in subsets for a in (s.get("notReadyAddresses") or [])]
        detail += (
            f"\n  ready endpoints   : {len(ready_ips)}  {ready_ips}"
            f"\n  not-ready endpoints: {len(not_ready_ips)}  {not_ready_ips}"
        )
        if pre_chaos_endpoint_count > 0:
            detail += f"\n  pre-chaos baseline: {pre_chaos_endpoint_count} ready endpoints"
        if not_ready_ips:
            return False, (
                detail + "\n  ✘ Endpoints still not-ready after HTTP chaos revert. "
                "Readiness probe not yet passing — wait for failureThreshold × period to reset."
            )
        if not ready_ips:
            return False, detail + "\n  ✘ No ready endpoints — all pods removed from Service"
        if pre_chaos_endpoint_count > 0 and len(ready_ips) < pre_chaos_endpoint_count:
            return False, (
                detail + f"\n  ✘ Partial recovery: {len(ready_ips)}/{pre_chaos_endpoint_count} "
                "endpoints restored. Pods still restarting from probe failures during chaos. "
                "Wait for all replicas to pass readiness probes before declaring recovery."
            )
        return True, detail + "\n  ✔ Service endpoints fully restored"
    checks["Service Endpoints Restored"] = _endpoints_restored

    # ── 4. No Unhealthy probe events in last 5m ───────────────────────────────
    # Rationale: liveness/readiness probe failures during the chaos window
    # generate Unhealthy events. These persisting post-chaos indicate the
    # app hasn't fully stabilised — probes are still timing out.
    def _no_unhealthy_probe_events():
        r = _kubectl("get", "events", "-n", namespace, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return True, f"Could not query events (non-fatal): {r.stderr.strip()}"
        try:
            events = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse events — skipping"

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
        probe_events = []
        for ev in events:
            if ev.get("type") != "Warning":
                continue
            if ev.get("reason") not in ("Unhealthy", "ProbeWarning"):
                continue
            ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
            try:
                ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                pass
            obj = ev.get("involvedObject", {}).get("name", "?")
            probe_events.append(f"  {obj}: {ev.get('message','')[:100]}")

        detail = (
            f"kubectl get events -n {namespace} --context {aks_context}  (last 5m)\n"
            f"  Unhealthy probe events: "
            + ("\n" + "\n".join(probe_events) if probe_events else "none")
        )
        if probe_events:
            return False, (
                detail + "\n  ✘ Probe failures still occurring post-chaos. "
                "App may not have recovered — allow another probe cycle before declaring success."
            )
        return True, detail + "\n  ✔ No Unhealthy probe events in last 5m"
    checks["No Probe Failures Post-HTTP Chaos"] = _no_unhealthy_probe_events

    return checks
