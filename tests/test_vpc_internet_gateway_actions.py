from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions import (
    capture_and_detach_igw,
    rollback_igw,
)


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.get_client")
def test_capture_no_attachment(mock_client):
    client = MagicMock()

    client.describe_internet_gateways.return_value = {
        "InternetGateways": [{"Attachments": []}]
    }

    mock_client.return_value = client

    with pytest.raises(Exception, match="Internet Gateway is not attached to any VPC."):
        capture_and_detach_igw("igw-123", "eu-central-1")


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.json.dump")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.get_client")
def test_capture_and_detach(mock_client, mock_open_file, mock_dump, mock_print):
    client = MagicMock()

    client.describe_internet_gateways.return_value = {
        "InternetGateways": [{"Attachments": [{"VpcId": "vpc-123"}]}]
    }

    mock_client.return_value = client

    capture_and_detach_igw("igw-123", "eu-central-1")

    client.detach_internet_gateway.assert_called_once_with(
        InternetGatewayId="igw-123", VpcId="vpc-123"
    )


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.os.path.exists")
def test_rollback_state_missing(mock_exists):
    mock_exists.return_value = False

    with pytest.raises(Exception, match="State file not found."):
        rollback_igw()


@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.print")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.os.remove")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.json.load")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.os.path.exists")
@patch("chaosforge.providers.aws.components.vpc.experiments.toolkit.actions.vpc_internet_gateway_actions.get_client")
def test_rollback_igw(
    mock_client, mock_exists, mock_load, mock_open_file, mock_remove, mock_print
):
    mock_exists.return_value = True

    client = MagicMock()

    mock_client.return_value = client

    mock_load.return_value = {
        "internet_gateway_id": "igw-123",
        "vpc_id": "vpc-123",
        "region": "eu-central-1",
    }

    rollback_igw()

    client.attach_internet_gateway.assert_called_once_with(
        InternetGatewayId="igw-123", VpcId="vpc-123"
    )

    mock_remove.assert_called_once()
