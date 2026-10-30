from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions import (
    _select_rule,
    capture_and_remove_rule,
    rollback_rule,
)


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.get_client")
def test_capture_and_remove_rule(mock_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    mock_client.return_value = client

    rule = {"RuleNumber": 100, "Egress": False}

    capture_and_remove_rule("acl-123", rule, "eu-central-1")

    client.delete_network_acl_entry.assert_called_once_with(
        NetworkAclId="acl-123", RuleNumber=100, Egress=False
    )

    mock_dump.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.get_client")
def test_capture_and_remove_rule_resolves_web_selected_index(
    mock_client, _mock_open_file, _mock_dump, _mock_print
):
    first = {"RuleNumber": 100, "Egress": False}
    selected = {"RuleNumber": 200, "Egress": True}
    client = MagicMock()
    client.describe_network_acls.return_value = {"NetworkAcls": [{"Entries": [first, selected]}]}
    mock_client.return_value = client

    capture_and_remove_rule("acl-123", "1", "eu-central-1")

    client.delete_network_acl_entry.assert_called_once_with(
        NetworkAclId="acl-123", RuleNumber=200, Egress=True
    )


@pytest.mark.parametrize(
    ("selected_rule", "message"),
    [("invalid", "invalid"), ("1", "unavailable")],
)
def test_select_rule_rejects_invalid_or_unavailable_selection(selected_rule, message):
    client = MagicMock()
    client.describe_network_acls.return_value = {
        "NetworkAcls": [{"Entries": [{"RuleNumber": 100, "Egress": False}]}]
    }

    with pytest.raises(ValueError, match=message):
        _select_rule(client, "acl-123", selected_rule)


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.get_client")
def test_rollback_ipv4(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "network_acl_id": "acl-123",
        "region": "eu-central-1",
        "rule": {
            "RuleNumber": 100,
            "Protocol": "6",
            "RuleAction": "allow",
            "Egress": False,
            "CidrBlock": "0.0.0.0/0",
        },
    }

    rollback_rule()

    client.create_network_acl_entry.assert_called_once()

    kwargs = client.create_network_acl_entry.call_args.kwargs

    assert kwargs["CidrBlock"] == "0.0.0.0/0"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.path.exists")
def test_state_file_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found"):
        rollback_rule()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.get_client")
def test_rollback_ipv6(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "network_acl_id": "acl",
        "region": "eu-central-1",
        "rule": {
            "RuleNumber": 100,
            "Protocol": "6",
            "RuleAction": "allow",
            "Egress": False,
            "Ipv6CidrBlock": "::/0",
        },
    }

    rollback_rule()

    kwargs = client.create_network_acl_entry.call_args.kwargs

    assert kwargs["Ipv6CidrBlock"] == "::/0"


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.get_client")
def test_rollback_port_range(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "network_acl_id": "acl",
        "region": "eu-central-1",
        "rule": {
            "RuleNumber": 100,
            "Protocol": "6",
            "RuleAction": "allow",
            "Egress": False,
            "CidrBlock": "0.0.0.0/0",
            "PortRange": {"From": 80, "To": 80},
        },
    }

    rollback_rule()

    kwargs = client.create_network_acl_entry.call_args.kwargs

    assert kwargs["PortRange"] == {"From": 80, "To": 80}


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_network_acl_actions.get_client")
def test_rollback_icmp(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "network_acl_id": "acl",
        "region": "eu-central-1",
        "rule": {
            "RuleNumber": 100,
            "Protocol": "1",
            "RuleAction": "allow",
            "Egress": False,
            "CidrBlock": "0.0.0.0/0",
            "IcmpTypeCode": {"Type": 8, "Code": 0},
        },
    }

    rollback_rule()

    kwargs = client.create_network_acl_entry.call_args.kwargs

    assert kwargs["IcmpTypeCode"] == {"Type": 8, "Code": 0}
