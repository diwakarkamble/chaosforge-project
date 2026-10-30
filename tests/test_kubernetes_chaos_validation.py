from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.lifecycle.checks.kubernetes_chaos import (
    EKS_TO_AKS_EXPERIMENT,
    SharedChaosMeshValidationCheck,
    build_cluster_plane_post_validation_checks,
    equivalent_aks_experiment,
    run_validation_checks,
)


def test_cluster_plane_post_validation_delegate_forwards_arguments(monkeypatch):
    builder = MagicMock(return_value={"restored": lambda: (True, "ready")})
    monkeypatch.setattr(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.checks.extended.build_cluster_plane_chaos_post_checks",
        builder,
    )

    assert build_cluster_plane_post_validation_checks("ctx", "aks-kube-proxy-kill") == {
        "restored": builder.return_value["restored"]
    }
    builder.assert_called_once_with("ctx", "aks-kube-proxy-kill")


@pytest.mark.parametrize(("eks_id", "aks_id"), EKS_TO_AKS_EXPERIMENT.items())
def test_equivalent_experiments_share_aks_validation_profile(eks_id, aks_id):
    assert equivalent_aks_experiment(eks_id) == aks_id


def test_time_profile_uses_offset_direction():
    assert equivalent_aks_experiment("chaos-mesh-time", {"time_offset": "+5m"}) == (
        "aks-clock-skew-forward"
    )
    assert equivalent_aks_experiment("chaos-mesh-time", {"time_offset": "-5m"}) == (
        "aks-clock-skew-backward"
    )


def test_unmatched_experiment_has_no_shared_profile():
    assert equivalent_aks_experiment("chaos-mesh-jvm") is None


def test_validation_runner_records_failures_and_exceptions():
    result = run_validation_checks(
        {
            "healthy": lambda: (True, "ready"),
            "unhealthy": lambda: (False, "not ready"),
            "broken": lambda: (_ for _ in ()).throw(RuntimeError("failed")),
        }
    )

    assert result["passed"] is False
    assert result["checks"]["healthy"]["passed"] is True
    assert result["checks"]["unhealthy"]["detail"] == "not ready"
    assert result["checks"]["broken"]["error"] == "failed"


def test_validation_runner_records_io_advisories_without_blocking_execution():
    result = run_validation_checks(
        {
            "IOChaos Namespace Inject Label": lambda: (False, "namespace not labeled"),
            "IOChaos Sidecar Injected on Pod (Advisory)": lambda: (False, "sidecar absent"),
            "Volume Mount Path Exists": lambda: (True, "mounted"),
        }
    )

    assert result["passed"] is True
    assert result["checks"]["IOChaos Namespace Inject Label"]["passed"] is False
    assert result["checks"]["IOChaos Sidecar Injected on Pod (Advisory)"]["passed"] is False
    assert len(result["warnings"]) == 2
    assert result["warnings"][0]["severity"] == "ADVISORY"
    assert result["blocking_failures"] == []


def test_validation_runner_keeps_post_probe_warning_visible_without_failing():
    result = run_validation_checks(
        {
            "Probe Failures Stopped (post)": lambda: (
                False,
                "Recent Unhealthy probe events remain in the recovery window.",
            ),
        }
    )

    assert result["passed"] is True
    assert result["warnings"] == [
        {
            "id": "probe_failures_stopped_(post)",
            "label": "Probe Failures Stopped (post)",
            "passed": False,
            "severity": "ADVISORY",
            "detail": "Recent Unhealthy probe events remain in the recovery window.",
            "elapsed_seconds": pytest.approx(result["warnings"][0]["elapsed_seconds"]),
            "error": None,
        }
    ]


def test_validation_runner_keeps_io_hard_failures_blocking():
    result = run_validation_checks(
        {"Volume Mount Path Exists": lambda: (False, "not mounted")}
    )

    assert result["passed"] is False


def test_during_validation_accepts_all_injected_condition(monkeypatch):
    experiment = SimpleNamespace(
        id="chaos-mesh-network-delay",
        variables={"eks_cluster": "cluster", "namespace": "default", "pod": "pod-a"},
    )
    discovery = SimpleNamespace(eks_kube_context="context")
    check = SharedChaosMeshValidationCheck(discovery, experiment)
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.observe_fault",
        lambda *args, **kwargs: {"severity": "INFO", "message": "active"},
    )

    sample = check.observe_during(
        experiment.variables,
        {},
        {
            "status": {
                "phase": "Running",
                "conditions": [{"type": "AllInjected", "status": "True"}],
            }
        },
    )

    assert sample["resource_phase"] == "Running"
    assert check.runtime_validation["fault_observed"] is True
    assert check.runtime_validation["passed"] is True


def test_aks_context_does_not_require_or_configure_aws_discovery():
    experiment = SimpleNamespace(
        id="aks-pod-kill",
        service="aks",
        variables={"aks_context": "aks-context", "namespace": "apps"},
    )
    check = SharedChaosMeshValidationCheck(None, experiment)

    context = check._context(experiment.variables)

    assert context.cluster == "aks-context"
    assert context.kube_context == "aks-context"
    assert context.namespace == "apps"


def test_coredns_validation_uses_kube_system_post_checks(monkeypatch):
    experiment = SimpleNamespace(
        id="aks-coredns-kill",
        service="aks",
        variables={"aks_context": "aks-context"},
    )
    cluster_plane_builder = MagicMock(
        return_value={"CoreDNS Restored": lambda: (True, "5/5 Ready")}
    )
    generic_builder = MagicMock()
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_cluster_plane_post_validation_checks",
        cluster_plane_builder,
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_post_validation_checks",
        generic_builder,
    )
    check = SharedChaosMeshValidationCheck(None, experiment)

    context = check._context(experiment.variables)
    result = check.validate(experiment.variables, baseline={})

    assert context.namespace == "kube-system"
    cluster_plane_builder.assert_called_once_with("aks-context", "aks-coredns-kill")
    generic_builder.assert_not_called()
    assert result["passed"] is True
    assert result["display"] == {
        "Expected": "All post-experiment checks pass",
        "Observed": "All post-experiment checks passed",
    }


def test_pod_mode_uses_exact_pod_and_owning_deployment_separately():
    experiment = SimpleNamespace(
        id="aks-pod-kill",
        service="aks",
        variables={
            "aks_context": "ctx",
            "namespace": "sample-app",
            "deployment": "nginx-app-54c8cc866d-frgrn",
            "owning_deployment": "nginx-app",
            "target_mode": "pod",
        },
    )

    context = SharedChaosMeshValidationCheck(None, experiment)._context(experiment.variables)

    assert context.pod == "nginx-app-54c8cc866d-frgrn"
    assert context.workload == "nginx-app"


def test_eks_pod_kill_post_validation_waits_fault_duration_and_retries(monkeypatch):
    experiment = SimpleNamespace(
        id="chaos-mesh-pod-kill",
        variables={
            "eks_cluster": "cluster",
            "namespace": "apps",
            "pod": "api-old",
            "owning_deployment": "api",
            "labels": {"app": "api"},
            "duration": "30s",
        },
    )
    check = SharedChaosMeshValidationCheck(SimpleNamespace(), experiment)
    post_builder = pytest.MonkeyPatch()
    captured = {}
    post_builder.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_post_validation_checks",
        lambda *_args, **kwargs: captured.update(kwargs) or {"Pod Recovery": lambda: (True, "ready")},
    )
    try:
        check.validate(experiment.variables, {})
    finally:
        post_builder.undo()

    assert captured["recovery_wait_seconds"] == 30
    assert captured["recovery_retry_count"] == 5
    assert captured["recovery_retry_interval_seconds"] == 50


def test_duration_seconds_accepts_web_integer_duration():
    from chaosforge.lifecycle.checks.kubernetes_chaos import _duration_seconds

    assert _duration_seconds(30) == 30
    assert _duration_seconds("30s") == 30
    assert _duration_seconds("PT2M") == 120


def test_registered_eks_client_prevents_ambient_kubeconfig_lookup(monkeypatch):
    from chaosforge.providers.azure.components.aks import kubernetes

    client = object()
    monkeypatch.setattr(kubernetes, "_client_cache", {})
    monkeypatch.setattr(
        kubernetes.config,
        "load_kube_config",
        lambda **_kwargs: pytest.fail("ambient kubeconfig must not be loaded"),
    )

    kubernetes.register_api_client("arn:aws:eks:region:account:cluster/demo", client)

    assert kubernetes._get_api_client("arn:aws:eks:region:account:cluster/demo") is client


def test_eks_validation_session_uses_eks_experiment_name(monkeypatch):
    experiment = SimpleNamespace(
        id="chaos-mesh-pod-kill",
        variables={"eks_cluster": "cluster", "namespace": "apps"},
    )
    session = SimpleNamespace(start=lambda: None)
    session_factory = pytest.MonkeyPatch()
    session_factory.setattr(
        "chaosforge.providers.azure.components.aks.experiments.chaos_studio.validation_logger.ValidationSession",
        lambda identifier: session if identifier == "chaos-mesh-pod-kill" else pytest.fail(identifier),
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.build_pre_validation_checks",
        lambda **_kwargs: {"Ready": lambda: (True, "ready")},
    )
    monkeypatch.setattr(
        "chaosforge.lifecycle.checks.kubernetes_chaos.run_validation_checks",
        lambda *_args, **_kwargs: {"passed": True, "checks": {}},
    )
    try:
        SharedChaosMeshValidationCheck(SimpleNamespace(), experiment).capture(experiment.variables)
    finally:
        session_factory.undo()


def test_eks_execution_display_hides_internal_aks_validation_identifier():
    experiment = SimpleNamespace(
        id="chaos-mesh-pod-failure",
        name="Pod Failure",
        variables={"eks_cluster": "cluster"},
    )

    display = SharedChaosMeshValidationCheck(SimpleNamespace(), experiment).build_execution_display(
        experiment.variables
    )

    assert display["Expected"] == "Pod Failure fault observed"
