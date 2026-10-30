"""
Azure AKS Service
Collects inputs for AKS experiments using live kubectl/az discovery.
Follows the same pattern as generic_service.py but with Azure-specific
resource types: aks_cluster, aks_namespace, aks_deployment, aks_container.
"""

import re
from copy import deepcopy

from chaosforge.application.campaigns.builder import build_experiment
from chaosforge.application.experiment_descriptions import get_experiment_description
from chaosforge.application.metadata import get_experiment
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import title
from chaosforge.interfaces.cli.interactive.ui.prompts import pause, prompt
from chaosforge.interfaces.cli.interactive.ui.status import (
    error,
    info,
    success,
    warning,
)
from chaosforge.interfaces.cli.session import context
from chaosforge.providers.azure.components.aks.discovery import AzureAKSDiscovery

CHAOS_MODES = [
    ("one",                "Randomly pick ONE pod (safe default)"),
    ("all",                "Target ALL matching pods"),
    ("fixed",              "Target exact NUMBER of pods"),
    ("fixed-percent",      "Target a PERCENTAGE of pods (e.g. 50)"),
    ("random-max-percent", "Target UP TO a percentage randomly"),
]

TIME_OFFSET_PATTERN = re.compile(r"^[+-]?[1-9][0-9]*(?:s|m|h)$")


def _normalize_time_offset(experiment_id, value):
    if not TIME_OFFSET_PATTERN.fullmatch(value):
        return None
    if value[0] in "+-":
        if experiment_id == "aks-clock-skew-forward" and value[0] != "+":
            return None
        if experiment_id == "aks-clock-skew-backward" and value[0] != "-":
            return None
        return value
    sign = "-" if experiment_id == "aks-clock-skew-backward" else "+"
    return f"{sign}{value}"


class _BackStep(Exception):
    """Raised when user enters 0 to go back one step."""


def _empty_result_choice(message, retry_label="Select a different namespace"):
    """Show a warning that a selection stage returned no results, and let the
    user choose to retry a previous step or return to the main menu — instead
    of silently exiting. Raises _BackStep to retry, or BackToMainMenu to exit.
    """
    warning(message)
    console.print()
    console.print(f"  [cyan]1.[/cyan] {retry_label}")
    console.print("  [cyan]0.[/cyan] Return to Main Menu")
    console.print()
    while True:
        choice = prompt(">").strip().lower()
        if choice == "1":
            raise _BackStep
        if choice in ("0", "m"):
            raise BackToMainMenu
        error("Invalid selection")


def _dead_end(message):
    """Show a warning for a case with no reasonable retry step (e.g. the
    cluster itself has zero namespaces, or no cluster is configured at all),
    then return to the main menu after the user acknowledges it."""
    warning(message)
    pause()
    raise BackToMainMenu


def _pick(label, items, default=None, default_display=None):
    """Numbered list picker with optional search. 0=back, s=search, m=main menu."""
    active = items
    while True:
        console.print()
        console.print(f"[bold cyan]{label}[/bold cyan]")
        if active is not items:
            console.print(f"  [bright_black](filtered: {len(active)} of {len(items)})[/bright_black]")
        console.print()
        for i, item in enumerate(active, start=1):
            console.print(f"  [cyan]{i}.[/cyan] {item}")
        console.print()
        console.print(
            "  [cyan]0.[/cyan] Back  [bright_black]|[/bright_black]  [cyan]s.[/cyan] Search"
        )
        if default is not None:
            console.print(
                f"[bright_black]Default : {default_display or default}[/bright_black]"
            )
        console.print()
        choice = prompt(">").strip()
        if choice == "" and default is not None:
            return default
        if choice.lower() == "m":
            raise BackToMainMenu
        if choice == "0":
            if active is not items:
                active = items
                continue
            raise _BackStep
        if choice.lower() == "s":
            term = prompt("Search").strip().lower()
            filtered = [x for x in items if term in x.lower()]
            if not filtered:
                error(f"No matches for '{term}'")
                continue
            active = filtered
            continue
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(active):
                return active[idx]
        except ValueError:
            pass
        error("Invalid selection")


def _collect_aks_inputs(metadata):
    """
    Collect all inputs for an AKS experiment using live discovery.
    Supports 0=back at every step. Returns a variables dict.
    """
    discovery = AzureAKSDiscovery()
    variables = {}
    fields     = metadata.get("inputs", [])
    idx        = 0

    # Tracks whether user chose "by deployment" or "by pod" after namespace
    # None = not yet chosen, "deployment" or "pod" = chosen
    target_mode = None

    title(metadata["name"])

    while idx < len(fields):
        field = fields[idx]
        name  = field["name"]
        ftype = field.get("type", "text")

        if any(
            variables.get(condition) != expected
            for condition, expected in field.get("visible_when", {}).items()
        ):
            idx += 1
            continue

        # Skip fields already populated by a previous field handler
        if name in variables:
            idx += 1
            continue

        try:
            # ── AKS Cluster ──────────────────────────────────────────
            # Cluster/subscription/resource-group are fixed for the whole
            # session via PlatformSelector's Azure setup flow — no longer
            # asked per experiment.
            if ftype == "azure_aks_cluster":
                if not context.aks_kube_context:
                    _dead_end(
                        "No AKS cluster configured. Return to the service menu "
                        "and set up an AKS cluster before running this experiment."
                    )
                variables[name] = context.aks_kube_context
                variables["subscription_id"] = context.azure_subscription or ""
                variables["resource_group"] = context.azure_resource_group or ""
                variables["aks_name"] = context.aks_cluster_name or ""
                if context.azure_location:
                    variables["location"] = context.azure_location

            # ── Node ─────────────────────────────────────────────────
            elif ftype == "azure_aks_node":
                ctx = variables.get("aks_context", "")
                nodes = discovery.list_nodes(ctx)
                if not nodes:
                    _dead_end(f"No worker nodes found in cluster context: {ctx}")
                variables[name] = _pick("Select Target Node", nodes)

            # ── Zone ─────────────────────────────────────────────────
            elif ftype == "azure_aks_zone":
                ctx = variables.get("aks_context", "")
                zones = discovery.list_zones(ctx)
                if not zones:
                    _dead_end(f"No availability zones found in cluster context: {ctx}")
                chosen_zone = _pick("Select Availability Zone", zones)
                variables[name] = chosen_zone
                # Store all nodes in that zone as comma-separated target_node
                zone_nodes = discovery.list_nodes_in_zone(ctx, chosen_zone)
                variables["target_node"] = ",".join(zone_nodes)
                info(f"Zone {chosen_zone}: {len(zone_nodes)} node(s) — {', '.join(zone_nodes)}")

            # ── Namespace ────────────────────────────────────────────
            elif ftype == "azure_aks_namespace":
                ctx = variables.get("aks_context", "")
                namespaces = discovery.list_namespaces(ctx)
                if not namespaces:
                    discovery_error = getattr(discovery, "last_error", None)
                    if discovery_error:
                        _dead_end(
                            f"Namespace discovery failed. {discovery_error}\n"
                            "Verify the kubeconfig context, cluster connectivity, "
                            "Azure credentials, and permission to list namespaces."
                        )
                    _dead_end(f"This cluster has no namespaces (context: {ctx}).")
                variables[name] = _pick("Select Namespace", namespaces)

                # After namespace: target mode → pod/deployment selection
                # 0 at target mode  → re-ask namespace (continue outer loop at same idx)
                # 0 at pod list     → re-ask target mode
                try:
                    while True:
                        target_mode = _pick(
                            "Select Target Mode",
                            [
                                "By Deployment  — target pods via deployment label selector",
                                "By Pod         — target a single specific pod directly",
                            ]
                        )
                        target_mode = "deployment" if target_mode.startswith("By Deployment") else "pod"
                        variables["target_mode"] = target_mode

                        if target_mode == "pod":
                            ctx  = variables.get("aks_context", "")
                            ns   = variables.get("namespace", "")
                            pods = discovery.list_pods(ctx, ns)
                            if not pods:
                                _empty_result_choice(
                                    f"Namespace '{ns}' has no running pods.",
                                    retry_label="Select a different namespace",
                                )
                            try:
                                chosen_pod = _pick("Select Pod", pods)
                            except _BackStep:
                                # 0 at pod list → re-ask target mode
                                continue
                            lkey, lval = discovery.get_pod_label(ctx, ns, chosen_pod)
                            owning_dep = discovery.get_deployment_for_pod(ctx, ns, chosen_pod)
                            variables["deployment"]  = chosen_pod
                            variables["pod"]         = chosen_pod
                            variables["label_key"]   = lkey
                            variables["label_val"]   = lval
                            variables["pod_count"]   = 1
                            variables["target_mode"] = "pod"
                            variables["owning_deployment"] = owning_dep or ""
                            info(f"Pod selector: {lkey}={lval}  (1 pod)")
                        break
                except _BackStep:
                    # 0 at target mode → clear namespace, re-ask namespace
                    variables.pop(name, None)
                    target_mode = None
                    continue  # outer while loop, re-runs namespace at same idx

            # ── Deployment ───────────────────────────────────────────
            elif ftype == "azure_aks_deployment":
                ctx = variables.get("aks_context", "")
                ns  = variables.get("namespace", "")
                deployments = discovery.list_deployments(ctx, ns)
                if not deployments:
                    _empty_result_choice(
                        f"Namespace '{ns}' has no deployments.",
                        retry_label="Select a different namespace",
                    )
                dep = _pick("Select Deployment", deployments)
                variables[name] = dep
                lkey, lval = discovery.get_label_selector(ctx, ns, dep)
                pod_count  = discovery.get_pod_count(ctx, ns, lkey, lval)
                variables["label_key"] = lkey
                variables["label_val"] = lval
                variables["pod_count"] = pod_count
                if pod_count > 1:
                    info(f"Pod selector: {lkey}={lval}  ({pod_count} pods — auto-scoped if collision detected)")
                else:
                    info(f"Pod selector: {lkey}={lval}  (1 pod)")

            # ── Container ────────────────────────────────────────────
            elif ftype == "azure_aks_container":
                ctx = variables.get("aks_context", "")
                ns  = variables.get("namespace", "")
                dep = variables.get("deployment", "")
                if target_mode == "pod":
                    containers = discovery.list_pod_containers(ctx, ns, dep)
                else:
                    containers = discovery.list_containers(ctx, ns, dep)
                if not containers:
                    warning("Could not detect containers. Enter name manually.")
                    value = prompt("Container name (0 Back) >").strip()
                    if value == "0":
                        raise _BackStep
                    if value.lower() == "m":
                        raise BackToMainMenu
                    variables[name] = value
                elif len(containers) == 1:
                    variables[name] = containers[0]
                    info(f"Container: {containers[0]} (auto-detected)")
                else:
                    variables[name] = _pick("Select Container", containers)

            # ── Time Offset ──────────────────────────────────────────
            elif ftype == "time_offset":
                default = field.get("default", "")
                console.print()
                console.print(f"[bold cyan]{field['label']}[/bold cyan]")
                if default != "":
                    console.print(f"[bright_black]Default : {default}[/bright_black]")
                console.print("  [cyan]0.[/cyan] Back")
                console.print()
                while True:
                    val = prompt(">").strip()
                    if val == "0":
                        raise _BackStep
                    if val.lower() == "m":
                        raise BackToMainMenu
                    if val == "":
                        val = default
                    normalized = _normalize_time_offset(metadata["id"], val)
                    if normalized:
                        variables[name] = normalized
                        break
                    direction = "positive" if metadata["id"] == "aks-clock-skew-forward" else "negative"
                    error(f"Enter a {direction} offset, or omit the sign, such as 5m, 10s, or 1h")

            # ── Chaos Mode ───────────────────────────────────────────
            elif ftype == "chaos_mode":
                # Skip when targeting a specific pod — always "one"
                if target_mode == "pod":
                    variables[name] = "one"
                    variables["chaos_value"] = ""
                    info("Chaos mode: one (auto-set for single pod target)")
                    idx += 1
                    continue
                pod_count = variables.get("pod_count", 0)
                info(f"Pods matching selector: {pod_count}")
                mode_labels = [f"{m}  — {desc}" for m, desc in CHAOS_MODES]
                default_mode = field.get("default")
                default_label = next(
                    (label for label in mode_labels if label.startswith(f"{default_mode}  ")),
                    None,
                )
                chosen_label = _pick(
                    "Select Chaos Mode",
                    mode_labels,
                    default=default_label,
                    default_display=default_mode,
                )
                mode = chosen_label.split()[0]
                variables[name] = mode
                # Set chaos_value here so the next field is skipped
                if mode in ("fixed", "fixed-percent", "random-max-percent"):
                    hints = {
                        "fixed":              f"How many pods to target (max {pod_count})",
                        "fixed-percent":      "Percentage of pods to target (1-100)",
                        "random-max-percent": "Max percentage of pods (1-100)",
                    }
                    while True:
                        raw_val = prompt(hints[mode]).strip()
                        if raw_val == "0":
                            variables.pop(name, None)
                            variables.pop("chaos_value", None)
                            raise _BackStep
                        if raw_val.lower() == "m":
                            raise BackToMainMenu
                        try:
                            ival = int(raw_val)
                        except ValueError:
                            error("Enter a whole number")
                            continue
                        if mode == "fixed":
                            if ival < 1:
                                error("Value must be at least 1")
                                continue
                            if pod_count and ival > pod_count:
                                error(f"Value cannot exceed pod count ({pod_count})")
                                continue
                        else:
                            if not (1 <= ival <= 100):
                                error("Percentage must be between 1 and 100")
                                continue
                        variables["chaos_value"] = str(ival)
                        break
                else:
                    variables["chaos_value"] = ""

            # ── Integer ──────────────────────────────────────────────
            elif ftype == "integer":
                default = field.get("default", "")
                minimum = field.get("min", "")
                maximum = field.get("max", "")
                console.print()
                console.print(f"[bold cyan]{field['label']}[/bold cyan]")
                if default != "":
                    console.print(f"[bright_black]Default : {default}[/bright_black]")
                if minimum != "" or maximum != "":
                    console.print(f"[bright_black]Allowed Range : {minimum} - {maximum}[/bright_black]")
                console.print("  [cyan]0.[/cyan] Back")
                console.print()
                while True:
                    val = prompt(">").strip()
                    if val == "0":
                        raise _BackStep
                    if val.lower() == "m":
                        raise BackToMainMenu
                    if val == "" and default != "":
                        variables[name] = default
                        break
                    try:
                        ival = int(val)
                        if minimum != "" and ival < int(minimum):
                            error(f"Value must be >= {minimum}")
                            continue
                        if maximum != "" and ival > int(maximum):
                            error(f"Value must be <= {maximum}")
                            continue
                        variables[name] = ival
                        break
                    except ValueError:
                        error("Enter a valid integer")

            # ── Text / default ───────────────────────────────────────
            else:
                default  = field.get("default", "")
                required = field.get("required", True)
                console.print()
                console.print(f"[bold cyan]{field['label']}[/bold cyan]")
                if default != "":
                    console.print(f"[bright_black]Default : {default}[/bright_black]")
                console.print("  [cyan]0.[/cyan] Back")
                console.print()
                while True:
                    val = prompt(">").strip()
                    if val == "0":
                        raise _BackStep
                    if val.lower() == "m":
                        raise BackToMainMenu
                    if val == "" and default != "":
                        variables[name] = default
                        break
                    elif val == "" and not required:
                        variables[name] = ""
                        break
                    elif val == "" and required:
                        error("This field is required")
                    else:
                        variables[name] = val
                        break

            idx += 1

        except _BackStep:
            if name == "container_name" and target_mode == "pod":
                # Pod selection is nested under the namespace step. Re-enter that
                # flow so Back returns to a valid target selector, not deployments.
                target_mode = None
                for key in (
                    "namespace", "target_mode", "deployment", "pod", "label_key",
                    "label_val", "pod_count", "owning_deployment", "container_name",
                    "chaos_mode", "chaos_value",
                ):
                    variables.pop(key, None)
                for index, candidate in enumerate(fields):
                    if candidate["name"] == "namespace":
                        idx = index
                        break
                continue
            if name == "duration" and target_mode == "pod":
                # Pod targets have an auto-set chaos mode, so the preceding
                # interactive step is the container selector.
                variables.pop("container_name", None)
                for index, candidate in enumerate(fields):
                    if candidate["name"] == "container_name":
                        idx = index
                        break
                continue
            if name == "chaos_mode" and target_mode == "deployment":
                # Chaos Mode is downstream of the deployment selector. Return
                # directly to that selector while retaining the namespace and
                # target mode, instead of relying on generic index arithmetic.
                variables.pop("deployment", None)
                variables.pop("label_key", None)
                variables.pop("label_val", None)
                variables.pop("pod_count", None)
                variables.pop("chaos_value", None)
                variables.pop("container_name", None)
                for index, candidate in enumerate(fields):
                    if candidate["name"] == "deployment":
                        idx = index
                        break
                continue
            if idx == 0:
                return None
            idx -= 1
            # If we backed up to the cluster field (auto-populated, no UI),
            # there's nothing to show — go all the way back to the experiment list.
            if idx == 0 and fields[0].get("type") == "azure_aks_cluster":
                return None
            prev_name = fields[idx]["name"]
            variables.pop(prev_name, None)
            variables.pop("chaos_value", None)
            # Backing up to or through namespace — reset target_mode, deployment,
            # and the label selector derived from it, so the target mode picker
            # is shown again and the selector gets re-resolved. These must stay
            # scoped to this branch: popping them on every back-step (even one
            # that only revisits a later field like chaos_mode/duration) would
            # permanently lose label_key/label_val/pod_count for the rest of
            # the session, since namespace/deployment are never revisited again.
            if name in ("namespace", "deployment"):
                target_mode = None
                variables.pop("namespace", None)
                variables.pop("deployment", None)
                variables.pop("label_key", None)
                variables.pop("label_val", None)
                variables.pop("pod_count", None)
                # Find namespace field index and reset idx to it
                for i, f in enumerate(fields):
                    if f["name"] == "namespace":
                        idx = i
                        break

    console.print()
    console.print("[bold cyan]Dry Run[/bold cyan]")
    console.print("[bright_black]Preview what this experiment would do — no changes will be made.[/bright_black]")
    console.print()
    dry_run_answer = prompt("Run as DRY RUN (preview only)? (Y/N)").strip().lower()
    variables["dry_run"] = "true" if dry_run_answer == "y" else "false"

    return variables


def add_aks_experiment(experiment_id):
    """
    Collect inputs for an AKS experiment and add it to the campaign.
    Called from azure_aks_menu.py — mirrors add_generic() flow.
    """
    metadata = get_experiment("aks", experiment_id)

    if metadata is None:
        error(f"Experiment '{experiment_id}' not found.")
        pause()
        return

    metadata = deepcopy(metadata)

    description = get_experiment_description("aks", experiment_id)
    console.print("\n[bold cyan]Experiment Description[/bold cyan]")
    console.print(f"[bold]Description:[/bold] {description.get('description', metadata['name'])}")
    console.print(f"[bold yellow]Potential Impact:[/bold yellow] {description.get('impact', 'Review the configured fault impact.')}")
    console.print(f"[bold green]Expected Behavior:[/bold green] {description.get('expected_behavior', 'Verify workload recovery after cleanup.')}")

    variables = _collect_aks_inputs(metadata)

    if variables is None:
        return

    build_experiment("aks", metadata, variables)

    success(f"{metadata['name']} added to Campaign")

    pause()
