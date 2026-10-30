import atexit
import subprocess

from rich.panel import Panel

from chaosforge.common.azure_cli import azure_cli_command
from chaosforge.interfaces.cli.interactive.ui.console import console
from chaosforge.interfaces.cli.interactive.ui.panels import title
from chaosforge.interfaces.cli.interactive.ui.prompts import prompt
from chaosforge.interfaces.cli.interactive.ui.status import error, info

_AZURE_CACHE_FILE = "~/.chaosforge/azure_last_used.json"


def _remove_kube_context(name):
    """Remove a session-only kubeconfig context when ChaosForge exits."""
    from chaosforge.providers.azure.components.aks.kubernetes import (
        delete_kube_context,
    )

    try:
        delete_kube_context(name)
    except Exception:
        pass


def _load_azure_cache():
    import json
    import os

    path = os.path.expanduser(_AZURE_CACHE_FILE)
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def _save_azure_cache(data):
    import json
    import os

    path = os.path.expanduser(_AZURE_CACHE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class PlatformSelector:
    def select(self):

        while True:
            title("Select Cloud Provider")

            console.print()

            console.print("[bold cyan]1.[/bold cyan] Amazon Web Services (AWS)")
            console.print("[bold cyan]2.[/bold cyan] Microsoft Azure")
            console.print("[bold cyan]0.[/bold cyan] Exit")
            console.print()

            choice = prompt("Select Cloud").strip()

            if choice == "1":
                return "aws"

            elif choice == "2":
                self._load_cached_azure_context()
                return "azure"

            elif choice == "0":
                raise SystemExit

            else:
                error("Invalid Choice")

    def _load_cached_azure_context(self):
        """Silently populate context from the last-used Azure config, if any.
        No prompts here — confirming/changing details happens in Create
        Campaign -> Select Azure Service."""
        from chaosforge.interfaces.cli.session import context

        cached = _load_azure_cache()
        if cached and cached.get("subscription_id") and cached.get("resource_group") and cached.get("cluster_name"):
            try:
                from chaosforge.providers.azure.discovery import resolve_subscription_id

                context.azure_subscription = resolve_subscription_id(
                    cached["subscription_id"]
                )
            except RuntimeError:
                return
            context.azure_account_name = cached.get("account_name")
            context.azure_resource_group = cached["resource_group"]
            context.aks_cluster_name = cached["cluster_name"]
            context.azure_location = cached.get("location")
            context.aks_kube_context = cached.get("kube_context")

    def ensure_azure_kube_context(self):
        """Ensure the selected AKS context exists, refreshing credentials if needed."""
        from chaosforge.interfaces.cli.session import context

        context_name = context.aks_kube_context
        if context_name:
            try:
                from chaosforge.providers.azure.components.aks.kubernetes import (
                    list_kube_contexts,
                )
                if context_name in list_kube_contexts():
                    return True
            except Exception:
                pass

        if not (
            context.azure_subscription
            and context.azure_resource_group
            and context.aks_cluster_name
        ):
            return False

        info(
            "The cached AKS kubeconfig context is missing. "
            "Refreshing cluster credentials from Azure."
        )
        try:
            result = subprocess.run(
                azure_cli_command(
                    "aks", "get-credentials",
                    "--subscription", context.azure_subscription,
                    "--resource-group", context.azure_resource_group,
                    "--name", context.aks_cluster_name,
                    "--overwrite-existing",
                ),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            error("Azure CLI ('az') not found. Cannot refresh AKS credentials.")
            return False
        except Exception as exc:
            error(f"Could not refresh AKS credentials: {exc}")
            return False

        if result.returncode != 0:
            error(f"'az aks get-credentials' failed: {result.stderr.strip()}")
            return False

        context.aks_kube_context = context.aks_cluster_name
        _save_azure_cache({
            "subscription_id": context.azure_subscription,
            "account_name": context.azure_account_name,
            "resource_group": context.azure_resource_group,
            "cluster_name": context.aks_cluster_name,
            "location": context.azure_location,
            "kube_context": context.aks_kube_context,
        })
        info(f"AKS credentials refreshed. Using context: {context.aks_kube_context}")
        return True

    def _prompt_azure_details(self):
        import json

        from chaosforge.interfaces.cli.interactive.ui.spinner import spinner
        from chaosforge.interfaces.cli.interactive.ui.tables import menu as _menu
        from chaosforge.interfaces.cli.session import context

        title("Microsoft Azure — Setup")

        # ------------------------------------------------------------------
        # Step 1: Subscription ID
        # ------------------------------------------------------------------
        console.print()
        console.print("[bold cyan]Azure Subscription ID[/bold cyan]")
        console.print("[bright_black]Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx[/bright_black]")
        console.print()
        subscription_id = prompt(">").strip()
        if not subscription_id:
            error("Subscription ID is required.")
            return False

        # ------------------------------------------------------------------
        # Step 2: Validate subscription access
        # ------------------------------------------------------------------
        console.print()
        with spinner("Validating subscription access..."):
            try:
                result = subprocess.run(
                    azure_cli_command("account", "show", "--subscription", subscription_id,
                     "--output", "json"),
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode != 0:
                    accessible = False
                    err_msg = (result.stderr.strip().splitlines()[0]
                               if result.stderr.strip() else "Access denied.")
                else:
                    account = json.loads(result.stdout)
                    accessible = True
                    subscription_id = account.get("id") or subscription_id
                    account_name = account.get("name", subscription_id)
            except FileNotFoundError:
                error("Azure CLI ('az') not found. Install it and run 'az login'.")
                return False
            except Exception as exc:
                error(f"Subscription check failed: {exc}")
                return False

        if not accessible:
            error(f"No access to subscription '{subscription_id}'. {err_msg}")
            info("Run 'az login' or check your subscription ID and try again.")
            return False

        info(f"Subscription verified: {account_name}")

        # ------------------------------------------------------------------
        # Step 3 & 4: List AKS clusters in this subscription and let the
        # user pick one, instead of typing Resource Group / Cluster Name
        # by hand. Falls back to manual entry if the listing fails.
        # ------------------------------------------------------------------
        resource_group = None
        cluster_name = None
        cluster_location = None

        console.print()
        clusters = []
        list_error = None
        with spinner("Listing AKS clusters in subscription..."):
            try:
                r = subprocess.run(
                    azure_cli_command("aks", "list",
                     "--subscription", subscription_id,
                     "--output", "json"),
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode != 0:
                    list_error = (r.stderr.strip().splitlines()[0]
                                  if r.stderr.strip() else "Unknown error.")
                else:
                    clusters = json.loads(r.stdout)
            except FileNotFoundError:
                list_error = "Azure CLI ('az') not found."
            except Exception as exc:
                list_error = str(exc)

        if list_error or not clusters:
            error(
                f"Could not list AKS clusters automatically "
                f"({list_error or 'no clusters found in this subscription'}). "
                f"Falling back to manual entry."
            )

            console.print()
            console.print("[bold cyan]Resource Group[/bold cyan]")
            console.print()
            resource_group = prompt(">").strip()
            if not resource_group:
                error("Resource Group is required.")
                return False

            console.print()
            console.print("[bold cyan]AKS Cluster Name[/bold cyan]")
            console.print()
            cluster_name = prompt(">").strip()
            if not cluster_name:
                error("Cluster Name is required.")
                return False

            console.print()
            with spinner(f"Fetching cluster details for '{cluster_name}'..."):
                try:
                    r = subprocess.run(
                        azure_cli_command("aks", "show",
                         "--subscription", subscription_id,
                         "--resource-group", resource_group,
                         "--name", cluster_name,
                         "--output", "json"),
                        capture_output=True, text=True, timeout=20,
                    )
                    if r.returncode == 0:
                        cluster_info = json.loads(r.stdout)
                        cluster_location = cluster_info.get("location")
                except Exception:
                    pass  # non-fatal — we still proceed

            if cluster_location:
                info(f"Cluster location: {cluster_location}")
            else:
                info("Could not fetch cluster location — continuing.")
        else:
            console.print()
            console.print("[bold cyan]AKS Clusters[/bold cyan]")
            console.print(
                "[bright_black]Clusters found in this subscription.[/bright_black]"
            )
            console.print()

            def _cluster_label(c):
                power_code = (c.get("powerState") or {}).get("code", "")
                label = f"{c.get('name')}  ({c.get('resourceGroup')})"
                if power_code and power_code.lower() != "running":
                    label += f"  [red]({power_code})[/red]"
                return label

            selected_cluster = None
            while True:
                _menu(
                    "Select AKS Cluster",
                    [
                        (i, _cluster_label(c))
                        for i, c in enumerate(clusters, start=1)
                    ],
                )
                console.print()

                while True:
                    choice = prompt("Select Cluster").strip()
                    try:
                        candidate = clusters[int(choice) - 1]
                        break
                    except (ValueError, IndexError):
                        error("Invalid selection.")

                power_code = (candidate.get("powerState") or {}).get("code", "")
                if power_code and power_code.lower() != "running":
                    error(
                        f"Cluster '{candidate.get('name')}' is currently {power_code}. "
                        f"Start it first (e.g. 'az aks start --name {candidate.get('name')} "
                        f"--resource-group {candidate.get('resourceGroup')}') or choose a "
                        f"different cluster."
                    )
                    console.print()
                    continue

                selected_cluster = candidate
                break

            resource_group = selected_cluster.get("resourceGroup")
            cluster_name = selected_cluster.get("name")
            cluster_location = selected_cluster.get("location")

            info(f"Cluster selected: {cluster_name} ({resource_group})")
            if cluster_location:
                info(f"Cluster location: {cluster_location}")

        # ------------------------------------------------------------------
        # Step 6: Search kubeconfig contexts that match this subscription
        # ------------------------------------------------------------------
        console.print()
        with spinner("Searching kubeconfig for matching Azure contexts..."):
            try:
                from chaosforge.providers.azure.components.aks.kubernetes import (
                    list_kube_contexts,
                )

                all_contexts = list_kube_contexts()
            except Exception:
                all_contexts = []

            # Keep only contexts that contain the subscription ID or cluster name —
            # this filters out unrelated AWS/GCP contexts stored in the same kubeconfig.
            sub_short = subscription_id.replace("-", "")[:8]
            matching_contexts = [
                c for c in all_contexts
                if subscription_id.lower() in c.lower()
                or cluster_name.lower() in c.lower()
                or sub_short in c.lower()
            ]

        confirmed_context = None

        if matching_contexts:
            console.print()
            console.print("[bold cyan]Matching Azure Contexts[/bold cyan]")
            console.print(
                "[bright_black]These kubeconfig contexts match your subscription / cluster.[/bright_black]"
            )
            console.print()

            _menu(
                "Matching Contexts",
                [(i, ctx) for i, ctx in enumerate(matching_contexts, start=1)],
            )

            console.print()
            console.print("[bold cyan]0.[/bold cyan] None — let ChaosForge fetch credentials automatically")
            console.print()

            while True:
                choice = prompt("Select Context").strip()

                if choice == "0":
                    confirmed_context = None
                    break

                try:
                    confirmed_context = matching_contexts[int(choice) - 1]
                    info(f"Context confirmed: {confirmed_context}")
                    break
                except (ValueError, IndexError):
                    error("Invalid selection.")
        else:
            info("No matching Azure contexts found in kubeconfig — fetching credentials from Azure.")

        # ------------------------------------------------------------------
        # Step 7: No context confirmed — fetch AKS credentials, then ask
        # whether to persist them to kubeconfig for future runs.
        # ------------------------------------------------------------------
        persist_context = True

        if not confirmed_context:
            console.print()
            with spinner(f"Fetching credentials for '{cluster_name}'..."):
                try:
                    r = subprocess.run(
                        azure_cli_command("aks", "get-credentials",
                         "--subscription", subscription_id,
                         "--resource-group", resource_group,
                         "--name", cluster_name,
                         "--overwrite-existing"),
                        capture_output=True, text=True, timeout=30,
                    )
                except FileNotFoundError:
                    error("Azure CLI ('az') not found. Cannot fetch AKS credentials automatically.")
                    return False
                except Exception as exc:
                    error(f"Could not fetch AKS credentials: {exc}")
                    return False

            if r.returncode != 0:
                error(f"'az aks get-credentials' failed: {r.stderr.strip()}")
                return False

            # az aks get-credentials names the merged context after the cluster by default
            confirmed_context = cluster_name
            info(f"Credentials fetched. Using context: {confirmed_context}")

            # Ask whether to save the new context entry for future runs
            console.print()
            save_answer = prompt("Save this context for future runs? (Y/N)").strip().lower()
            if save_answer != "y":
                # Keep the context until process exit because all subsequent
                # Kubernetes calls resolve it from kubeconfig by name.
                persist_context = False
                atexit.register(_remove_kube_context, confirmed_context)
                info("Context will be used for this session only and removed when ChaosForge exits.")

        # ------------------------------------------------------------------
        # Commit to context
        # ------------------------------------------------------------------
        context.azure_subscription = subscription_id
        context.azure_account_name = account_name
        context.azure_resource_group = resource_group
        context.aks_cluster_name = cluster_name
        context.azure_location = cluster_location
        context.aks_kube_context = confirmed_context

        _save_azure_cache({
            "subscription_id": subscription_id,
            "account_name": account_name,
            "resource_group": resource_group,
            "cluster_name": cluster_name,
            "location": cluster_location,
            "kube_context": confirmed_context if persist_context else None,
        })

        return True

    def show_coming_soon(self, provider):

        title(provider)

        console.print()

        console.print(
            Panel.fit(
                f"""
[bold cyan]{provider} (Coming Soon)[/bold cyan]

Support for this cloud provider is currently under development.

[bold]Planned Features[/bold]

✓ Region Selection
✓ Resource Discovery
✓ Chaos Experiments
✓ Campaign Management
✓ Reporting

[yellow]Status : Coming Soon[/yellow]
""",
                title=provider,
                border_style="cyan",
            )
        )

        console.print()

        prompt("Press Enter to return")
