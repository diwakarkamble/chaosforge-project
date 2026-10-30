"""Selector-scope validation independent from safety.py module globals."""


def validate_and_resolve_selector(
    aks_context: str,
    namespace: str,
    deployment: str,
    target_mode: str,
    label_key: str = "",
    label_val: str = "",
    *,
    ui=None,
    session=None,
    exact_pod_targeting=False,
    kubectl,
    discovery_factory,
    sleep,
):
    """Validate a selector and return a safely narrowed replacement when needed."""
    result = {
        "ok": True,
        "label_selectors_map": None,
        "exact_pod_name": None,
        "hard_block": False,
        "warning": None,
    }
    if not namespace or not deployment:
        return result

    discovery = discovery_factory()
    try:
        if target_mode == "pod" and exact_pod_targeting:
            pod_result = kubectl(
                "get", "pod", deployment, "-n", namespace,
                "-o", "jsonpath={.metadata.name}", context=aks_context,
            )
            if pod_result.returncode != 0 or pod_result.stdout.strip() != deployment:
                result["ok"] = False
                result["hard_block"] = True
                result["warning"] = (
                    f"Exact pod target '{deployment}' could not be resolved in namespace "
                    f"'{namespace}'. Pod-mode experiments cannot be overridden because a "
                    "label fallback could target a different pod."
                )
                return result
            result["exact_pod_name"] = deployment
            result["warning"] = (
                f"Pod mode pinned to exact pod '{deployment}' using "
                "selector.fieldSelectors[metadata.name]."
            )
            try:
                owning_deployment = discovery.get_deployment_for_pod(
                    aks_context, namespace, deployment
                )
                if owning_deployment:
                    safe_map = discovery.get_safe_label_selector(
                        aks_context, namespace, owning_deployment
                    )
                    if safe_map:
                        result["label_selectors_map"] = safe_map
            except Exception:
                pass
            return result

        def snapshot():
            if target_mode == "pod":
                expected_pods = {deployment}
                owning_deployment = discovery.get_deployment_for_pod(
                    aks_context, namespace, deployment
                )
            else:
                owning_deployment = deployment
                expected_pods = set(
                    discovery.get_owned_pod_names(aks_context, namespace, deployment)
                )
            if not expected_pods:
                return None, None, None, None, None, dict(result)

            selector = f"{label_key}={label_val}" if label_key and label_val else ""
            if not selector:
                return None, None, None, None, None, dict(result)
            naive_result = kubectl(
                "get", "pods", "-n", namespace, "-l", selector,
                "--no-headers", "-o", "custom-columns=NAME:.metadata.name",
                context=aks_context,
            )
            naive = (
                {line.strip() for line in naive_result.stdout.splitlines() if line.strip()}
                if naive_result.returncode == 0 else set()
            )
            if naive and naive == expected_pods:
                return expected_pods, naive, naive, owning_deployment, selector, dict(result)
            if not owning_deployment:
                blocked = dict(result)
                blocked["ok"] = False
                blocked["warning"] = (
                    f"Selector '{selector}' matches {len(naive)} pod(s) but the expected "
                    f"target is {len(expected_pods)} pod(s), and the owning Deployment could not be "
                    "resolved to auto-correct the selector."
                )
                return expected_pods, naive, None, owning_deployment, selector, blocked

            safe_map = discovery.get_safe_label_selector(
                aks_context, namespace, owning_deployment
            )
            if not safe_map:
                blocked = dict(result)
                blocked["ok"] = False
                blocked["warning"] = (
                    f"Selector '{selector}' matches {len(naive)} pod(s), which differs from "
                    f"the {len(expected_pods)} pod(s) actually owned by '{owning_deployment}', and no "
                    "corrected selector could be resolved."
                )
                return expected_pods, naive, None, owning_deployment, selector, blocked

            tightened_selector = ",".join(f"{key}={value}" for key, value in safe_map.items())
            tightened_result = kubectl(
                "get", "pods", "-n", namespace, "-l", tightened_selector,
                "--no-headers", "-o", "custom-columns=NAME:.metadata.name",
                context=aks_context,
            )
            tightened = (
                {line.strip() for line in tightened_result.stdout.splitlines() if line.strip()}
                if tightened_result.returncode == 0 else set()
            )
            if tightened == expected_pods:
                success = dict(result)
                extra = naive - expected_pods
                success["label_selectors_map"] = safe_map
                success["warning"] = (
                    f"Selector '{selector}' would also have matched {len(extra)} pod(s) from other "
                    "Deployment(s) sharing the same labels — auto-tightened using additional pod-template "
                    f"labels to scope only to '{owning_deployment}'."
                )
                return expected_pods, naive, tightened, owning_deployment, selector, success
            return expected_pods, naive, tightened, owning_deployment, selector, None

        expected, naive, tightened, owner, selector, outcome = snapshot()
        if outcome is not None:
            if outcome.get("label_selectors_map") and ui:
                ui.step(f"Selector auto-tightened — pod-template labels scoped to '{owner}'", live=True)
            if outcome.get("label_selectors_map") and session:
                session.log_event("pre-check", outcome["warning"])
            return outcome

        if session:
            session.log_event(
                "pre-check",
                f"Selector-scope mismatch on first check (expected {len(expected)}, "
                f"naive matched {len(naive)}, tightened matched {len(tightened)}) — "
                "retrying once to rule out transient pod churn."
            )
        sleep(1.5)
        expected, naive, tightened, owner, selector, outcome = snapshot()
        if outcome is not None:
            if outcome.get("label_selectors_map"):
                if session:
                    session.log_event(
                        "pre-check",
                        "Selector-scope validation passed on retry — mismatch was transient "
                        "(likely pod churn), not a genuine label collision."
                    )
                if ui:
                    ui.step(f"Selector auto-tightened on retry — pod-template labels scoped to '{owner}'", live=True)
            return outcome

        result["ok"] = False
        extra_naive = sorted(naive - expected)
        missing_naive = sorted(expected - naive)
        extra_tightened = sorted(tightened - expected)
        missing_tightened = sorted(expected - tightened)
        result["warning"] = (
            f"Selector '{selector}' matches pods outside the selected target and could not be "
            "safely scoped, even after tightening with pod-template labels (confirmed on retry). "
            f"Expected {len(expected)} pod(s), naive selector matched {len(naive)}, "
            f"tightened selector matched {len(tightened)}.\n"
            f"    Expected (ground truth via ReplicaSet ownership): {sorted(expected)}\n"
            f"    Naive selector matched:    {sorted(naive)}"
            + (f"  [extra: {extra_naive}, missing: {missing_naive}]" if naive != expected else "")
            + f"\n    Tightened selector matched: {sorted(tightened)}"
            + (f"  [extra: {extra_tightened}, missing: {missing_tightened}]" if tightened != expected else "")
        )
        if session:
            session.log_event("pre-check", result["warning"])
        return result
    except Exception as exc:
        if session:
            session.log_event("pre-check", f"Selector-scope validation skipped (error): {exc}")
        return result
