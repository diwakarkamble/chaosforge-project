"""Extracted implementation helpers for the AKS Chaos Studio executor."""

from typing import Any

from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    CHAOS_MESH_VERSION,
    ChaosMeshInstaller,
)
from chaosforge.engines.chaos_mesh.version_policy import assess_installer

from .execution_support import executor_compatible

datetime: Any = None
json: Any = None
os: Any = None
re: Any = None
subprocess: Any = None
time: Any = None
timezone: Any = None
CHAOS_NAMESPACE: Any = None
EXPERIMENT_SPECS: Any = None
NETWORK_CHAOS_EXPERIMENTS: Any = None
POD_PINNING_CAPABLE_EXPERIMENTS: Any = None
SPEC_DIR: Any = None
TIME_CHAOS_EXPERIMENTS: Any = None
verify_fault_active: Any = None
_capture_missing_net_baseline: Any = None
_extract_net_metrics: Any = None
_kubectl: Any = None
_normalize_time_offset: Any = None
_save_state_field: Any = None
azure_cli_command: Any = None


def _build_spec(experiment_id, ctx):
    """
    Load JSON spec file, substitute placeholders, return (spec_dict, json_spec_str, kind).
    JSON spec files are pre-converted from YAML — same structure AWS uses for its experiments.
    """
    spec_file = EXPERIMENT_SPECS.get(experiment_id)
    if not spec_file:
        raise ValueError(f"No spec file for: {experiment_id}")

    path = os.path.join(SPEC_DIR, spec_file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Spec not found: {path}")

    with open(path) as f:
        raw = f.read()

    # NOTE: use `or` rather than dict.get() defaults — the campaign/experiment JSON
    # always supplies these keys, but often as empty strings (""). A .get(k, default)
    # only falls back when the key is ABSENT, so an empty label_key would render
    # `labelSelectors: {"": ""}`, which Chaos Mesh rejects with
    # "cannot parse label selector" and the fault silently selects zero pods.
    label_key    = ctx.get("label_key") or "app"
    label_val    = ctx.get("label_val") or ctx.get("deployment") or ""
    chaos_mode   = ctx.get("chaos_mode", "one")
    chaos_val    = str(ctx.get("chaos_value", "")).strip()
    duration_s   = int(ctx.get("duration", 60))
    duration_str = f"{duration_s}s"
    time_offset  = str(ctx.get("time_offset", "")).strip()

    if experiment_id in TIME_CHAOS_EXPERIMENTS:
        time_offset = _normalize_time_offset(experiment_id, time_offset)
        if not time_offset:
            direction = "positive" if experiment_id == "aks-clock-skew-forward" else "negative"
            raise ValueError(
                f"Time offset must be {direction} or unsigned, such as 5m, 10s, or 1h"
            )

    # Substitute placeholders in the raw JSON string
    raw = raw.replace("<target-namespace>",        ctx.get("namespace") or "default")
    # Only substitute app label placeholders when present — avoids mangling kube-system specs
    if "<app-label>" in raw:
        raw = raw.replace('"app": "<app-label>"', f'"{label_key}": "{label_val}"')
        raw = raw.replace('"<app-label>"',          f'"{label_val}"')
    raw = raw.replace("<container-name>",          ctx.get("container_name") or "app")
    # DNSChaos spec ships with a bare wildcard "*" pattern as its safe default
    # (matches nothing meaningful until overridden — extended checks hard-block
    # an unreplaced bare "*" so the operator must supply a real domain).
    # Only touch the DNS spec's own "patterns" array — a blind string replace of
    # `"*"` would also corrupt unrelated IOChaos/HTTPChaos "path": "*" fields.
    dns_pattern_value = (ctx.get("dns_pattern") or "").strip()
    if dns_pattern_value:
        raw = re.sub(
            r'"patterns"\s*:\s*\[\s*"\*"\s*\]',
            f'"patterns": ["{dns_pattern_value}"]',
            raw,
        )
    raw = raw.replace('"/data"',                   f'"{ctx.get("volume_path") or "/data"}"')
    raw = raw.replace('"mode": "one"',             f'"mode": "{chaos_mode}"')
    raw = raw.replace('"<duration>"',              f'"{duration_str}"')

    spec = json.loads(raw)
    if experiment_id in TIME_CHAOS_EXPERIMENTS:
        spec["timeOffset"] = time_offset
    kind = spec.pop("kind", "")

    # If the selector-scope validator (Phase 2 pre-check) determined that the naive
    # label selector above would also match sibling Deployments' pods, it saves a
    # corrected multi-key selector to state as "label_selectors_map". When present,
    # it replaces the naive single-key labelSelectors so the fault only ever reaches
    # the pods the operator actually selected. Absent for the common case (no label
    # collision) — behavior there is identical to before.
    label_selectors_map = ctx.get("label_selectors_map")
    if label_selectors_map and "selector" in spec and "labelSelectors" in spec["selector"]:
        spec["selector"]["labelSelectors"] = label_selectors_map

    # Network Partition (and only Network Partition) ships a SECOND selector
    # block at spec["target"]["selector"] — this is the "other side" of the
    # partition (mode "all", matching every peer pod the source pod is being
    # isolated from). Every other network-chaos spec (delay/loss/bandwidth/
    # corruption/duplication) has just the one top-level "selector", so this
    # block is a no-op for them. Without this, a label collision correction
    # applied to the source selector above was silently NOT mirrored onto the
    # target selector, so the target side kept the naive, over-matching label
    # and could pull sibling Deployments' pods into the fault as real Chaos
    # Mesh targets (confirmed via status.experiment.podRecords in a live run).
    if (
        label_selectors_map
        and isinstance(spec.get("target"), dict)
        and "selector" in spec["target"]
        and "labelSelectors" in spec["target"]["selector"]
    ):
        spec["target"]["selector"]["labelSelectors"] = label_selectors_map

    exact_pod_name = ctx.get("exact_pod_name")
    if experiment_id in POD_PINNING_CAPABLE_EXPERIMENTS and ctx.get("target_mode") == "pod":
        if not exact_pod_name:
            raise ValueError(
                "Pod target mode requires an exact pod name resolved during pre-checks; "
                "refusing to fall back to a broad label selector."
            )
        selector_spec = spec.setdefault("selector", {})
        selector_spec.pop("labelSelectors", None)
        selector_spec["fieldSelectors"] = {"metadata.name": exact_pod_name}
        spec["mode"] = "one"
        spec.pop("value", None)

    # Fail fast on an unusable label selector. Chaos Mesh rejects empty/blank label
    # keys with "cannot parse label selector" but still reports the experiment as
    # started — the CRD sits at Selected=False and injects nothing, which looks like
    # a successful no-op run. Surfacing it here turns a silent false-negative into
    # an actionable error.
    _sel = (spec.get("selector") or {}).get("labelSelectors")
    if isinstance(_sel, dict) and _sel:
        _bad = [k for k in _sel if not str(k).strip()]
        if _bad:
            raise ValueError(
                f"Invalid labelSelectors for {experiment_id}: {_sel!r}. "
                "Label keys must be non-empty — Chaos Mesh would reject this selector "
                "and inject nothing (Selected=False). Check that label_key/label_val "
                "(or deployment) are populated in the experiment context."
            )

    # Inject value field when chaos_mode needs it
    if chaos_val and not (
        experiment_id in POD_PINNING_CAPABLE_EXPERIMENTS
        and ctx.get("target_mode") == "pod"
    ):
        spec["value"] = chaos_val

    # ── Network chaos — override spec values from user input when provided ────
    # Falls back to the hardcoded spec defaults when the user leaves the field empty.
    if experiment_id == "aks-network-delay":
        latency = str(ctx.get("latency", "")).strip()
        jitter  = str(ctx.get("jitter",  "")).strip()
        corr    = str(ctx.get("correlation", "")).strip()
        if latency:
            spec.setdefault("delay", {})["latency"] = latency
        if jitter:
            spec.setdefault("delay", {})["jitter"] = jitter
        if corr:
            spec.setdefault("delay", {})["correlation"] = corr

    elif experiment_id == "aks-packet-loss":
        loss_pct = str(ctx.get("loss_percentage", "")).strip()
        corr     = str(ctx.get("correlation", "")).strip()
        if loss_pct:
            spec.setdefault("loss", {})["loss"] = loss_pct
        if corr:
            spec.setdefault("loss", {})["correlation"] = corr

    elif experiment_id == "aks-bandwidth-limit":
        rate = str(ctx.get("rate", "")).strip()
        if rate:
            spec.setdefault("bandwidth", {})["rate"] = rate

    elif experiment_id == "aks-packet-corruption":
        corrupt_pct = str(ctx.get("corrupt_percentage", "")).strip()
        corr        = str(ctx.get("correlation", "")).strip()
        if corrupt_pct:
            spec.setdefault("corrupt", {})["corrupt"] = corrupt_pct
        if corr:
            spec.setdefault("corrupt", {})["correlation"] = corr

    elif experiment_id == "aks-packet-duplication":
        dup_pct = str(ctx.get("duplicate_percentage", "")).strip()
        corr    = str(ctx.get("correlation", "")).strip()
        if dup_pct:
            spec.setdefault("duplicate", {})["duplicate"] = dup_pct
        if corr:
            spec.setdefault("duplicate", {})["correlation"] = corr

    # ── Disk I/O chaos — override spec values from user input when provided ──
    # IOChaos specs carry these as flat top-level fields (not a nested
    # "delay"/"loss"-style sub-object like NetworkChaos), so they're set
    # directly on spec. Falls back to the spec defaults (100ms / EIO / 50%)
    # when the corresponding field is left blank. Isolated to these two
    # experiment IDs only — no effect on any other experiment type.
    elif experiment_id == "aks-io-latency":
        io_delay_val = str(ctx.get("io_delay", "")).strip()
        io_pct_val   = str(ctx.get("io_percent", "")).strip()
        if io_delay_val:
            spec["delay"] = io_delay_val
        if io_pct_val:
            spec["percent"] = int(io_pct_val)

    elif experiment_id == "aks-io-errors":
        io_errno_val = str(ctx.get("io_errno", "")).strip()
        io_pct_val   = str(ctx.get("io_percent", "")).strip()
        if io_errno_val:
            spec["errno"] = int(io_errno_val)
        if io_pct_val:
            spec["percent"] = int(io_pct_val)

    # Substitute container name in containerNames list if present
    if "containerNames" in spec:
        spec["containerNames"] = [
            ctx.get("container_name", c) if c == "<container-name>" else c
            for c in spec["containerNames"]
        ]

    # Studio's jsonSpec must NOT include 'duration' — it's controlled by ContinuousAction.
    # Keep it in spec dict for _apply_direct (direct Chaos Mesh kubectl path).
    studio_spec = {k: v for k, v in spec.items() if k != "duration"}
    return spec, json.dumps(studio_spec, separators=(",", ":")), kind


def _az_rest_put(url, label, session=None):
    """Run 'az rest PUT url' and raise RuntimeError with a clear message on failure."""
    import time as _t
    if session:
        session.log_event("experiment-setup", f"PUT {label} — start")
    t0 = _t.monotonic()
    try:
        r = subprocess.run(
            azure_cli_command("rest", "--method", "put", "--url", url, "--body", '{"properties":{}}'),
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        if session:
            session.log_event("experiment-setup", f"PUT {label} — TIMED OUT after 30s")
        raise RuntimeError(
            f"Timed out (30s) registering {label} — az rest PUT did not respond.\n"
            "Check Azure connectivity and authentication."
        )
    elapsed = _t.monotonic() - t0
    if session:
        session.log_event(
            "experiment-setup",
            f"PUT {label} — {'OK' if r.returncode == 0 else 'FAILED'}  {elapsed:.1f}s"
            + (f"  error={r.stderr.strip()[:120]}" if r.returncode != 0 else ""),
        )
    if r.returncode != 0:
        raise RuntimeError(
            f"Azure Chaos Studio registration failed for {label}.\n"
            f"Command: az rest --method put --url {url}\n"
            f"Error  : {r.stderr.strip() or r.stdout.strip()}\n"
            "Check that:\n"
            "  • The Microsoft.Chaos resource provider is registered in this subscription\n"
            "  • Your identity has 'Contributor' on the target resource\n"
            "  • The AKS cluster name, resource group, and subscription ID are correct"
        )


def _setup_studio_target(
    subscription_id, rg, aks_name, aks_context="", ui=None, session=None,
    chaos_mesh_version_action="", chaos_mesh_installed_version="",
):
    import concurrent.futures as _cf
    def _step(msg): ui and ui.step(msg, live=True)
    def _log(msg):  session and session.log_event("experiment-setup", msg)

    base = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/resourceGroups/{rg}"
        f"/providers/Microsoft.ContainerService/managedClusters/{aks_name}"
        f"/providers/Microsoft.Chaos/targets/Microsoft-AzureKubernetesServiceChaosMesh"
    )
    api = "?api-version=2024-01-01"

    _step("Registering Microsoft.Chaos provider (idempotent)...")
    _log("az provider register --namespace Microsoft.Chaos — start")
    try:
        pr = subprocess.run(
            azure_cli_command("provider", "register", "--namespace", "Microsoft.Chaos"),
            capture_output=True, timeout=60,
        )
        _log(f"az provider register — rc={pr.returncode}"
             + (f"  warning={pr.stderr.strip()[:120]}" if pr.returncode != 0 else ""))
    except subprocess.TimeoutExpired:
        _log("WARNING: az provider register timed out after 60s — continuing")

    # Target resource must exist before capabilities — register it first, serially.
    _step(f"Registering AKS Chaos Studio target ({aks_name})...")
    _az_rest_put(f"{base}{api}", f"AKS target ({aks_name})", session=session)

    # Capabilities are independent of each other — register them in parallel.
    # If Azure throttles concurrent PUTs the calls will still succeed (idempotent);
    # if any fail we collect all errors and raise together so nothing is silently skipped.
    CAPABILITIES = [
        "PodChaos-2.2", "NetworkChaos-2.2", "StressChaos-2.2",
        "IOChaos-2.2",  "TimeChaos-2.2",    "HTTPChaos-2.2",   "DNSChaos-2.2",
    ]
    _step(f"Registering {len(CAPABILITIES)} capabilities in parallel...")
    _log(f"Parallel capability registration: {CAPABILITIES}")

    errors = []

    def _register_cap(cap):
        try:
            _az_rest_put(f"{base}/capabilities/{cap}{api}", f"capability {cap}", session=session)
        except RuntimeError as exc:
            errors.append(str(exc))

    with _cf.ThreadPoolExecutor(max_workers=len(CAPABILITIES)) as pool:
        list(pool.map(_register_cap, CAPABILITIES))

    if errors:
        raise RuntimeError(
            "One or more capability registrations failed:\n" + "\n".join(errors)
        )

    _step(f"All {len(CAPABILITIES)} capabilities registered")
    _ensure_chaos_mesh_in_chaos_testing(
        ui=ui,
        session=session,
        aks_context=aks_context,
        action=chaos_mesh_version_action,
        expected_installed_version=chaos_mesh_installed_version or None,
    )


def _ensure_chaos_mesh_in_chaos_testing(
    ui=None, session=None, aks_context="", action="", expected_installed_version=None
):
    def _step(msg): ui and ui.step(msg, live=True)
    def _log(msg):  session and session.log_event("experiment-setup", msg)

    installer = ChaosMeshInstaller(
        release_name="chaos-mesh-studio",
        namespace=CHAOS_NAMESPACE,
        kube_context=aks_context or None,
        timeout="5m",
    )
    assessment = assess_installer(installer, "azure", aks_context or "AKS")
    if assessment.installed_version != expected_installed_version:
        if not (
            assessment.state in {"current", "newer"}
            and expected_installed_version in {None, assessment.installed_version}
        ):
            raise RuntimeError(
                "The installed Chaos Mesh version changed after campaign review. Review the campaign again."
            )
    if assessment.state in {"current", "newer"}:
        _log(assessment.message)
        return
    if assessment.blocked:
        raise RuntimeError(assessment.message)
    if action == "continue" and assessment.state == "older":
        _log(assessment.message + " Continuing by campaign decision.")
        return
    if action == "upgrade" and assessment.state == "older":
        _step(f"Upgrading Chaos Mesh to {CHAOS_MESH_VERSION} (helm)...")
        result = installer.upgrade()
        if result.status == "BLOCKED":
            raise RuntimeError(result.message)
        return
    if action != "install" or assessment.state != "absent":
        raise RuntimeError("A reviewed Chaos Mesh install or upgrade decision is required.")

    _log("Chaos Mesh Helm release not found — proceeding with installation")
    _step(f"Installing Chaos Mesh into {CHAOS_NAMESPACE} namespace (helm)...")

    _kubectl("create", "namespace", CHAOS_NAMESPACE)

    _log("helm get values chaos-mesh — start")
    vals = subprocess.run(
        ["helm", "get", "values", "chaos-mesh", "-n", "chaos-mesh", "--output", "json"],
        capture_output=True, text=True)
    _log(f"helm get values — rc={vals.returncode}")

    extra = []
    if vals.returncode == 0:
        try:
            d = json.loads(vals.stdout).get("chaosDaemon", {})
            if d.get("runtime"):
                extra += ["--set", f"chaosDaemon.runtime={d['runtime']}"]
            if d.get("socketPath"):
                extra += ["--set", f"chaosDaemon.socketPath={d['socketPath']}"]
        except Exception:
            pass
    if not extra:
        extra = ["--set", "chaosDaemon.runtime=containerd",
                 "--set", "chaosDaemon.socketPath=/run/containerd/containerd.sock"]

    # AKS system nodepools taint themselves CriticalAddonsOnly:NoSchedule.
    # Without a matching toleration chaos-daemon is silently never scheduled
    # there, so StressChaos/IOChaos against system-nodepool-hosted workloads
    # (CoreDNS, kube-proxy) fails with "cannot find daemonIP on node ..." for
    # the whole run while pod-kill (k8s API only) keeps working — masking it.
    extra += [
        "--set", "chaosDaemon.tolerations[0].key=CriticalAddonsOnly",
        "--set", "chaosDaemon.tolerations[0].operator=Exists",
        "--set", "chaosDaemon.tolerations[0].effect=NoSchedule",
    ]

    _log(f"helm upgrade --install chaos-mesh-studio — start  extra={extra}")
    try:
        hi = subprocess.run(
            ["helm", "upgrade", "--install", "chaos-mesh-studio", "chaos-mesh/chaos-mesh",
             "--namespace", CHAOS_NAMESPACE, "--version", CHAOS_MESH_VERSION,
             "--set", "controllerManager.replicaCount=1",
             "--timeout", "5m"] + extra,
            capture_output=True, timeout=360,
        )
        _log(
            f"helm install — rc={hi.returncode}"
            + (f"  stdout={hi.stdout.strip()[:200]}" if hi.stdout.strip() else "")
            + (f"  stderr={hi.stderr.strip()[:200]}" if hi.stderr.strip() else "")
        )
        if hi.returncode != 0:
            raise RuntimeError(
                f"helm upgrade --install chaos-mesh-studio failed (rc={hi.returncode}):\n"
                f"{hi.stderr.strip() or hi.stdout.strip()}"
            )
    except subprocess.TimeoutExpired:
        _log("helm install timed out after 360s")
        raise RuntimeError("helm install chaos-mesh-studio timed out after 6 minutes")


def _get_chaos_identity_id(subscription_id, rg):
    r = subprocess.run(
        azure_cli_command("identity", "show", "--name", "chaos-studio-identity",
         "--resource-group", rg, "--query", "id", "-o", "tsv"),
        capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return (f"/subscriptions/{subscription_id}/resourceGroups/{rg}"
            f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/chaos-studio-identity")


def _seconds_to_iso8601(seconds):
    """Convert integer seconds to ISO 8601 duration string for Azure Chaos Studio."""
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    result = "PT"
    if hours:
        result += f"{hours}H"
    if minutes:
        result += f"{minutes}M"
    if secs or result == "PT":
        result += f"{secs}S"
    return result


def _build_studio_experiment_object(json_spec, capability_urn, sub, rg, cluster, ctx):
    """Build the Azure SDK Experiment object. Pure construction, no network calls."""
    from azure.mgmt.chaos.models import (
        ChaosExperimentBranch,
        ChaosExperimentStep,
        ChaosTargetListSelector,
        ContinuousAction,
        Experiment,
        KeyValuePair,
        ManagedServiceIdentity,
        ManagedServiceIdentityType,
        TargetReference,
        TargetReferenceType,
    )
    duration_secs = int(ctx.get("duration", 60))
    iso_duration  = _seconds_to_iso8601(duration_secs)
    aks_id        = (f"/subscriptions/{sub}/resourceGroups/{rg}"
                     f"/providers/Microsoft.ContainerService/managedClusters/{cluster}")
    identity      = _get_chaos_identity_id(sub, rg)

    return Experiment(
        location=ctx.get("location") or "westeurope",
        identity=ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={identity: {}}
        ),
        steps=[ChaosExperimentStep(name="Step1", branches=[
            ChaosExperimentBranch(name="Branch1", actions=[
                ContinuousAction(
                    name=capability_urn, duration=iso_duration,
                    parameters=[KeyValuePair(key="jsonSpec", value=json_spec)],
                    selector_id="sel1"
                )
            ])
        ])],
        selectors=[ChaosTargetListSelector(
            id="sel1",
            targets=[TargetReference(
                type=TargetReferenceType.CHAOS_TARGET,
                id=f"{aks_id}/providers/Microsoft.Chaos/targets/Microsoft-AzureKubernetesServiceChaosMesh"
            )]
        )]
    )


def _precreate_studio_experiment(exp_name, json_spec, capability_urn,
                                  sub, chaos_rg, cluster, ctx, *, ui=None, session=None):
    """
    Create the Studio experiment ARM resource during setup so the cost is paid
    before phase 4. Only begin_create_or_update is called here — begin_start
    is called later in _run_studio_experiment when the operator is ready.

    chaos_rg  — dedicated experiments RG where the ARM resource is placed
    cluster_rg — cluster RG used for identity + AKS target selector lookups
    """
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.chaos import ChaosManagementClient

    cluster_rg = ctx.get("resource_group", chaos_rg)
    client     = ChaosManagementClient(DefaultAzureCredential(), sub)
    experiment = _build_studio_experiment_object(json_spec, capability_urn, sub, cluster_rg, cluster, ctx)
    client.experiments.begin_create_or_update(chaos_rg, exp_name, experiment).result()
    if ui:
        ui.step(f"Studio experiment ARM resource created: {exp_name}", live=True)


def _target_selection_preview(target_pods, chaos_mode, chaos_value):
    """
    Build start-banner rows for Chaos Mesh selector modes.

    For random modes (one/fixed value below matching pod count), Azure/Chaos Mesh
    chooses the concrete pod at runtime, so listing every matching pod as
    "selected" is misleading.
    """
    total = len(target_pods)
    if not total:
        return [], []

    mode = str(chaos_mode or "one").strip().lower()
    value = str(chaos_value or "").strip()

    if mode == "all":
        return target_pods, []

    if mode == "one":
        return [], [f"1 pod will be randomly selected by Chaos Mesh from {total} matching pod(s)"]

    if mode == "fixed":
        try:
            fixed_count = int(value)
        except ValueError:
            fixed_count = 0
        if fixed_count > 0 and fixed_count < total:
            return [], [f"{fixed_count} pod(s) will be randomly selected by Chaos Mesh from {total} matching pod(s)"]
        if fixed_count >= total:
            return target_pods, []

    if value:
        return [], [f"selector matched {total} pod(s); Chaos Mesh mode={mode}, value={value}"]

    return [], [f"selector matched {total} pod(s); Chaos Mesh mode={mode}"]


def _extract_chaos_target_pods(crds):
    """Return unique pod names recorded by Chaos Mesh CRD status."""
    targeted = []
    for crd in crds or []:
        experiment = crd.get("status", {}).get("experiment", {})
        records = (
            experiment.get("containerRecords")
            or experiment.get("podRecords")
            or experiment.get("records")
            or []
        )
        if isinstance(records, dict):
            records = [{"id": record_id} for record_id in records]
        for record in records:
            record_id = (
                record.get("id")
                or record.get("podName")
                or record.get("name")
                or ""
            ) if isinstance(record, dict) else str(record)
            parts = [part for part in record_id.split("/") if part]
            if not parts:
                continue
            # containerRecords use namespace/pod/container; podRecords use namespace/pod.
            pod_name = parts[-2] if len(parts) >= 3 else parts[-1]
            if pod_name and pod_name not in targeted:
                targeted.append(pod_name)
    return targeted


def _read_chaos_target_pods(crd_kind, aks_context):
    """Read the actual runtime-selected pods from Chaos Mesh status."""
    result = _kubectl("get", crd_kind, "-n", CHAOS_NAMESPACE,
                      "-o", "json", context=aks_context, timeout=10)
    if result.returncode != 0:
        return []
    try:
        return _extract_chaos_target_pods(json.loads(result.stdout).get("items", []))
    except ValueError:
        return []


def _read_restart_total(namespace, selector, aks_context, exact_pod_name=""):
    """Return the cumulative restart count for the selector, or None."""
    selection_args = (
        ["--field-selector", f"metadata.name={exact_pod_name}"]
        if exact_pod_name else ["-l", selector]
    )
    result = _kubectl("get", "pods", "-n", namespace, *selection_args,
                      "-o", "json", context=aks_context, timeout=10)
    if result.returncode != 0:
        return None
    try:
        return sum(
            status.get("restartCount", 0)
            for pod in json.loads(result.stdout).get("items", [])
            for status in pod.get("status", {}).get("containerStatuses", [])
        )
    except ValueError:
        return None


def _read_io_baseline_ms(namespace, selector, aks_context, volume_path="/data"):
    """
    Run one write+read+delete round-trip probe against the target's mount
    path before the fault starts, so the in-fault live probe and the final
    impact summary have a genuine "before" number to compare against —
    mirrors _read_restart_total's baseline-capture role for IOChaos.
    Returns elapsed milliseconds, or None if no running pod / probe fails.
    """
    import time as _time

    result = _kubectl("get", "pods", "-n", namespace, "-l", selector, "-o", "json",
                      context=aks_context, timeout=10)
    if result.returncode != 0:
        return None
    try:
        pods = json.loads(result.stdout).get("items", [])
    except ValueError:
        return None
    pod_name = next(
        (p.get("metadata", {}).get("name") for p in pods
         if p.get("status", {}).get("phase") == "Running"),
        None,
    )
    if not pod_name:
        return None
    _vpath = (volume_path or "/data").rstrip("/") or "/"
    from .checks._extended_common import _find_writable_probe_location
    _cname, _ppath = _find_writable_probe_location(aks_context, namespace, pod_name, _vpath)
    _ppath = _ppath or _vpath
    _c_args = ("-c", _cname) if _cname else ()
    _probe_file = f"{_ppath}/.chaosforge_io_probe_baseline"
    t0 = _time.monotonic()
    r = _kubectl(
        "exec", pod_name, "-n", namespace, *_c_args, "--", "sh", "-c",
        f"date +%s%3N > '{_probe_file}' && cat '{_probe_file}' >/dev/null && rm -f '{_probe_file}'",
        context=aks_context, timeout=10,
    )
    elapsed_ms = int((_time.monotonic() - t0) * 1000)
    if r.returncode != 0:
        return None
    return elapsed_ms



from . import studio_runtime as _studio_runtime

_run_studio_experiment = _studio_runtime._LOCAL_EXPORTS["_run_studio_experiment"]
_get_experiment_failure_detail = _studio_runtime._LOCAL_EXPORTS["_get_experiment_failure_detail"]

_EXPORTED_FUNCTIONS = (
    "_build_spec",
    "_az_rest_put",
    "_setup_studio_target",
    "_ensure_chaos_mesh_in_chaos_testing",
    "_get_chaos_identity_id",
    "_seconds_to_iso8601",
    "_build_studio_experiment_object",
    "_precreate_studio_experiment",
    "_target_selection_preview",
    "_extract_chaos_target_pods",
    "_read_chaos_target_pods",
    "_read_restart_total",
    "_read_io_baseline_ms",
    "_run_studio_experiment",
    "_get_experiment_failure_detail",
)

_LOCAL_EXPORTS = {}
_LOCAL_EXPORTS.update(
    {name: executor_compatible(globals()[name]) for name in _EXPORTED_FUNCTIONS}
)
__all__ = list(_EXPORTED_FUNCTIONS)
