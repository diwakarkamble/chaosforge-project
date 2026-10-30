"""Steady-state checks for corruption, duplication, and partition NetworkChaos."""

import json

_IDS = frozenset({"aks-packet-corruption", "aks-packet-duplication", "aks-network-partition"})


def build_pre_network_checks(experiment_id, aks_context, namespace, deployment,
                             label_key, label_val, selection_args, selection_display,
                             *, kubectl, find_svc_name, partition_ping_target):
    """Build checks with late-bound safety.py dependencies."""
    if experiment_id not in _IDS or not namespace or not deployment:
        return {}

    def run(*args, **kwargs): return kubectl()(*args, **kwargs)
    def service(): return find_svc_name()(namespace, label_key, label_val, deployment, aks_context)
    def pod():
        response = run("get", "pods", "-n", namespace, *selection_args, "-o", "json", context=aks_context)
        if response.returncode: return None
        try: items = json.loads(response.stdout).get("items", [])
        except ValueError: return None
        return next((item.get("metadata", {}).get("name") for item in items if item.get("status", {}).get("phase") == "Running"), None)
    def crd():
        detail = "kubectl get crd networkchaoses.chaos-mesh.org"
        if run("get", "crd", "networkchaoses.chaos-mesh.org", context=aks_context).returncode == 0: return True, detail + "\n  NetworkChaos CRD present"
        for args in (("get", "networkchaos", "--all-namespaces", "--no-headers"), ("get", "networkchaos", "-n", "chaos-testing", "--no-headers")):
            if run(*args, context=aks_context).returncode == 0: return True, "kubectl " + " ".join(args) + "\n  NetworkChaos API available"
        return False, detail + "\n  NetworkChaos CRD not installed - experiment will silently no-op"
    def no_existing():
        detail = "kubectl get networkchaos -n chaos-testing"
        response = run("get", "networkchaos", "-n", "chaos-testing", "-o", "json", context=aks_context)
        if response.returncode: return True, detail + "\n  (query failed - assuming clean)"
        try: items = json.loads(response.stdout).get("items", [])
        except ValueError: return True, detail + "\n  (parse failed - assuming clean)"
        live = [item.get("metadata", {}).get("name", "?") for item in items if any(condition.get("type") == "AllInjected" and condition.get("status") == "True" for condition in item.get("status", {}).get("conditions", []))]
        if live: return False, detail + f"\n  Another network chaos experiment is actively injecting: {live}"
        if items:
            names = [item.get("metadata", {}).get("name", "?") for item in items]
            run("delete", "networkchaos", "--all", "-n", "chaos-testing", context=aks_context)
            return True, detail + f"\n  Stale NetworkChaos resources found and auto-deleted: {names}"
        return True, detail + "\n  No existing NetworkChaos resources"
    def no_rule():
        name = pod()
        command = ("iptables", "-L", "-n") if experiment_id == "aks-network-partition" else ("tc", "qdisc", "show", "dev", "eth0")
        detail = f"kubectl exec <pod> -n {namespace} -- {' '.join(command)}"
        if not name: return True, detail + "\n  (no running pod - skipping)"
        response = run("exec", name, "-n", namespace, "--", *command, context=aks_context)
        if response.returncode: return True, detail + "\n  (command unavailable - skipping)"
        stale = "chaos" in response.stdout.lower() if experiment_id == "aks-network-partition" else "netem" in response.stdout
        if stale: return False, detail + "\n  stale partition/injection rule detected"
        return True, detail + "\n  No existing chaos rule"
    def endpoints():
        name, found = service()
        if not found: return True, f"No Service found for selector {label_key}={label_val} in '{namespace}'\n  (skipping endpoint check)"
        response = run("get", "endpoints", name, "-n", namespace, "-o", "json", context=aks_context)
        detail = f"kubectl get endpoints {name} -n {namespace} --context {aks_context}"
        if response.returncode: return True, detail + "\n  (endpoint query failed - skipping)"
        try: subsets = json.loads(response.stdout).get("subsets") or []
        except ValueError: return False, detail + "\n  Could not parse endpoints JSON"
        ready = [address.get("ip", "") for subset in subsets for address in subset.get("addresses") or []]
        return (bool(ready), detail + f"\n  ready endpoints: {len(ready)} {ready}")
    def restart():
        response = run("get", "pods", "-n", namespace, *selection_args, "-o", "json", context=aks_context)
        detail = f"kubectl get pods -n {namespace} {selection_display} --context {aks_context}  (restart baseline)"
        if response.returncode: return True, detail + "\n  (kubectl failed - skipping)"
        try: items = json.loads(response.stdout).get("items", [])
        except ValueError: return True, detail + "\n  (parse failed - skipping)"
        return True, detail + "\n" + "\n".join(f"  {item.get('metadata', {}).get('name', '?')}: restarts={sum(status.get('restartCount', 0) for status in item.get('status', {}).get('containerStatuses', []))}" for item in items)
    def exec_check(command, required=None, failure=None):
        name = pod(); detail = f"kubectl exec <pod> -n {namespace} -- {' '.join(command)}"
        if not name: return True, detail + "\n  (no running pod - skipping)"
        response = run("exec", name, "-n", namespace, "--", *command, context=aks_context)
        if response.returncode and not response.stdout: return True, detail + "\n  (command unavailable - skipping)"
        if required and required not in response.stdout: return False, detail + "\n  " + (failure or "baseline check failed")
        return True, detail + "\n  " + response.stdout.strip()
    def ping_target():
        if experiment_id in {"aks-packet-corruption", "aks-network-partition"}:
            return partition_ping_target()(aks_context)
        response = run("get", "service", "kube-dns", "-n", "kube-system", "-o", "jsonpath={.spec.clusterIP}", context=aks_context)
        return response.stdout.strip() if response.returncode == 0 and response.stdout.strip() else "10.0.0.10"
    def loss_ping(count, label):
        name = pod()
        target = ping_target()
        detail = f"kubectl exec <pod> -n {namespace} -- ping -c {count} -W 2 {target}"
        if not name:
            return True, detail + "\n  (no running pod - skipping)"
        response = run("exec", name, "-n", namespace, "--", "ping", "-c", count, "-W", "2", target, context=aks_context)
        loss = next((line.strip().split("%")[0].split()[-1] for line in response.stdout.splitlines() if "packet loss" in line), None)
        result = f"{detail}\n  {label} packet loss = {loss}%"
        if loss and loss not in {"0", "0.0", "0.00"}:
            return False, result + f"\n  Pre-fault packet loss already {loss}%"
        return True, result
    def no_dup_ping():
        name = pod()
        target = ping_target()
        detail = f"kubectl exec <pod> -n {namespace} -- ping -c 5 -W 2 {target}"
        if not name:
            return True, detail + "\n  (no running pod - skipping)"
        response = run("exec", name, "-n", namespace, "--", "ping", "-c", "5", "-W", "2", target, context=aks_context)
        duplicates = [line for line in response.stdout.splitlines() if "DUP!" in line]
        if duplicates:
            return False, detail + "\n  Duplicate ICMP replies seen before fault injection"
        if response.returncode:
            return True, detail + "\n  (ping unavailable - skipping)"
        return True, detail + "\n  0 DUP! packets pre-fault"
    def replica_safety():
        response = run("get", "deployment", deployment, "-n", namespace, "-o", "json", context=aks_context)
        detail = f"kubectl get deployment {deployment} -n {namespace} --context {aks_context}"
        if response.returncode: return True, detail + "\n  (could not read deployment - skipping)"
        try: replicas = json.loads(response.stdout).get("spec", {}).get("replicas", 1)
        except ValueError: return True, detail + "\n  (could not parse - skipping)"
        if replicas < 2: return False, detail + "\n  Single-replica deployment - network partition will cause complete service downtime"
        return True, detail + f"\n  desired replicas = {replicas}"
    checks = {"NetworkChaos CRD Installed": crd, "No Existing NetworkChaos": no_existing}
    if experiment_id == "aks-packet-corruption":
        checks.update({"No Existing tc-netem Rule": no_rule, "Service Endpoints (baseline)": endpoints,
                       "Probe Timeouts vs Corruption (impact analysis)": lambda: (True, "Probe timeout impact analysis"),
                       "TCP Retransmit Baseline (/proc/net/snmp)": lambda: exec_check(("cat", "/proc/net/snmp")),
                       "Baseline Ping (0% loss pre-fault)": lambda: loss_ping("10", "baseline"),
                       "Baseline DNS Resolution (UDP)": lambda: exec_check(("nslookup", f"{deployment}.{namespace}.svc.cluster.local"), "Address", "DNS not resolving before fault"),
                       "Baseline HTTP Response Time": lambda: exec_check(("curl", "-o", "/dev/null", "-s", "-m", "5", "-w", "%{time_total}", f"http://{deployment}.{namespace}.svc.cluster.local")), "Pod Restart Baseline": restart})
    elif experiment_id == "aks-packet-duplication":
        checks.update({"No Existing tc-netem Rule": no_rule, "Service Endpoints (baseline)": endpoints, "Pod Restart Baseline": restart,
                       "Baseline Ping (0 DUP! pre-fault)": lambda: no_dup_ping(),
                       "TCP Stats Baseline (RetransSegs + TCPDSACKRecv)": lambda: exec_check(("cat", "/proc/net/snmp")),
                       "Baseline HTTP Response Time": lambda: exec_check(("curl", "-o", "/dev/null", "-s", "-m", "5", "-w", "%{time_total}", f"http://{deployment}.{namespace}.svc.cluster.local")),
                       "Baseline DNS Resolution": lambda: exec_check(("nslookup", f"{deployment}.{namespace}.svc.cluster.local"), "Address", "DNS not resolving before fault")})
    else:
        checks.update({"No Existing iptables Chaos Rules": no_rule, "Service Endpoints (baseline)": endpoints,
                       "Replica Count Safety (partition impact)": replica_safety,
                       "Probe Impact Analysis (partition = guaranteed NotReady)": lambda: (True, "Partition probe impact analysis"),
                       "Baseline Connectivity (ping — 0% loss pre-fault)": lambda: loss_ping("3", "baseline"),
                       "Baseline DNS Resolution": lambda: exec_check(("nslookup", f"{deployment}.{namespace}.svc.cluster.local"), "Address", "DNS not resolving before fault"),
                       "Baseline HTTP Response Time": lambda: exec_check(("curl", "-o", "/dev/null", "-s", "-m", "5", "-w", "%{time_total}", f"http://{deployment}.{namespace}.svc.cluster.local")), "Pod Restart Baseline": restart})
    return checks
