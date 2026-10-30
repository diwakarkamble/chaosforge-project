import json
import os
import tempfile

import boto3

STATE_FILE = os.path.join(tempfile.gettempdir(), "network_acl_state.json")


def get_client(region):

    return boto3.client("ec2", region_name=region)


def _select_rule(client, network_acl_id, selected_rule):
    if isinstance(selected_rule, dict):
        return selected_rule
    try:
        index = int(selected_rule)
    except (TypeError, ValueError) as exc:
        raise ValueError("Selected Network ACL rule is invalid.") from exc
    entries = client.describe_network_acls(NetworkAclIds=[network_acl_id])["NetworkAcls"][0]["Entries"]
    rules = [entry for entry in entries if entry["RuleNumber"] != 32767]
    if not 0 <= index < len(rules):
        raise ValueError("Selected Network ACL rule is unavailable.")
    return rules[index]


def capture_and_remove_rule(network_acl_id, selected_rule, region):

    client = get_client(region)
    selected_rule = _select_rule(client, network_acl_id, selected_rule)

    #
    # Save original rule
    #

    state = {"network_acl_id": network_acl_id, "region": region, "rule": selected_rule}

    with open(STATE_FILE, "w") as fp:
        json.dump(state, fp)

    print()

    print(f"Deleting Network ACL Rule {selected_rule['RuleNumber']}...")

    client.delete_network_acl_entry(
        NetworkAclId=network_acl_id,
        RuleNumber=selected_rule["RuleNumber"],
        Egress=selected_rule["Egress"],
    )

    print("Rule deleted successfully.")


def rollback_rule():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    rule = state["rule"]

    arguments = {
        "NetworkAclId": state["network_acl_id"],
        "RuleNumber": rule["RuleNumber"],
        "Protocol": rule["Protocol"],
        "RuleAction": rule["RuleAction"],
        "Egress": rule["Egress"],
    }

    #
    # Destination
    #

    if "CidrBlock" in rule:
        arguments["CidrBlock"] = rule["CidrBlock"]

    elif "Ipv6CidrBlock" in rule:
        arguments["Ipv6CidrBlock"] = rule["Ipv6CidrBlock"]

    #
    # Port Range
    #

    if "PortRange" in rule:
        arguments["PortRange"] = {
            "From": rule["PortRange"]["From"],
            "To": rule["PortRange"]["To"],
        }

    #
    # ICMP
    #

    if "IcmpTypeCode" in rule:
        arguments["IcmpTypeCode"] = {
            "Type": rule["IcmpTypeCode"]["Type"],
            "Code": rule["IcmpTypeCode"]["Code"],
        }

    print()

    print(f"Restoring Network ACL Rule {rule['RuleNumber']}...")

    client.create_network_acl_entry(**arguments)

    os.remove(STATE_FILE)

    print("Rule restored successfully.")
