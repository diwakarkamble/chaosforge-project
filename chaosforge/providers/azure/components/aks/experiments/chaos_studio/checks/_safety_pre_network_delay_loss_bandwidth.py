"""Steady-state checks for delay, packet-loss, and bandwidth NetworkChaos."""

import json

_IDS = frozenset({"aks-network-delay", "aks-packet-loss", "aks-bandwidth-limit"})


def build_pre_network_checks(experiment_id, aks_context, namespace, deployment,
                             label_key, label_val, selection_args, selection_display,
                             *, kubectl, find_svc_name):
    """Build checks while resolving safety.py seams when each closure runs."""
    if experiment_id not in _IDS or not namespace or not deployment:
        return {}

    def run(*args, **kwargs):
        return kubectl()(*args, **kwargs)

    def service():
        return find_svc_name()(namespace, label_key, label_val, deployment, aks_context)

    def first_pod():
        response = run("get", "pods", "-n", namespace, *selection_args, "-o", "json", context=aks_context)
        if response.returncode:
            return None
        try:
            pods = json.loads(response.stdout).get("items", [])
        except ValueError:
            return None
        return next((pod.get("metadata", {}).get("name") for pod in pods
                     if pod.get("status", {}).get("phase") == "Running"), None)

    def crd():
        detail = "kubectl get crd networkchaoses.chaos-mesh.org"
        if run("get", "crd", "networkchaoses.chaos-mesh.org", context=aks_context).returncode == 0:
            return True, detail + "\n  NetworkChaos CRD present"
        for args in (("get", "networkchaos", "--all-namespaces", "--no-headers"),
                     ("get", "networkchaos", "-n", "chaos-testing", "--no-headers")):
            if run(*args, context=aks_context).returncode == 0:
                return True, "kubectl " + " ".join(args) + "\n  NetworkChaos API available"
        return False, detail + "\n  NetworkChaos CRD not installed - experiment will silently no-op"

    def no_existing():
        detail = "kubectl get networkchaos -n chaos-testing"
        response = run("get", "networkchaos", "-n", "chaos-testing", "-o", "json", context=aks_context)
        if response.returncode:
            return True, detail + "\n  (query failed - assuming clean)"
        try:
            items = json.loads(response.stdout).get("items", [])
        except ValueError:
            return True, detail + "\n  (parse failed - assuming clean)"
        live = [item.get("metadata", {}).get("name", "?") for item in items if any(
            condition.get("type") == "AllInjected" and condition.get("status") == "True"
            for condition in item.get("status", {}).get("conditions", []))]
        if live:
            return False, detail + f"\n  Another network chaos experiment is actively injecting: {live}"
        if items:
            names = [item.get("metadata", {}).get("name", "?") for item in items]
            run("delete", "networkchaos", "--all", "-n", "chaos-testing", context=aks_context)
            return True, detail + f"\n  Stale NetworkChaos resources found and auto-deleted: {names}"
        return True, detail + "\n  No existing NetworkChaos resources"

    def no_tc_rule():
        pod = first_pod()
        detail = f"kubectl exec <pod> -n {namespace} -- tc qdisc show dev eth0"
        if not pod:
            return True, detail + "\n  (no running pod - skipping)"
        response = run("exec", pod, "-n", namespace, "--", "tc", "qdisc", "show", "dev", "eth0", context=aks_context)
        if response.returncode:
            return True, detail + "\n  (tc unavailable - skipping)"
        output = response.stdout.strip()
        stale = "netem" in output if experiment_id != "aks-bandwidth-limit" else "netem" in output or "tbf" in output
        if stale:
            return False, f"kubectl exec {pod} -n {namespace} -- tc qdisc show dev eth0\n  output: {output}\n  stale injection"
        return True, detail + "\n  No tc shaping rule on eth0"

    def endpoints():
        name, found = service()
        if not found:
            return True, f"No Service found for selector {label_key}={label_val} in '{namespace}'\n  (skipping endpoint check)"
        response = run("get", "endpoints", name, "-n", namespace, "-o", "json", context=aks_context)
        detail = f"kubectl get endpoints {name} -n {namespace} --context {aks_context}"
        if response.returncode:
            return True, detail + "\n  (endpoint query failed - skipping)"
        try:
            subsets = json.loads(response.stdout).get("subsets") or []
        except ValueError:
            return False, detail + "\n  Could not parse endpoints JSON"
        ready = [address.get("ip", "") for subset in subsets for address in subset.get("addresses") or []]
        if not ready:
            return False, detail + "\n  No ready endpoints - nothing to inject into"
        return True, detail + f"\n  ready endpoints: {len(ready)} {ready}"

    def probes():
        response = run("get", "deployment", deployment, "-n", namespace, "-o", "json", context=aks_context)
        detail = f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}"
        if response.returncode:
            return True, detail + "\n  (could not read deployment - skipping)"
        try:
            containers = json.loads(response.stdout).get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        except ValueError:
            return True, detail + "\n  (could not parse - skipping)"
        lines = [f"  container '{container.get('name', '?')}': readinessProbe.timeoutSeconds={container.get('readinessProbe', {}).get('timeoutSeconds', 1)}  livenessProbe.timeoutSeconds={container.get('livenessProbe', {}).get('timeoutSeconds', 1)}" for container in containers]
        return True, detail + "\n" + ("\n".join(lines) if lines else "  no containers found")

    def restart_baseline():
        response = run("get", "pods", "-n", namespace, *selection_args, "-o", "json", context=aks_context)
        detail = f"kubectl get pods -n {namespace} {selection_display} --context {aks_context}  (restart baseline)"
        if response.returncode:
            return True, detail + "\n  (kubectl failed - skipping)"
        try:
            pods = json.loads(response.stdout).get("items", [])
        except ValueError:
            return True, detail + "\n  (parse failed - skipping)"
        lines = [f"  {pod.get('metadata', {}).get('name', '?')}: restarts={sum(status.get('restartCount', 0) for status in pod.get('status', {}).get('containerStatuses', []))}" for pod in pods]
        return True, detail + "\n" + ("\n".join(lines) if lines else "  no pods found")

    def pod_exec(label, command, parser=None):
        pod = first_pod()
        detail = f"kubectl exec <pod> -n {namespace} -- {' '.join(command)}"
        if not pod:
            return True, detail + "\n  (no running pod - skipping)"
        response = run("exec", pod, "-n", namespace, "--", *command, context=aks_context)
        if response.returncode:
            return True, detail + "\n  (command unavailable - skipping)"
        return (parser(response.stdout) if parser else (True, detail + f"\n  {response.stdout.strip()}"))

    def dns_ip():
        response = run("get", "service", "kube-dns", "-n", "kube-system", "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
        return response.stdout.strip() if response.returncode == 0 and response.stdout.strip() else "10.0.0.10"

    def dns():
        pod = first_pod()
        if not pod:
            return True, f"kubectl exec <pod> -n {namespace} -- nslookup <service>\n  (no running pod - skipping)"
        name, found = service()
        if not found:
            return True, f"No Service found for selector {label_key}={label_val} in '{namespace}'\n  (DNS baseline is not applicable)"
        fqdn = f"{name}.{namespace}.svc.cluster.local"
        response = run("exec", pod, "-n", namespace, "--", "nslookup", fqdn, context=aks_context)
        return "Address" in response.stdout, f"Baseline DNS Resolution (UDP)\n  resolved={'Address' in response.stdout}"

    def http():
        name, found = service()
        if not found:
            return True, f"No Service found for selector {label_key}={label_val} in '{namespace}'\n  (HTTP baseline is not applicable)"
        return pod_exec("http", ("curl", "-o", "/dev/null", "-s", "-m", "5", "-w", "%{time_total}", f"http://{name}.{namespace}.svc.cluster.local"))

    checks = {"NetworkChaos CRD Installed": crd, "No Existing NetworkChaos": no_existing}
    if experiment_id == "aks-network-delay":
        checks.update({"No Existing tc-netem Rule": no_tc_rule, "Service Endpoints (baseline)": endpoints,
                       "Probe Timeouts vs Delay (impact analysis)": probes, "Baseline HTTP Response Time": http,
                       "Baseline Ping RTT": lambda: pod_exec("ping", ("ping", "-c", "3", "-W", "2", dns_ip())),
                       "Baseline DNS Resolution": dns, "Pod Restart Baseline": restart_baseline})
    elif experiment_id == "aks-packet-loss":
        checks.update({"No Existing tc-netem Rule": no_tc_rule, "Service Endpoints (baseline)": endpoints,
                       "Probe Timeouts vs Packet Loss (impact analysis)": probes,
                       "TCP Retransmit Baseline (/proc/net/snmp)": lambda: pod_exec("tcp", ("cat", "/proc/net/snmp")),
                       "Baseline HTTP Response Time": http, "Baseline DNS Resolution (UDP)": dns,
                       "Pod Restart Baseline": restart_baseline})
    else:
        checks.update({"No Existing tc Rule (tbf/netem)": no_tc_rule, "Service Endpoints (baseline)": endpoints,
                       "Probe Timeouts vs Bandwidth Cap (impact analysis)": probes,
                       "Baseline Throughput (KB/s)": lambda: pod_exec("throughput", ("curl", "-o", "/dev/null", "-s", "-m", "10", "-w", "%{size_download} %{time_total} %{speed_download}", f"http://{deployment}.{namespace}.svc.cluster.local")),
                       "Baseline HTTP Response Time": http,
                       "Baseline Ping RTT (should stay stable)": lambda: pod_exec("ping", ("ping", "-c", "5", "-W", "2", dns_ip())),
                       "Pod Restart Baseline": restart_baseline, "Baseline DNS Resolution": dns})
    return checks
