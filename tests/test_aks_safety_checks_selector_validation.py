"""
Unit tests for validate_and_resolve_selector in actions/aks_safety_checks.py.
Covers the label-selector-scope pre-check that detects when a naive
label_key=label_val selector would over-match into sibling Deployments, and
corrects (or hard-blocks) accordingly.
"""

from unittest.mock import MagicMock, patch

from chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks import (
    safety as aks_safety_checks,
)


def _discovery(get_deployment_for_pod=None, get_safe_label_selector=None, get_owned_pod_names=None):
    fake = MagicMock()
    fake.get_deployment_for_pod.return_value = get_deployment_for_pod
    fake.get_safe_label_selector.return_value = get_safe_label_selector
    fake.get_owned_pod_names.return_value = get_owned_pod_names or []
    return fake


def _kubectl_side_effect(*outputs):
    from subprocess import CompletedProcess
    return [CompletedProcess([], 0, stdout=o, stderr="") for o in outputs]


def test_returns_default_ok_when_namespace_or_deployment_missing():
    result = aks_safety_checks.validate_and_resolve_selector(
        "ctx", "", "dep", target_mode="deployment",
    )
    assert result == {
        "ok": True, "label_selectors_map": None, "exact_pod_name": None,
        "hard_block": False, "warning": None,
    }


def test_exact_pod_targeting_resolves_and_pins_field_selector():
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=_kubectl_side_effect("pod-a")[0]), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery",
               return_value=_discovery(get_deployment_for_pod=None)):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "pod-a", target_mode="pod", exact_pod_targeting=True,
        )
    assert result["ok"] is True
    assert result["exact_pod_name"] == "pod-a"
    assert result["label_selectors_map"] is None


def test_exact_pod_targeting_includes_owner_safe_labels_when_available():
    discovery = _discovery(
        get_deployment_for_pod="owning-deployment",
        get_safe_label_selector={"app": "x", "pod-template-hash": "abc"},
    )
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=_kubectl_side_effect("pod-a")[0]), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery",
               return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "pod-a", target_mode="pod", exact_pod_targeting=True,
        )
    assert result["exact_pod_name"] == "pod-a"
    assert result["label_selectors_map"] == {"app": "x", "pod-template-hash": "abc"}


def test_exact_pod_targeting_ignores_optional_label_enrichment_errors():
    discovery = _discovery(get_deployment_for_pod="owning-deployment")
    discovery.get_safe_label_selector.side_effect = RuntimeError("labels unavailable")
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=_kubectl_side_effect("pod-a")[0]), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery",
               return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "pod-a", target_mode="pod", exact_pod_targeting=True,
        )
    assert result["ok"] is True
    assert result["exact_pod_name"] == "pod-a"
    assert result["label_selectors_map"] is None


def test_exact_pod_targeting_hard_blocks_when_pod_not_found():
    from subprocess import CompletedProcess
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=CompletedProcess([], 1, stdout="", stderr="not found")):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "pod-a", target_mode="pod", exact_pod_targeting=True,
        )
    assert result["ok"] is False
    assert result["hard_block"] is True
    assert "could not be resolved" in result["warning"]


def test_naive_selector_already_matches_expected_pods_no_correction_needed():
    discovery = _discovery(get_owned_pod_names=["p1", "p2"])
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=_kubectl_side_effect("p1\np2")[0]), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
        )
    assert result["ok"] is True
    assert result["label_selectors_map"] is None


def test_returns_default_when_target_has_no_owned_pods():
    discovery = _discovery(get_owned_pod_names=[])
    with patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
        )
    assert result["ok"] is True


def test_returns_default_when_no_label_selector_is_supplied():
    discovery = _discovery(get_owned_pod_names=["p1"])
    with patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment",
        )
    assert result["ok"] is True


def test_over_matching_selector_is_auto_tightened_when_safe_map_resolves():
    discovery = _discovery(get_owned_pod_names=["p1"])
    discovery.get_safe_label_selector.return_value = {"app": "x", "pod-template-hash": "abc"}
    from subprocess import CompletedProcess
    responses = [
        CompletedProcess([], 0, stdout="p1\np2", stderr=""),  # naive over-matches
        CompletedProcess([], 0, stdout="p1", stderr=""),       # tightened matches exactly
    ]
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
        )
    assert result["ok"] is True
    assert result["label_selectors_map"] == {"app": "x", "pod-template-hash": "abc"}


def test_auto_tightening_reports_to_ui_and_session():
    discovery = _discovery(get_owned_pod_names=["p1"])
    discovery.get_safe_label_selector.return_value = {"app": "x", "pod-template-hash": "abc"}
    ui = MagicMock()
    session = MagicMock()
    responses = _kubectl_side_effect("p1\np2", "p1")
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
            ui=ui, session=session,
        )
    assert result["ok"] is True
    ui.step.assert_called_once_with(
        "Selector auto-tightened — pod-template labels scoped to 'dep'", live=True,
    )
    session.log_event.assert_called_once_with("pre-check", result["warning"])


def test_hard_blocks_when_owning_deployment_cannot_be_resolved():
    discovery = _discovery(get_deployment_for_pod=None, get_owned_pod_names=["p1"])
    discovery.get_deployment_for_pod.return_value = None
    from subprocess import CompletedProcess
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=CompletedProcess([], 0, stdout="p1\np2", stderr="")), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "pod-a", target_mode="pod", label_key="app", label_val="x",
        )
    assert result["ok"] is False
    assert "owning Deployment could not be resolved" in result["warning"]


def test_hard_blocks_when_no_corrected_selector_can_be_resolved():
    discovery = _discovery(get_owned_pod_names=["p1"], get_safe_label_selector=None)
    with patch.object(aks_safety_checks, "_kubectl",
                      return_value=_kubectl_side_effect("p1\np2")[0]), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
        )
    assert result["ok"] is False
    assert "no corrected selector could be resolved" in result["warning"]


def test_transient_mismatch_logs_retry_and_recovers_with_ui(monkeypatch):
    monkeypatch.setattr(aks_safety_checks.time, "sleep", lambda *_a, **_k: None)
    discovery = _discovery(get_owned_pod_names=["p1"])
    discovery.get_safe_label_selector.return_value = {"app": "x", "pod-template-hash": "abc"}
    ui = MagicMock()
    session = MagicMock()
    responses = _kubectl_side_effect("p1\np2", "p1\np3", "p1\np2", "p1")
    with patch.object(aks_safety_checks, "_kubectl", side_effect=responses), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
            ui=ui, session=session,
        )
    assert result["ok"] is True
    assert session.log_event.call_count == 2
    assert "passed on retry" in session.log_event.call_args_list[-1].args[1]
    ui.step.assert_called_once_with(
        "Selector auto-tightened on retry — pod-template labels scoped to 'dep'", live=True,
    )


def test_persistent_mismatch_hard_blocks_after_retry(monkeypatch):
    monkeypatch.setattr(aks_safety_checks.time, "sleep", lambda *_a, **_k: None)
    discovery = _discovery(get_owned_pod_names=["p1"])
    discovery.get_deployment_for_pod.return_value = "owning-dep"
    discovery.get_safe_label_selector.return_value = {"app": "x", "pod-template-hash": "abc"}
    from subprocess import CompletedProcess
    # Both snapshot rounds: naive over-matches, tightened still doesn't match exactly.
    mismatched = [
        CompletedProcess([], 0, stdout="p1\np2", stderr=""),
        CompletedProcess([], 0, stdout="p1\np3", stderr=""),
    ] * 2
    with patch.object(aks_safety_checks, "_kubectl", side_effect=mismatched), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "pod-a", target_mode="pod", label_key="app", label_val="x",
        )
    assert result["ok"] is False
    assert "confirmed on retry" in result["warning"]


def test_persistent_mismatch_logs_final_warning_to_session(monkeypatch):
    monkeypatch.setattr(aks_safety_checks.time, "sleep", lambda *_a, **_k: None)
    discovery = _discovery(get_owned_pod_names=["p1"])
    discovery.get_safe_label_selector.return_value = {"app": "x", "pod-template-hash": "abc"}
    session = MagicMock()
    mismatched = _kubectl_side_effect("p1\np2", "p1\np3") * 2
    with patch.object(aks_safety_checks, "_kubectl", side_effect=mismatched), \
         patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
            session=session,
        )
    assert result["ok"] is False
    assert session.log_event.call_args_list[-1].args == ("pre-check", result["warning"])


def test_never_raises_when_discovery_call_errors_inside_snapshot():
    # AzureAKSDiscovery() itself is instantiated outside the try/except, so a
    # constructor failure still propagates — the "never raises" guarantee
    # covers errors from calls made *inside* the try block (e.g. a discovery
    # method raising mid-snapshot), which is what this exercises.
    discovery = MagicMock()
    discovery.get_owned_pod_names.side_effect = RuntimeError("boom")
    with patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
        )
    assert result["ok"] is True
    assert result["label_selectors_map"] is None


def test_logs_when_selector_validation_errors():
    discovery = MagicMock()
    discovery.get_owned_pod_names.side_effect = RuntimeError("boom")
    session = MagicMock()
    with patch("chaosforge.providers.azure.components.aks.discovery.AzureAKSDiscovery", return_value=discovery):
        result = aks_safety_checks.validate_and_resolve_selector(
            "ctx", "ns", "dep", target_mode="deployment", label_key="app", label_val="x",
            session=session,
        )
    assert result["ok"] is True
    session.log_event.assert_called_once_with(
        "pre-check", "Selector-scope validation skipped (error): boom",
    )
