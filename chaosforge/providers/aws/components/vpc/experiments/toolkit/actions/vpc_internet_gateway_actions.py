import json
import os
import tempfile

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "internet_gateway_state.json")


def get_client(region):

    return boto3.client("ec2", region_name=region)


def capture_and_detach_igw(internet_gateway_id, region):

    client = get_client(region)

    response = client.describe_internet_gateways(
        InternetGatewayIds=[internet_gateway_id]
    )

    gateway = response["InternetGateways"][0]

    if not gateway["Attachments"]:
        raise LookupError("Internet Gateway is not attached to any VPC.")

    attachment = gateway["Attachments"][0]

    vpc_id = attachment["VpcId"]

    #
    # Save original attachment
    #

    state = {
        "internet_gateway_id": internet_gateway_id,
        "vpc_id": vpc_id,
        "region": region,
    }

    with open(STATE_FILE, "w") as fp:
        json.dump(state, fp)

    print()

    print(f"Detaching Internet Gateway {internet_gateway_id}")

    client.detach_internet_gateway(InternetGatewayId=internet_gateway_id, VpcId=vpc_id)

    print("Internet Gateway detached successfully.")


def rollback_igw():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    print()

    print(f"Reattaching Internet Gateway {state['internet_gateway_id']}")

    client.attach_internet_gateway(
        InternetGatewayId=state["internet_gateway_id"], VpcId=state["vpc_id"]
    )

    os.remove(STATE_FILE)

    print("Internet Gateway restored successfully.")
