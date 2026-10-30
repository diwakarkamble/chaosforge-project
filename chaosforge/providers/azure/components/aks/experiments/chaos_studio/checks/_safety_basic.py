"""Dependency-injected implementations for basic AKS safety checks."""

import json

PROTECTED_NAMESPACES = frozenset({
    "kube-system", "kube-public", "kube-node-lease",
    "chaos-testing", "chaos-mesh", "chaos-engine",
    "cert-manager", "azure-arc", "gatekeeper-system",
    "monitoring", "prometheus", "istio-system", "linkerd",
})


def is_true(value):
    """chaostoolkit passes --var values as strings — normalize truthy ones."""
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def check_protected_namespace(namespace):
    """Refuse to run against system/infrastructure namespaces."""
    if namespace and namespace.lower() in PROTECTED_NAMESPACES:
        raise RuntimeError(
            f"Namespace '{namespace}' is protected and cannot be targeted by "
            f"chaos experiments. Protected namespaces: {sorted(PROTECTED_NAMESPACES)}"
        )


def check_deployment_replica_floor(context, namespace, deployment, min_replicas, owning_deployment, kubectl):
    """Require sufficient desired and ready replicas for a target."""
    r = kubectl("get", "deployment", deployment, "-n", namespace, "-o", "json", context=context)
    if r.returncode == 0:
        try:
            dep = json.loads(r.stdout)
        except ValueError as exc:
            raise RuntimeError(f"Could not parse deployment '{deployment}': {exc}")
        desired = dep.get("spec", {}).get("replicas") or 0
        ready = dep.get("status", {}).get("readyReplicas") or 0
        target_kind = "Deployment"
    else:
        rp = kubectl("get", "pod", deployment, "-n", namespace, "-o", "json", context=context)
        if rp.returncode != 0:
            if owning_deployment and owning_deployment != deployment:
                return check_deployment_replica_floor(
                    context, namespace, owning_deployment, min_replicas, "", kubectl
                )
            raise RuntimeError(
                f"Could not find a Deployment or Pod named '{deployment}' in "
                f"namespace '{namespace}': {rp.stderr.strip() or r.stderr.strip()}"
            )
        try:
            pod = json.loads(rp.stdout)
        except ValueError as exc:
            raise RuntimeError(f"Could not parse pod '{deployment}': {exc}")
        conditions = pod.get("status", {}).get("conditions", [])
        is_ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
        desired = 1
        ready = 1 if (pod.get("status", {}).get("phase") == "Running" and is_ready) else 0
        target_kind = "Pod"
    if desired < min_replicas:
        raise RuntimeError(
            f"{target_kind} '{deployment}' has only {desired} desired replica(s). "
            f"Minimum required for chaos: {min_replicas}. Scale the deployment before running chaos experiments."
            if target_kind == "Deployment" else
            f"{target_kind} '{deployment}' is a standalone pod with no redundancy "
            f"(minimum required for chaos: {min_replicas}). Killing it has no fallback."
        )
    if ready < min_replicas:
        raise RuntimeError(
            f"{target_kind} '{deployment}' has only {ready} ready replica(s) "
            f"(desired: {desired}). Minimum required: {min_replicas}. "
            "Wait for it to stabilise before running chaos."
        )


def check_pdb_allows_disruption(context, namespace, label_key, label_val, kubectl):
    if not label_key or not label_val:
        return
    r = kubectl("get", "pdb", "-n", namespace, "-o", "json", context=context)
    if r.returncode != 0:
        return
    try:
        pdbs = json.loads(r.stdout).get("items", [])
    except ValueError:
        return
    for pdb in pdbs:
        match_labels = pdb.get("spec", {}).get("selector", {}).get("matchLabels") or {}
        if match_labels.get(label_key) != label_val:
            continue
        status = pdb.get("status", {})
        allowed = status.get("disruptionsAllowed")
        if allowed is not None and allowed < 1:
            name = pdb.get("metadata", {}).get("name", "unknown")
            raise RuntimeError(
                f"PodDisruptionBudget '{name}' in namespace '{namespace}' currently "
                f"allows 0 disruptions. Current healthy pods: {status.get('currentHealthy')}, "
                f"desired healthy: {status.get('desiredHealthy')}. Wait for the deployment to have "
                "enough healthy replicas before running chaos."
            )


def check_chaos_mesh_running(context, chaos_mesh_namespace, kubectl):
    def ready_pods(namespace):
        r = kubectl("get", "pods", "-n", namespace, "-l", "app.kubernetes.io/component=controller-manager", "-o", "json", context=context)
        if r.returncode != 0:
            return None
        try:
            pods = json.loads(r.stdout).get("items", [])
        except ValueError:
            return None
        return [
            pod.get("metadata", {}).get("name") for pod in pods
            if pod.get("status", {}).get("phase") == "Running"
            and any(c.get("type") == "Ready" and c.get("status") == "True" for c in pod.get("status", {}).get("conditions", []))
        ]
    pods = ready_pods(chaos_mesh_namespace)
    if pods is None:
        pods = ready_pods("chaos-mesh")
    if not pods:
        raise RuntimeError(
            "Chaos Mesh controller-manager is not running or not ready. "
            "Chaos Studio experiments delegate fault delivery to Chaos Mesh — if Chaos Mesh is unhealthy, "
            "Azure will report 'Succeeded' while no "
            f"fault is injected. Check: kubectl get pods -n {chaos_mesh_namespace} --context {context}"
        )


def check_nodes_ready(context, min_ready, kubectl):
    r = kubectl("get", "nodes", "-o", "json", context=context)
    if r.returncode != 0:
        raise RuntimeError(f"Could not list nodes (context={context}): {r.stderr.strip()}")
    try:
        nodes = json.loads(r.stdout).get("items", [])
    except ValueError as exc:
        raise RuntimeError(f"Could not parse node list: {exc}")
    ready_count = 0
    for node in nodes:
        taint_keys = {t.get("key", "") for t in node.get("spec", {}).get("taints") or []}
        if "node-role.kubernetes.io/control-plane" in taint_keys or "node-role.kubernetes.io/master" in taint_keys:
            continue
        if any(c.get("type") == "Ready" and c.get("status") == "True" for c in node.get("status", {}).get("conditions", [])):
            ready_count += 1
    if ready_count < min_ready:
        raise RuntimeError(
            f"Only {ready_count} worker node(s) are Ready (minimum required: {min_ready}). "
            "Cluster is not in a stable state — do not start a chaos experiment now."
        )


def check_system_pods_running(context, kubectl):
    for component, labels, required in [
        ("CoreDNS", ["k8s-app=kube-dns"], True),
        ("kube-proxy", ["k8s-app=kube-proxy", "component=kube-proxy"], False),
    ]:
        pods = None
        query_failed = False
        for label in labels:
            r = kubectl("get", "pods", "-n", "kube-system", "-l", label, "-o", "json", context=context)
            if r.returncode != 0:
                query_failed = True
                continue
            query_failed = False
            try:
                pods = json.loads(r.stdout).get("items", [])
            except ValueError:
                pods = []
            if pods:
                break
        if query_failed and not pods:
            if required:
                raise RuntimeError(f"Could not query {component} pods in kube-system (context={context}).")
            print(f"[probe] WARNING: Could not query {component} pods — skipping (non-fatal)")
            continue
        if not pods:
            if required:
                raise RuntimeError(f"No {component} pods found in kube-system (context={context}). Cluster infrastructure appears unhealthy — aborting.")
            print(f"[probe] INFO: No {component} pods found in kube-system — this is normal for some AKS configurations")
            continue
        running = [p for p in pods if p.get("status", {}).get("phase") == "Running" and any(c.get("type") == "Ready" and c.get("status") == "True" for c in p.get("status", {}).get("conditions", []))]
        if not running:
            names = [p.get("metadata", {}).get("name", "?") for p in pods]
            if required:
                raise RuntimeError(f"{component} pods are not Ready in kube-system: {names}. Cluster infrastructure appears unhealthy — aborting.")
            print(f"[probe] WARNING: {component} pods exist but not Ready: {names}")


def get_pods_for_deployment(context, namespace, deployment, owning_deployment, kubectl):
    r = kubectl("get", "deployment", deployment, "-n", namespace, "-o", "json", context=context)
    if r.returncode == 0:
        try:
            labels = json.loads(r.stdout).get("spec", {}).get("selector", {}).get("matchLabels", {})
            if labels:
                selector = ",".join(f"{key}={value}" for key, value in labels.items())
                rp = kubectl("get", "pods", "-l", selector, "-n", namespace, "-o", "json", context=context)
                if rp.returncode == 0:
                    return json.loads(rp.stdout).get("items", [])
        except (ValueError, KeyError):
            pass
    rp = kubectl("get", "pod", deployment, "-n", namespace, "-o", "json", context=context)
    if rp.returncode == 0:
        try:
            return [json.loads(rp.stdout)]
        except ValueError:
            pass
    if owning_deployment and owning_deployment != deployment:
        return get_pods_for_deployment(context, namespace, owning_deployment, "", kubectl)
    return []


def snapshot_pod_health(pods):
    snap = {}
    for pod in pods:
        name = pod["metadata"]["name"]
        status = pod.get("status", {})
        container_state, waiting_reason, restarts = "Unknown", "", 0
        for cs in status.get("containerStatuses", []):
            restarts += cs.get("restartCount", 0)
            state = cs.get("state", {})
            if "running" in state:
                container_state = "Running"
            elif "waiting" in state:
                container_state, waiting_reason = "Waiting", state["waiting"].get("reason", "")
            elif "terminated" in state:
                container_state = "Terminated"
        snap[name] = {"ready": any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions", [])), "phase": status.get("phase", "Unknown"), "container_state": container_state, "waiting_reason": waiting_reason, "restarts": restarts}
    return snap


def check_app_stability(context, namespace, deployment, stability_secs, owning_deployment, get_pods, snapshot, console, sleep):
    pods = get_pods(context, namespace, deployment, owning_deployment)
    if not pods:
        console.print(f"  [bold red]✗[/bold red] Could not find pods for '{deployment}' in '{namespace}'")
        return False, f"No pods found for {deployment}"
    snap0 = snapshot(pods)
    total = len(snap0)
    total_restarts = sum(p["restarts"] for p in snap0.values())
    has_restarts = total_restarts > 0
    snap1, restart_count_changing = snap0, False
    if has_restarts and stability_secs > 0:
        console.print(
            f"  [dim]ℹ Pre-existing container restarts detected — waiting {stability_secs}s "
            "to confirm the restart count is stable before proceeding...[/dim]"
        )
        sleep(stability_secs)
        pods1 = get_pods(context, namespace, deployment, owning_deployment)
        snap1 = snapshot(pods1) if pods1 else snap0
        restart_count_changing = any(info1 and info1["restarts"] > info0["restarts"] for name, info0 in snap0.items() if (info1 := snap1.get(name)))
    ready_count_final = sum(1 for p in snap1.values() if p["ready"])
    total_restarts_final = sum(p["restarts"] for p in snap1.values())
    crashloop_pods_final = [n for n, p in snap1.items() if p["waiting_reason"] == "CrashLoopBackOff"]
    running_not_ready = [n for n, p in snap1.items() if p["phase"] == "Running" and not p["ready"]]
    states = [p["container_state"] for p in snap1.values()]
    container_state_display = "Waiting" if "Waiting" in states else "Terminated" if "Terminated" in states else "Running" if "Running" in states else states[0] if states else "Unknown"
    readiness_pass = ready_count_final == total and not running_not_ready
    reasons = []
    if restart_count_changing:
        increasing = [n for n, p in snap1.items() if n in snap0 and p["restarts"] > snap0[n]["restarts"]]
        reasons.append(f"Restarts increasing: {sum(snap0[n]['restarts'] for n in increasing if n in snap0)} → {sum(snap1[n]['restarts'] for n in increasing if n in snap1)} (pods: {', '.join(increasing)})")
    if ready_count_final < total:
        reasons.append(f"Ready: {ready_count_final}/{total}")
    if crashloop_pods_final:
        reasons.append(f"CrashLoopBackOff: {', '.join(crashloop_pods_final)}")
    if running_not_ready:
        reasons.append(f"Running but not Ready: {', '.join(running_not_ready)}")
    healthy = not reasons
    w = 54
    console.print(f"  {'┌─ PRE-CHAOS HEALTH CHECK ' + '─' * (w - 25) + '┐'}")
    def row(label, value, color=None):
        line = f"│  {label:<26}{value}"
        console.print(f"  [{color}]{line}[/{color}]" if color else f"  {line}")
    row("Deployment:", deployment); row("Namespace:", namespace); console.print("  │")
    row("Pods:", f"{ready_count_final}/{total} Ready"); row("Restarts detected:", "YES" if has_restarts else "NO")
    if has_restarts:
        row("Restart count:", str(total_restarts_final)); row("Restart count changing:", "YES" if restart_count_changing else "NO", "red" if restart_count_changing else None)
    row("Readiness:", "PASS" if readiness_pass else "FAIL", None if readiness_pass else "red")
    row("Container state:", container_state_display); row("CrashLoopBackOff:", "YES" if crashloop_pods_final else "NO", "red" if crashloop_pods_final else None); console.print("  │")
    if healthy:
        console.print("  │  [bold green]Overall Application Health: ✓ HEALTHY → proceeding[/bold green]")
    else:
        console.print("  │  [bold red]Overall Application Health: ✗ UNHEALTHY → blocking chaos[/bold red]")
        for reason in reasons:
            console.print(f"  │    [red]- {reason}[/red]")
    console.print(f"  {'└' + '─' * w + '┘'}")
    return healthy, "HEALTHY" if healthy else "; ".join(reasons)


def probe_aks_target_healthy(aks_context, namespace, deployment, owning_deployment, check_floor, check_app, check_nodes, check_system):
    if not namespace or not deployment:
        try:
            check_nodes(aks_context, min_ready=1); check_system(aks_context)
        except RuntimeError as exc:
            print(f"[probe] Cluster-level steady-state check failed: {exc}")
            return False
        print("[probe] Cluster-level steady-state OK (nodes ready, system pods running)")
        return True
    try:
        check_floor(aks_context, namespace, deployment, min_replicas=1, owning_deployment=owning_deployment)
    except RuntimeError as exc:
        print(f"[probe] Replica floor check failed: {exc}")
        return False
    healthy, detail = check_app(aks_context, namespace, deployment, owning_deployment=owning_deployment)
    if not healthy:
        print(f"[probe] Application health check failed: {detail}")
    return healthy


def verify_rollback_health(aks_context, namespace, deployment, dry_run, owning_deployment, is_dry_run, check_app, check_nodes, check_system):
    if is_dry_run(dry_run):
        print("[verify-rollback] Dry run — nothing was injected, skipping post-rollback verification.")
        return True
    if namespace and deployment:
        healthy, detail = check_app(aks_context, namespace, deployment, stability_secs=0, owning_deployment=owning_deployment)
        if not healthy:
            raise RuntimeError(f"Rollback ran, but target '{deployment}' in namespace '{namespace}' is still not healthy afterwards — manual intervention required. ({detail})")
    else:
        try:
            check_nodes(aks_context, min_ready=1); check_system(aks_context)
        except RuntimeError as exc:
            raise RuntimeError("Rollback ran, but cluster-level health checks failed afterwards (nodes or system pods not Ready) — manual intervention required. (" + str(exc) + ")") from exc
    print(f"[verify-rollback] Target '{deployment}' in namespace '{namespace}' is healthy after rollback." if namespace and deployment else "[verify-rollback] Cluster-level health checks passed after rollback.")
    return True
