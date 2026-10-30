from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions import (
    _select_route,
    capture_and_remove_route,
    rollback_route,
)


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_capture_and_remove_ipv4_route(
    mock_client, mock_open_file, mock_dump, mock_print
):
    client = MagicMock()

    mock_client.return_value = client

    route = {"DestinationCidrBlock": "0.0.0.0/0"}

    capture_and_remove_route("rtb-123", route, "eu-central-1")

    client.delete_route.assert_called_once_with(
        RouteTableId="rtb-123", DestinationCidrBlock="0.0.0.0/0"
    )


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_capture_and_remove_route_resolves_web_selected_index(
    mock_client, _mock_open_file, _mock_dump, _mock_print
):
    local = {"DestinationCidrBlock": "10.0.0.0/16", "GatewayId": "local"}
    first = {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1"}
    selected = {"DestinationCidrBlock": "172.16.0.0/12", "GatewayId": "igw-2"}
    client = MagicMock()
    client.describe_route_tables.return_value = {"RouteTables": [{"Routes": [local, first, selected]}]}
    mock_client.return_value = client

    capture_and_remove_route("rtb-123", "1", "eu-central-1")

    client.delete_route.assert_called_once_with(
        RouteTableId="rtb-123", DestinationCidrBlock="172.16.0.0/12"
    )


@pytest.mark.parametrize(
    ("selected_route", "message"),
    [("invalid", "invalid"), ("1", "unavailable")],
)
def test_select_route_rejects_invalid_or_unavailable_selection(selected_route, message):
    client = MagicMock()
    client.describe_route_tables.return_value = {
        "RouteTables": [{"Routes": [{"DestinationCidrBlock": "0.0.0.0/0"}]}]
    }

    with pytest.raises(ValueError, match=message):
        _select_route(client, "rtb-123", selected_route)


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_capture_and_remove_ipv6_route(
    mock_client, mock_open_file, mock_dump, mock_print
):
    client = MagicMock()

    mock_client.return_value = client

    route = {"DestinationIpv6CidrBlock": "::/0"}

    capture_and_remove_route("rtb", route, "eu-central-1")

    kwargs = client.delete_route.call_args.kwargs

    assert kwargs["DestinationIpv6CidrBlock"] == "::/0"


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_capture_and_remove_prefix_list(
    mock_client, mock_open_file, mock_dump, mock_print
):
    client = MagicMock()

    mock_client.return_value = client

    route = {"DestinationPrefixListId": "pl-123"}

    capture_and_remove_route("rtb", route, "eu-central-1")

    kwargs = client.delete_route.call_args.kwargs

    assert kwargs["DestinationPrefixListId"] == "pl-123"


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_gateway(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["GatewayId"] == "igw-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
def test_state_file_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found"):
        rollback_route()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_unsupported_target(mock_client, mock_exists, mock_load, mock_open_file):
    mock_exists.return_value = True

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0"},
    }

    with pytest.raises(Exception, match="Unsupported route target"):
        rollback_route()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_nat_gateway(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["NatGatewayId"] == "nat-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_transit_gateway(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0", "TransitGatewayId": "tgw-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["TransitGatewayId"] == "tgw-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_vpc_peering(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {
            "DestinationCidrBlock": "0.0.0.0/0",
            "VpcPeeringConnectionId": "pcx-123",
        },
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["VpcPeeringConnectionId"] == "pcx-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_network_interface(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0", "NetworkInterfaceId": "eni-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["NetworkInterfaceId"] == "eni-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_instance(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0", "InstanceId": "i-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["InstanceId"] == "i-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_vpc_endpoint(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationCidrBlock": "0.0.0.0/0", "VpcEndpointId": "vpce-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["VpcEndpointId"] == "vpce-123"

    mock_remove.assert_called_once()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_ipv6_route(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationIpv6CidrBlock": "::/0", "GatewayId": "igw-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["DestinationIpv6CidrBlock"] == "::/0"
    assert kwargs["GatewayId"] == "igw-123"


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_route_table_actions.get_client")
def test_rollback_prefix_list_route(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()
    mock_client.return_value = client

    mock_load.return_value = {
        "route_table_id": "rtb",
        "region": "eu-central-1",
        "route": {"DestinationPrefixListId": "pl-123", "GatewayId": "igw-123"},
    }

    rollback_route()

    kwargs = client.create_route.call_args.kwargs

    assert kwargs["DestinationPrefixListId"] == "pl-123"
    assert kwargs["GatewayId"] == "igw-123"
