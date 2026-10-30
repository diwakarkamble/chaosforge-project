import json
import os
import tempfile

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "route_table_state.json")


def get_client(region):

    return boto3.client("ec2", region_name=region)


def _select_route(client, route_table_id, selected_route):
    if isinstance(selected_route, dict):
        return selected_route
    try:
        index = int(selected_route)
    except (TypeError, ValueError) as exc:
        raise ValueError("Selected route is invalid.") from exc
    routes = client.describe_route_tables(RouteTableIds=[route_table_id])["RouteTables"][0]["Routes"]
    selectable = [
        route
        for route in routes
        if route.get("Origin") != "EnableVgwRoutePropagation"
        and route.get("GatewayId") != "local"
    ]
    if not 0 <= index < len(selectable):
        raise ValueError("Selected route is unavailable.")
    return selectable[index]


def capture_and_remove_route(route_table_id, selected_route, region):

    client = get_client(region)
    selected_route = _select_route(client, route_table_id, selected_route)

    #
    # Save state
    #

    state = {
        "route_table_id": route_table_id,
        "region": region,
        "route": selected_route,
    }

    with open(STATE_FILE, "w") as fp:
        json.dump(state, fp)

    #
    # Destination
    #

    arguments = {"RouteTableId": route_table_id}

    if "DestinationCidrBlock" in selected_route:
        arguments["DestinationCidrBlock"] = selected_route["DestinationCidrBlock"]

    elif "DestinationIpv6CidrBlock" in selected_route:
        arguments["DestinationIpv6CidrBlock"] = selected_route[
            "DestinationIpv6CidrBlock"
        ]

    elif "DestinationPrefixListId" in selected_route:
        arguments["DestinationPrefixListId"] = selected_route["DestinationPrefixListId"]

    print()

    print("Deleting Route...")

    client.delete_route(**arguments)

    print("Route deleted successfully.")


def rollback_route():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    route = state["route"]

    arguments = {"RouteTableId": state["route_table_id"]}

    #
    # Destination
    #

    if "DestinationCidrBlock" in route:
        arguments["DestinationCidrBlock"] = route["DestinationCidrBlock"]

    elif "DestinationIpv6CidrBlock" in route:
        arguments["DestinationIpv6CidrBlock"] = route["DestinationIpv6CidrBlock"]

    elif "DestinationPrefixListId" in route:
        arguments["DestinationPrefixListId"] = route["DestinationPrefixListId"]

    #
    # Target
    #

    if "GatewayId" in route:
        arguments["GatewayId"] = route["GatewayId"]

    elif "NatGatewayId" in route:
        arguments["NatGatewayId"] = route["NatGatewayId"]

    elif "TransitGatewayId" in route:
        arguments["TransitGatewayId"] = route["TransitGatewayId"]

    elif "VpcPeeringConnectionId" in route:
        arguments["VpcPeeringConnectionId"] = route["VpcPeeringConnectionId"]

    elif "NetworkInterfaceId" in route:
        arguments["NetworkInterfaceId"] = route["NetworkInterfaceId"]

    elif "InstanceId" in route:
        arguments["InstanceId"] = route["InstanceId"]

    elif "VpcEndpointId" in route:
        arguments["VpcEndpointId"] = route["VpcEndpointId"]

    else:
        raise ValueError("Unsupported route target.")

    print()

    print("Restoring Route...")

    client.create_route(**arguments)

    os.remove(STATE_FILE)

    print("Route restored successfully.")
