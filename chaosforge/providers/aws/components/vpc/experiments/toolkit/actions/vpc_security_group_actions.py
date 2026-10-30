import json
import os
import tempfile

import boto3
from rich.console import Console
from rich.table import Table

console = Console()

STATE_FILE = os.path.join(tempfile.gettempdir(), "security_group_state.json")


def get_client(region):

    return boto3.client("ec2", region_name=region)


def capture_and_remove_rule(security_group_id, region, selected_rule=None):

    client = get_client(region)

    response = client.describe_security_groups(GroupIds=[security_group_id])

    group = response["SecurityGroups"][0]

    permissions = group.get("IpPermissions", [])

    if not permissions:
        raise ValueError("Security Group has no ingress rules.")

    #
    # Display Available Rules
    #

    table = Table(title=f"Ingress Rules : {group['GroupName']}")

    table.add_column("#", justify="right")
    table.add_column("Protocol")
    table.add_column("Port")
    table.add_column("Source")

    for index, rule in enumerate(permissions, start=1):
        protocol = rule.get("IpProtocol", "ALL")

        if protocol == "-1":
            protocol = "ALL"

        if "FromPort" in rule:
            if rule.get("FromPort") == rule.get("ToPort"):
                port = str(rule["FromPort"])

            else:
                port = f"{rule['FromPort']}-{rule['ToPort']}"

        else:
            port = "ALL"

        #
        # Source CIDR
        #

        if rule.get("IpRanges"):
            source = ", ".join(ip["CidrIp"] for ip in rule["IpRanges"])

        #
        # IPv6
        #

        elif rule.get("Ipv6Ranges"):
            source = ", ".join(ip["CidrIpv6"] for ip in rule["Ipv6Ranges"])

        #
        # Security Group Reference
        #

        elif rule.get("UserIdGroupPairs"):
            source = ", ".join(sg["GroupId"] for sg in rule["UserIdGroupPairs"])

        else:
            source = "N/A"

        table.add_row(str(index), protocol.upper(), port, source)

    console.print()

    console.print(table)

    console.print()

    if selected_rule is None:
        # Legacy CLI callers that did not collect a rule can still choose one.
        while True:
            choice = input("Select Rule Number : ").strip()
            try:
                index = int(choice)
                if index < 1 or index > len(permissions):
                    raise ValueError
                selected_rule = index - 1
                break
            except ValueError:
                print("Invalid Selection.")

    try:
        selected_rule = int(selected_rule)
    except (TypeError, ValueError) as exc:
        raise ValueError("Selected security group rule is invalid.") from exc
    if not 0 <= selected_rule < len(permissions):
        raise ValueError("Selected security group rule is unavailable.")

    selected_rule = permissions[selected_rule]

    #
    # Save State
    #

    state = {
        "security_group_id": security_group_id,
        "region": region,
        "rule": selected_rule,
    }

    with open(STATE_FILE, "w") as fp:
        json.dump(state, fp)

    #
    # Remove Rule
    #

    client.revoke_security_group_ingress(
        GroupId=security_group_id, IpPermissions=[selected_rule]
    )

    print()

    print("✓ Security Group rule removed.")


def rollback_security_group():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    client.authorize_security_group_ingress(
        GroupId=state["security_group_id"], IpPermissions=[state["rule"]]
    )

    os.remove(STATE_FILE)

    print()

    print("✓ Security Group rule restored.")
