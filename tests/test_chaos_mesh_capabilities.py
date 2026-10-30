from chaosforge.engines.chaos_mesh.chaos_mesh_capabilities import (
    CHAOS_MESH_CAPABILITIES,
    capability_summary,
    get_chaos_mesh_capability,
    is_supported_chaos_mesh_kind,
    list_chaos_mesh_capabilities,
)


def test_all_expected_chaos_mesh_capabilities_are_registered():
    expected = {
        "PodChaos",
        "NetworkChaos",
        "DNSChaos",
        "HTTPChaos",
        "StressChaos",
        "IOChaos",
        "TimeChaos",
        "KernelChaos",
        "AWSChaos",
        "JVMChaos",
        "BlockChaos",
        "PhysicalMachineChaos",
        "Workflow",
        "Schedule",
        "StatusCheck",
    }

    assert expected.issubset(CHAOS_MESH_CAPABILITIES.keys())


def test_get_capability():
    capability = get_chaos_mesh_capability("NetworkChaos")

    assert capability is not None
    assert capability.kind == "NetworkChaos"
    assert capability.category == "network"


def test_unknown_capability_returns_none():
    assert get_chaos_mesh_capability("NotAChaosKind") is None


def test_supported_kind():
    assert is_supported_chaos_mesh_kind("PodChaos") is True
    assert is_supported_chaos_mesh_kind("NotAChaosKind") is False


def test_list_capabilities():
    capabilities = list_chaos_mesh_capabilities()

    assert len(capabilities) >= 15
    assert all(capability.kind for capability in capabilities)


def test_capability_summary_is_json_friendly():
    summary = capability_summary()

    assert summary
    assert all(isinstance(item, dict) for item in summary)

    network = next(
        item for item in summary
        if item["kind"] == "NetworkChaos"
    )

    assert network["category"] == "network"
    assert network["supports_duration"] is True
