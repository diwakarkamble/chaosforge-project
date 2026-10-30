from chaosforge.lifecycle.lifecycle_report import LifecycleReportRenderer


def test_render_full_lifecycle_report():
    renderer = LifecycleReportRenderer()

    report = renderer.render(
        precheck={
            "enabled": True,
            "check": "Lambda configuration",
            "resource": "Chaos-POC-lambda",
            "baseline": "Captured",
            "passed": True,
        },
        injection={
            "success": True,
            "check": "Memory Modification",
            "display": {
                "Expected": "512 MB",
                "Observed": "512 MB",
            },
        },
        validation={
            "enabled": True,
            "check": "Memory modification",
            "display": {
                "Expected": "512 MB",
                "Observed": "512 MB",
            },
            "passed": True,
        },
    )

    assert "Lifecycle Validation" in report
    assert "PRE-CHECK" in report
    assert "CHAOS EXECUTION" in report
    assert "POST-VALIDATION" in report
    assert "FINAL RESULT" in report

    assert "Lambda configuration" in report
    assert "Chaos-POC-lambda" in report
    assert "Memory Modification" in report
    assert "512 MB" in report

    assert "OVERALL     : PASSED" in report


def test_render_without_validation():
    renderer = LifecycleReportRenderer()

    report = renderer.render(
        precheck={
            "enabled": False,
            "passed": True,
        },
        injection={
            "success": True,
            "check": "Test Experiment",
            "display": {},
        },
        validation={
            "enabled": False,
        },
    )

    assert "PRE-CHECK" in report
    assert "CHAOS EXECUTION" in report
    assert "POST-VALIDATION" in report

    assert "SKIPPED" in report
    assert "OVERALL     : PASSED" in report


def test_render_failed_validation():
    renderer = LifecycleReportRenderer()

    report = renderer.render(
        precheck={
            "enabled": True,
            "check": "Resource configuration",
            "resource": "test-resource",
            "baseline": "Captured",
            "passed": True,
        },
        injection={
            "success": True,
            "check": "Resource modification",
            "display": {
                "Expected": "Stopped",
                "Observed": "Stopped",
            },
        },
        validation={
            "enabled": True,
            "check": "Resource state",
            "display": {
                "Expected": "Running",
                "Observed": "Stopped",
            },
            "passed": False,
        },
    )

    assert "Expected" in report
    assert "Running" in report
    assert "Observed" in report
    assert "Stopped" in report
    assert "Result" in report
    assert "FAILED" in report


def test_render_advisory_post_validation_warning():
    report = LifecycleReportRenderer().render(
        injection={"success": True, "check": "Network delay"},
        validation={
            "enabled": True,
            "check": "shared-kubernetes-chaos-validation",
            "passed": True,
            "warnings": [
                {
                    "label": "Probe Failures Stopped (post)",
                    "detail": "Recent Unhealthy probe events remain.",
                }
            ],
        },
    )

    assert "Result      : PASSED WITH WARNINGS" in report
    assert "Warning     : Probe Failures Stopped (post): Recent Unhealthy probe events remain." in report
    assert "OVERALL     : PASSED WITH WARNINGS" in report


def test_render_failed_injection_includes_error():
    report = LifecycleReportRenderer().render(
        injection={
            "success": False,
            "check": "Stop EC2 Instances (AWS FIS)",
            "error": "Target resource is required for an AWS FIS experiment.",
        },
        validation={"enabled": False},
    )

    assert "Result      : FAILED" in report
    assert "Error       : Target resource is required" in report


def test_render_failed_precheck_includes_error():
    report = LifecycleReportRenderer().render(
        precheck={
            "enabled": True,
            "check": "shared-kubernetes-chaos-validation",
            "resource": "pod-a",
            "passed": False,
            "error": "Kubernetes pre-checks failed: Replica Floor (pod-a)",
        },
        injection={"success": False},
        validation={"enabled": False},
    )

    assert "Error       : Kubernetes pre-checks failed: Replica Floor (pod-a)" in report


def test_renderer_is_service_agnostic():
    renderer = LifecycleReportRenderer()

    report = renderer.render(
        precheck={
            "enabled": True,
            "check": "Generic configuration",
            "resource": "resource-123",
            "baseline": "Captured",
            "passed": True,
        },
        injection={
            "success": True,
            "check": "Generic experiment",
            "display": {
                "Expected": "Changed",
                "Observed": "Changed",
            },
        },
        validation={
            "enabled": True,
            "check": "Generic validation",
            "display": {
                "Expected": "Healthy",
                "Observed": "Healthy",
            },
            "passed": True,
        },
    )

    assert "Generic configuration" in report
    assert "resource-123" in report
    assert "Generic experiment" in report
    assert "Healthy" in report
    assert "OVERALL     : PASSED" in report
