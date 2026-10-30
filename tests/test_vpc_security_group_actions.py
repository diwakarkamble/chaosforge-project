from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions import (
    capture_and_remove_rule,
    rollback_security_group,
)


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_no_ingress_rules(mock_client):
    client = MagicMock()

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "sg", "IpPermissions": []}]
    }

    mock_client.return_value = client

    with pytest.raises(Exception, match="Security Group has no ingress rules"):
        capture_and_remove_rule("sg-1", "eu-central-1")


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_ipv4_rule(
    mock_client, mock_open_file, mock_dump, mock_console, mock_input
):
    client = MagicMock()

    rule = {
        "IpProtocol": "tcp",
        "FromPort": 80,
        "ToPort": 80,
        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
    }

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1")

    client.revoke_security_group_ingress.assert_called_once_with(
        GroupId="sg-1", IpPermissions=[rule]
    )


@patch("builtins.input")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_selected_rule_without_interactive_prompt(
    mock_client, _mock_open_file, _mock_dump, _mock_console, mock_input
):
    first_rule = {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80}
    selected_rule = {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443}
    client = MagicMock()
    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [first_rule, selected_rule]}]
    }
    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1", selected_rule="1")

    mock_input.assert_not_called()
    client.revoke_security_group_ingress.assert_called_once_with(
        GroupId="sg-1", IpPermissions=[selected_rule]
    )


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_rejects_unavailable_selected_rule(mock_client):
    client = MagicMock()
    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [{"IpProtocol": "tcp"}]}]
    }
    mock_client.return_value = client

    with pytest.raises(ValueError, match="unavailable"):
        capture_and_remove_rule("sg-1", "eu-central-1", selected_rule="2")


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_rejects_invalid_selected_rule(mock_client):
    client = MagicMock()
    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [{"IpProtocol": "tcp"}]}]
    }
    mock_client.return_value = client

    with pytest.raises(ValueError, match="invalid"):
        capture_and_remove_rule("sg-1", "eu-central-1", selected_rule="invalid")

    client.revoke_security_group_ingress.assert_not_called()


@patch("builtins.input", side_effect=["5", "abc", "1"])
@patch("builtins.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_invalid_selection_then_valid(
    mock_client, mock_open_file, mock_dump, mock_console, mock_print, mock_input
):
    client = MagicMock()

    rule = {"IpProtocol": "tcp", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg", "eu-central-1")

    assert mock_input.call_count == 3


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.os.path.exists")
def test_state_file_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found"):
        rollback_security_group()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_rollback_security_group(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    rule = {"IpProtocol": "tcp"}

    mock_load.return_value = {
        "security_group_id": "sg-1",
        "region": "eu-central-1",
        "rule": rule,
    }

    rollback_security_group()

    client.authorize_security_group_ingress.assert_called_once_with(
        GroupId="sg-1", IpPermissions=[rule]
    )

    mock_remove.assert_called_once()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_ipv6_rule(
    mock_client, mock_open_file, mock_dump, mock_console, mock_input
):
    client = MagicMock()

    rule = {
        "IpProtocol": "tcp",
        "FromPort": 80,
        "ToPort": 80,
        "Ipv6Ranges": [{"CidrIpv6": "::/0"}],
    }

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "ipv6", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1")

    client.revoke_security_group_ingress.assert_called_once()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_sg_reference_rule(
    mock_client, mock_open_file, mock_dump, mock_console, mock_input
):
    client = MagicMock()

    rule = {
        "IpProtocol": "tcp",
        "FromPort": 80,
        "ToPort": 80,
        "UserIdGroupPairs": [{"GroupId": "sg-999"}],
    }

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1")

    client.revoke_security_group_ingress.assert_called_once()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_all_protocol_rule(
    mock_client, mock_open_file, mock_dump, mock_console, mock_input
):
    client = MagicMock()

    rule = {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1")

    client.revoke_security_group_ingress.assert_called_once()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_port_range_rule(
    mock_client, mock_open_file, mock_dump, mock_console, mock_input
):
    client = MagicMock()

    rule = {
        "IpProtocol": "tcp",
        "FromPort": 1000,
        "ToPort": 2000,
        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
    }

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1")

    client.revoke_security_group_ingress.assert_called_once()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.console.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_security_group_actions.get_client")
def test_remove_rule_without_source(
    mock_client, mock_open_file, mock_dump, mock_console, mock_input
):
    client = MagicMock()

    rule = {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80}

    client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupName": "web", "IpPermissions": [rule]}]
    }

    mock_client.return_value = client

    capture_and_remove_rule("sg-1", "eu-central-1")

    client.revoke_security_group_ingress.assert_called_once()
