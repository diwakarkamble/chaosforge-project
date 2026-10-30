from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chaosforge.lifecycle.checks.azure_redis_adapter import AzureRedisAdapter
from chaosforge.lifecycle.checks.common import CommonResourceCheck
from chaosforge.lifecycle.checks.resolver import CheckResolver
from chaosforge.lifecycle.lifecycle_report import LifecycleReportRenderer


@pytest.mark.parametrize(
    ("experiment_id", "recovery_supported"),
    [
        ("azure-redis-reboot", True),
        ("azure-redis-flush", False),
        ("azure-redis-access-disruption", True),
    ],
)
def test_azure_redis_experiments_resolve_lifecycle_checks(
    experiment_id, recovery_supported
):
    check = CheckResolver().resolve(
        SimpleNamespace(id=experiment_id, service="azure_redis", variables={})
    )

    assert isinstance(check, CommonResourceCheck)
    assert isinstance(check.adapter, AzureRedisAdapter)
    assert check.name == f"{experiment_id}-lifecycle"
    assert check.recovery_supported is recovery_supported


def test_azure_redis_adapter_captures_availability_and_access_configuration(monkeypatch):
    client = SimpleNamespace(
        redis=SimpleNamespace(
            get=MagicMock(
                return_value=SimpleNamespace(
                    name="cache",
                    id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache",
                    provisioning_state="Succeeded",
                    public_network_access="Enabled",
                    sku=SimpleNamespace(name="Premium"),
                )
            )
        )
    )
    import azure.mgmt.redis

    monkeypatch.setattr(azure.mgmt.redis, "RedisManagementClient", lambda *_: client)

    snapshot = AzureRedisAdapter().capture(
        {"subscription_id": "sub", "resource_group": "rg", "redis_name": "cache"}
    )

    assert snapshot["exists"] is True
    assert snapshot["state"]["provisioning_state"] == "Succeeded"
    assert snapshot["configuration"]["public_network_access"] == "Enabled"
    assert snapshot["configuration"]["sku"] == "Premium"


@pytest.mark.parametrize(
    "experiment_id",
    ["azure-redis-flush", "azure-redis-access-disruption"],
)
def test_azure_redis_custom_experiments_derive_cache_name_from_resource_id(
    monkeypatch, experiment_id
):
    client = SimpleNamespace(
        redis=SimpleNamespace(
            get=MagicMock(
                return_value=SimpleNamespace(
                    name="cache",
                    id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache",
                    provisioning_state="Succeeded",
                    public_network_access="Enabled",
                    sku=SimpleNamespace(name="Premium"),
                )
            )
        )
    )
    import azure.mgmt.redis

    monkeypatch.setattr(azure.mgmt.redis, "RedisManagementClient", lambda *_: client)
    check = CheckResolver().resolve(
        SimpleNamespace(id=experiment_id, service="azure_redis", variables={})
    )
    target = {
        "subscription_id": "sub",
        "resource_group": "rg",
        "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Cache/redis/cache",
    }

    snapshot = check.capture(target)

    assert snapshot["identity"]["name"] == "cache"
    client.redis.get.assert_called_once_with("rg", "cache")


def test_azure_redis_adapter_requires_a_target_identity():
    with pytest.raises(ValueError, match="redis_name or resource_id"):
        AzureRedisAdapter().capture({"subscription_id": "sub", "resource_group": "rg"})


def test_redis_reboot_and_access_disruption_validate_recovery():
    resolver = CheckResolver()
    baseline = {
        "exists": True,
        "state": {"provisioning_state": "Succeeded"},
        "configuration": {"public_network_access": "Enabled"},
    }
    current = dict(baseline)

    reboot = resolver.resolve(
        SimpleNamespace(id="azure-redis-reboot", service="azure_redis", variables={})
    )
    access = resolver.resolve(
        SimpleNamespace(
            id="azure-redis-access-disruption", service="azure_redis", variables={}
        )
    )
    reboot.adapter.capture = lambda _: current
    access.adapter.capture = lambda _: current

    assert reboot.validate({}, baseline)["passed"] is True
    assert access.validate({}, baseline)["passed"] is True

    access.adapter.capture = lambda _: {
        **baseline,
        "configuration": {"public_network_access": "Disabled"},
    }
    assert access.validate({}, baseline)["passed"] is False


def test_redis_lifecycle_report_includes_pre_execution_and_post_sections():
    report = LifecycleReportRenderer().render(
        precheck={
            "enabled": True,
            "check": "azure-redis-reboot-lifecycle",
            "resource": "cache",
            "baseline": "Captured",
            "passed": True,
        },
        injection={
            "check": "Reboot Redis",
            "success": True,
            "display": {"Expected": "AllNodes", "Observed": "Applied successfully"},
        },
        validation={
            "enabled": True,
            "check": "azure-redis-reboot-lifecycle",
            "passed": True,
            "display": {"Expected": "Succeeded", "Observed": "Succeeded"},
        },
    )

    assert "PRE-CHECK" in report
    assert "CHAOS EXECUTION" in report
    assert "POST-VALIDATION" in report
    assert "azure-redis-reboot-lifecycle" in report
    assert "OVERALL     : PASSED" in report
