from types import SimpleNamespace

import pytest

from e2e.webui.functional import test_functional_campaigns as runner


def test_select_target_fills_identity_before_selecting_resource(monkeypatch):
    calls = []
    page = SimpleNamespace(locator=lambda selector: _locator(selector, calls), wait_for_function=lambda *_args, **_kwargs: None)
    case = SimpleNamespace(
        cloud="azure",
        target={"resource_group": "rg"},
        selector="#resource_id",
        resource_fields=(),
        inputs={"chaos_identity_id": "/identities/chaos"},
        id="case",
    )
    resolution = SimpleNamespace(resources=[{"id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm", "name": "vm"}])
    monkeypatch.setattr(runner, "goto_successfully", lambda *_: calls.append("goto"))
    monkeypatch.setattr(
        runner,
        "select_exact_resource",
        lambda _page, selector, _resource: calls.append(selector) or "/vm",
    )

    assert runner._select_target(page, "http://example/experiment", case, resolution) == "/vm"
    assert calls.index("#chaos_identity_id") < calls.index("#resource_id")


def test_select_target_selects_the_eks_cluster_before_workload_inputs(monkeypatch):
    calls = []
    region = SimpleNamespace(count=lambda: 1, select_option=lambda value: calls.append(("region", value)))
    page = SimpleNamespace(
        locator=lambda selector: region if selector == "#aws_region" else _locator(selector, calls),
        wait_for_function=lambda *_args, **_kwargs: None,
    )
    case = SimpleNamespace(
        cloud="aws", service="chaos_mesh",
        target={"region": "eu-central-1"},
        selector="#eks_cluster",
        resource_fields=(),
        inputs={"namespace": "sample-app", "pod": "sample-app-123"},
        id="eks-chaos-mesh",
    )
    resolution = SimpleNamespace(resources=[{"id": "cluster", "name": "cluster"}])
    monkeypatch.setattr(runner, "goto_successfully", lambda *_: calls.append("goto"))
    monkeypatch.setattr(
        runner,
        "select_exact_resource",
        lambda _page, selector, _resource: calls.append(selector) or "cluster",
    )
    monkeypatch.setattr(runner, "_fill_inputs", lambda _page, _case: calls.append("fill-inputs"))

    assert runner._select_target(page, "http://example/experiment", case, resolution) == "cluster"
    assert calls.index("#eks_cluster") < calls.index("fill-inputs")


def test_select_target_selects_native_eks_cluster_before_workload_inputs(monkeypatch):
    calls = []
    region = SimpleNamespace(count=lambda: 1, select_option=lambda value: calls.append(("region", value)))
    page = SimpleNamespace(
        locator=lambda selector: region if selector == "#aws_region" else _locator(selector, calls),
        wait_for_function=lambda *_args, **_kwargs: None,
    )
    case = SimpleNamespace(
        cloud="aws", service="eks", target={"region": "eu-central-1"},
        selector="#eks_cluster", resource_fields=(),
        inputs={"namespace": "sample-app", "pod_name": "sample-app-123"}, id="eks-restart",
    )
    resolution = SimpleNamespace(resources=[{"id": "cluster", "name": "cluster"}])
    monkeypatch.setattr(runner, "goto_successfully", lambda *_: calls.append("goto"))
    monkeypatch.setattr(
        runner,
        "select_exact_resource",
        lambda _page, selector, _resource: calls.append(selector) or "cluster",
    )
    monkeypatch.setattr(runner, "_fill_inputs", lambda _page, _case: calls.append("fill-inputs"))

    runner._select_target(page, "http://example/experiment", case, resolution)

    assert calls.index("#eks_cluster") < calls.index("fill-inputs")


def test_isolated_case_resolves_a_non_skipped_case(monkeypatch):
    case = SimpleNamespace(
        id="case", skip_reason="", target={}, cloud="aws", service="s3", experiment="s3-versioning",
        selector="#bucket_name", resource_fields=(), inputs={}, execute=False,
    )
    resolution = SimpleNamespace(status="found", resources=[{"id": "bucket", "name": "bucket"}])
    page = SimpleNamespace(close=lambda: None)
    browser = SimpleNamespace(new_page=lambda: page)
    config = SimpleNamespace(getoption=lambda _: False)
    monkeypatch.setattr(runner, "resolve", lambda _: resolution)
    monkeypatch.setattr(runner, "_select_target", lambda *_: "bucket")

    runner.test_functional_campaign_case(browser, case, "http://example", config)


def test_combined_review_accepts_ec2_instance_ids_target():
    case = SimpleNamespace(
        service="ec2",
        experiment="ec2-incremental-instance-stop",
        id="aws-ec2-ec2-incremental-instance-stop-tags",
        target={"fis_service_id": "", "fis_experiment_id": ""},
    )
    target = {"variable": "instance_ids", "value": "i-123"}

    runner._validate_combined_review(
        {
            "experiments": [
                {
                    "service": "ec2",
                    "id": "ec2-incremental-instance-stop",
                    "target": target,
                }
            ]
        },
        [(case, target)],
    )


@pytest.mark.parametrize(
    ("experiment", "variable", "value"),
    [
        ("elasticache-snapshot-retention", "replication_group_id", "redis-group"),
        ("elasticache-reboot", "cache_cluster_id", "redis-node-001"),
        ("elasticache-daily-snapshot", "replication_group_id", "redis-group"),
    ],
)
def test_isolated_review_accepts_elasticache_target(
    experiment, variable, value
):
    target = {"variable": variable, "value": value}

    runner.validate_campaign_review(
        {
            "experiments": [
                {
                    "service": "elasticache",
                    "id": experiment,
                    "target": target,
                }
            ]
        },
        "elasticache",
        experiment,
        target,
    )


def test_fill_inputs_normalizes_boolean_select_values(monkeypatch):
    calls = []
    page = SimpleNamespace(
        locator=lambda selector: _locator(selector, calls),
        wait_for_function=lambda _script, arg, **_kwargs: calls.append(arg["value"]),
    )
    case = SimpleNamespace(inputs={"abrupt_shutdown": False}, id="case")

    runner._fill_inputs(page, case)

    assert "false" in calls


def test_vmss_instance_selection_uses_visible_checkbox_picker(monkeypatch):
    calls = []
    checkbox = SimpleNamespace(wait_for=lambda **_: calls.append("visible"), check=lambda: calls.append("checked"))
    picker = SimpleNamespace(locator=lambda _: checkbox)
    page = SimpleNamespace(
        locator=lambda selector: picker if selector == "[data-azure-vmss-instance-picker]" else SimpleNamespace(),
        wait_for_function=lambda *_args, **_kwargs: calls.append("serialized"),
    )

    runner._select_vmss_instance(page, "instances", {"id": "0", "name": "Instance 0"})

    assert calls == ["visible", "checked", "serialized"]


def test_combined_campaign_execution_continues_after_a_failure(monkeypatch):
    requests = []
    page = SimpleNamespace(
        request=SimpleNamespace(
            post=lambda url, **kwargs: requests.append((url, kwargs)) or _response({"review_token": "token", "experiments": []})
        ),
        get_by_role=lambda *_args, **_kwargs: SimpleNamespace(click=lambda: None),
        wait_for_load_state=lambda *_args, **_kwargs: None,
        goto=lambda url, **_kwargs: requests.append((url, {})),
        wait_for_function=lambda *_args, **_kwargs: None,
        evaluate=lambda *_args: "run",
        url="http://example/campaign",
    )
    case = SimpleNamespace(id="case", service="azure_vmss", experiment="azure-vmss-shutdown", target_variable="resource_id")
    monkeypatch.setattr(runner, "_select_target", lambda *_: "/vmss")
    monkeypatch.setattr(runner, "_validate_combined_review", lambda *_: None)
    waits = []
    monkeypatch.setattr(
        runner,
        "wait_for_execution",
        lambda *_args, **kwargs: waits.append(kwargs["timeout_seconds"]) or {"status": "SUCCESS", "experiments": {}},
    )
    monkeypatch.setattr(runner, "_validate_combined_execution", lambda *_: None)

    runner._execute_combined_group(page, "http://example", "azure", [(case, SimpleNamespace())], 123)

    assert "continue_on_failure=true" in requests[-1][0]
    assert waits == [123]


def test_fis_case_uses_the_component_bound_fis_route():
    case = SimpleNamespace(
        service="fis",
        experiment="fis-create-experiment",
        target={"fis_service_id": "ec2", "fis_experiment_id": "stop-instances"},
    )

    assert runner._experiment_url("http://example", case) == (
        "http://example/experiment/fis/fis-create-experiment?"
        "fis_service_id=ec2&fis_experiment_id=stop-instances"
    )


def test_fis_review_and_execution_matching_require_the_bound_action():
    case = SimpleNamespace(
        service="fis",
        experiment="fis-create-experiment",
        target={"fis_service_id": "ec2", "fis_experiment_id": "stop-instances"},
    )
    target = {"variable": "target_arn", "value": "arn:aws:ec2:region:account:instance/i-1"}
    item = {
        "service": "fis", "id": "fis-create-experiment", "experiment_id": "fis-create-experiment",
        "target": target, "fis_service_id": "ec2", "fis_experiment_id": "stop-instances",
    }

    assert runner._matches_case(item, case, target, "id")
    item["fis_experiment_id"] = "reboot-instances"
    assert not runner._matches_case(item, case, target, "id")



def _locator(selector, calls):
    calls.append(selector)
    return SimpleNamespace(
        count=lambda: 1,
        evaluate=lambda *_: "SELECT",
        set_checked=lambda *_: None,
        select_option=lambda *_args, **_kwargs: None,
        fill=lambda *_: None,
    )


def _response(payload):
    return SimpleNamespace(ok=True, status=200, text=lambda: "", json=lambda: payload)
