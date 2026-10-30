"""Structured AWS resource and metadata-graph lookup for functional E2E."""

from __future__ import annotations

from typing import Any

# Resource Groups Tagging API names.  Types absent here cannot be selected by
# tag, so graph resolution deliberately falls back to an exact-one child.
RESOURCE_TYPES = {
    "s3": ["s3"], "lambda": ["lambda:function"], "dynamodb": ["dynamodb:table"],
    "elb": ["elasticloadbalancing:loadbalancer"], "elb-target-group": ["elasticloadbalancing:targetgroup"],
    "elasticache": ["elasticache:replicationgroup"], "elasticache-replication-group": ["elasticache:replicationgroup"],
    "elasticache-cache-cluster": ["elasticache:cluster"], "apigateway": ["apigateway:restapis"],
    "ec2": ["ec2:instance"], "ebs-volume": ["ec2:volume"], "ebs-volume-available": ["ec2:volume"],
    "ebs-volume-asg-available": ["ec2:volume"], "autoscaling-group": ["autoscaling:autoScalingGroup"],
    "ecs": ["ecs:cluster"], "ecs-service": ["ecs:service"], "eks": ["eks:cluster"], "kinesis": ["kinesis:stream"],
    "rds": ["rds:db"], "sns": ["sns:topic"], "sns_subscription": ["sns:subscription"],
    "security-group": ["ec2:security-group"], "route-table": ["ec2:route-table"],
    "network-acl": ["ec2:network-acl"], "internet-gateway": ["ec2:internet-gateway"],
}


def resolve(target: dict[str, Any]) -> tuple[str, list[dict[str, str]], str]:
    """Resolve one top-level resource, retaining the original runner contract."""
    service = target.get("resolver_service", target["service"])
    if service not in RESOURCE_TYPES:
        return "unsupported", [], f"AWS functional resolver does not support component {service!r}."
    try:
        session = _session(target)
        resources = _tagged(session, service, target["target"]) if target["target_type"] == "tags" else _roots(session, service)
        if target["target_type"] != "tags":
            resources = _match(resources, str(target["target"]))
    except Exception as exc:  # noqa: BLE001 - turn local cloud setup failures into runner outcomes.
        return "environment_error", [], f"AWS lookup failed for {service}: {exc}"
    return _outcome(service, resources, target.get("target"))


def resolve_graph(target: dict[str, Any], resource_fields: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, str]], str]:
    """Resolve ordered ``aws_resource`` metadata fields into one safe graph.

    ``resource_fields`` are metadata inputs with at least ``name`` and
    ``resource_type`` and, for descendants, ``parent``.  The return mapping is
    keyed by input name so a browser runner can select each resolved option in
    metadata order.  A child is never chosen by position: it must match the
    supplied tags where taggable, or be the only candidate below its parent.
    """
    if not resource_fields:
        return "found", {}, ""
    try:
        session = _session(target)
        selected: dict[str, dict[str, str]] = {}
        selected_types: dict[str, str] = {}
        for field in resource_fields:
            name, kind, parent_name = field["name"], field["resource_type"], field.get("parent")
            if parent_name:
                if parent_name not in selected:
                    return "unsupported", selected, f"AWS graph field {name!r} has unresolved parent {parent_name!r}."
                candidates = _children(session, selected_types[parent_name], selected[parent_name], kind)
                # A taggable child must satisfy the same tag predicate as its root.
                if target["target_type"] == "tags" and kind in RESOURCE_TYPES:
                    tagged = _tagged(session, kind, target["target"])
                    candidates = _intersect(candidates, tagged)
            elif target["target_type"] == "tags":
                if kind not in RESOURCE_TYPES:
                    return "unsupported", selected, f"AWS resource type {kind!r} cannot be tag-resolved without a parent."
                candidates = _tagged_roots(session, kind, target["target"])
            else:
                candidates = _match(_roots(session, kind), str(target["target"]))
            override = target.get("resource_overrides", {}).get(name)
            if override is not None:
                candidates = _match(candidates, str(override))
            status, _, reason = _outcome(kind, candidates, target.get("target"))
            if status != "found":
                return status, selected, f"{name}: {reason}"
            selected[name], selected_types[name] = candidates[0], kind
        return "found", selected, ""
    except Exception as exc:  # noqa: BLE001
        return "environment_error", {}, f"AWS graph lookup failed: {exc}"


def _session(target):
    import boto3
    return boto3.Session(profile_name=target.get("profile") or None, region_name=target["region"])


def _outcome(kind, resources, target):
    if not resources:
        return "missing", [], f"No AWS {kind} resource matched {target!r}."
    if len(resources) != 1:
        return "ambiguous", resources, f"AWS {kind} selection matched {len(resources)} resources."
    return "found", resources, ""


def _tagged(session, kind, tags):
    pages = session.client("resourcegroupstaggingapi").get_paginator("get_resources").paginate(
        ResourceTypeFilters=RESOURCE_TYPES[kind],
        TagFilters=[{"Key": key, "Values": [value]} for key, value in tags.items()],
    )
    return [_resource(item["ResourceARN"]) for page in pages for item in page.get("ResourceTagMappingList", [])]


def _tagged_roots(session, kind, tags):
    """Return native IDs for tagged roots when an ARN is not an API input."""
    tagged = _tagged(session, kind, tags)
    roots = _roots(session, kind)
    return _intersect(roots, tagged)


def _roots(session, kind):
    if kind == "s3":
        return [_item(f"arn:aws:s3:::{x['Name']}", x["Name"]) for x in session.client("s3").list_buckets().get("Buckets", [])]
    if kind == "lambda":
        return [_item(x["FunctionArn"], x["FunctionName"]) for p in _pages(session, "lambda", "list_functions") for x in p.get("Functions", [])]
    if kind == "dynamodb":
        client = session.client("dynamodb")
        return [_item(t["TableArn"], name) for p in _pages(session, "dynamodb", "list_tables") for name in p.get("TableNames", []) for t in [client.describe_table(TableName=name)["Table"]]]
    if kind in {"elb", "elb-target-group"}:
        key, name = ("LoadBalancers", "LoadBalancerName") if kind == "elb" else ("TargetGroups", "TargetGroupName")
        arn = "LoadBalancerArn" if kind == "elb" else "TargetGroupArn"
        operation = "describe_load_balancers" if kind == "elb" else "describe_target_groups"
        return [_item(x[arn], x[name]) for p in _pages(session, "elbv2", operation) for x in p.get(key, [])]
    if kind in {"elasticache", "elasticache-replication-group"}:
        return [_item(x.get("ARN", x["ReplicationGroupId"]), x["ReplicationGroupId"]) for p in _pages(session, "elasticache", "describe_replication_groups") for x in p.get("ReplicationGroups", [])]
    if kind == "elasticache-cache-cluster":
        return [_item(x.get("ARN", x["CacheClusterId"]), x["CacheClusterId"]) for p in _pages(session, "elasticache", "describe_cache_clusters") for x in p.get("CacheClusters", [])]
    if kind == "apigateway":
        return [_item(x["id"], x["name"]) for p in _pages(session, "apigateway", "get_rest_apis") for x in p.get("items", [])]
    if kind == "ec2":
        return [_item(x["InstanceId"], x["InstanceId"]) for p in _pages(session, "ec2", "describe_instances") for r in p.get("Reservations", []) for x in r.get("Instances", [])]
    if kind in {"ebs-volume", "ebs-volume-available", "ebs-volume-asg-available"}:
        return [_item(x["VolumeId"], x["VolumeId"]) for p in _pages(session, "ec2", "describe_volumes") for x in p.get("Volumes", []) if kind == "ebs-volume" or x.get("State") == "available"]
    if kind == "autoscaling-group":
        return [_item(x["AutoScalingGroupName"], x["AutoScalingGroupName"]) for p in _pages(session, "autoscaling", "describe_auto_scaling_groups") for x in p.get("AutoScalingGroups", [])]
    if kind == "ecs":
        return [_item(x, x.rsplit("/", 1)[-1]) for p in _pages(session, "ecs", "list_clusters") for x in p.get("clusterArns", [])]
    if kind == "eks":
        return [_item(x, x) for p in _pages(session, "eks", "list_clusters") for x in p.get("clusters", [])]
    if kind == "kinesis":
        client = session.client("kinesis")
        return [
            _item(stream["StreamARN"], name)
            for page in client.get_paginator("list_streams").paginate()
            for name in page.get("StreamNames", [])
            for stream in [client.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]]
        ]
    if kind == "rds":
        return [_item(x["DBInstanceArn"], x["DBInstanceIdentifier"]) for p in _pages(session, "rds", "describe_db_instances") for x in p.get("DBInstances", [])]
    if kind == "sns":
        return [_item(x["TopicArn"], x["TopicArn"].rsplit(":", 1)[-1]) for p in _pages(session, "sns", "list_topics") for x in p.get("Topics", [])]
    if kind == "sns_subscription":
        return [_item(x["SubscriptionArn"], x["SubscriptionArn"]) for p in _pages(session, "sns", "list_subscriptions") for x in p.get("Subscriptions", [])]
    if kind in {"security-group", "route-table", "network-acl", "internet-gateway"}:
        plural, ident = {"security-group": ("SecurityGroups", "GroupId"), "route-table": ("RouteTables", "RouteTableId"), "network-acl": ("NetworkAcls", "NetworkAclId"), "internet-gateway": ("InternetGateways", "InternetGatewayId")}[kind]
        operation = "describe_" + plural.replace("Groups", "_groups").replace("Tables", "_tables").replace("Acls", "_acls").replace("Gateways", "_gateways").lower()
        return [_item(x[ident], x.get("GroupName", x[ident])) for p in _pages(session, "ec2", operation) for x in p.get(plural, [])]
    raise ValueError(f"unsupported AWS resource type {kind!r}")


def _children(session, parent_kind, parent, kind):
    pid = parent["id"]
    if (parent_kind, kind) == ("apigateway", "apigateway-stage"):
        return [_item(x["stageName"], x["stageName"]) for x in session.client("apigateway").get_stages(restApiId=pid).get("item", [])]
    if parent_kind == "ec2" and kind == "ebs-volume":
        return [_item(x["Ebs"]["VolumeId"], x["Ebs"]["VolumeId"]) for p in _pages(session, "ec2", "describe_instances", InstanceIds=[pid]) for r in p.get("Reservations", []) for x in r.get("Instances", []) for x in x.get("BlockDeviceMappings", []) if x.get("Ebs")]
    if parent_kind == "ec2" and kind == "ebs-volume-available":
        return _roots(session, kind)
    if parent_kind == "autoscaling-group" and kind == "ebs-volume-asg-available":
        return _roots(session, kind)
    if (parent_kind, kind) == ("ecs", "ecs-service"):
        return [_item(x, x.rsplit("/", 1)[-1]) for p in _pages(session, "ecs", "list_services", cluster=pid) for x in p.get("serviceArns", [])]
    if (parent_kind, kind) == ("elb", "elb-target-group"):
        return [_item(x["TargetGroupArn"], x["TargetGroupName"]) for p in _pages(session, "elbv2", "describe_target_groups", LoadBalancerArn=pid) for x in p.get("TargetGroups", [])]
    if (parent_kind, kind) == ("elb", "elb-listener"):
        return [_item(x["ListenerArn"], x["ListenerArn"].rsplit("/", 1)[-1]) for p in _pages(session, "elbv2", "describe_listeners", LoadBalancerArn=pid) for x in p.get("Listeners", [])]
    if (parent_kind, kind) == ("elb-target-group", "elb-target"):
        return [_item(x["Target"]["Id"], x["Target"]["Id"]) for p in _pages(session, "elbv2", "describe_target_health", TargetGroupArn=pid) for x in p.get("TargetHealthDescriptions", [])]
    if (parent_kind, kind) == ("security-group", "security-group-rule"):
        groups = [
            group
            for page in _pages(session, "ec2", "describe_security_groups", GroupIds=[pid])
            for group in page.get("SecurityGroups", [])
        ]
        rules = [
            rule
            for page in _pages(
                session,
                "ec2",
                "describe_security_group_rules",
                Filters=[{"Name": "group-id", "Values": [pid]}],
            )
            for rule in page.get("SecurityGroupRules", [])
            if not rule.get("IsEgress")
        ]
        return [
            _item(str(index), _security_group_rule_id(permission, rules) or str(index))
            for group in groups
            for index, permission in enumerate(group.get("IpPermissions", []))
        ]
    if (parent_kind, kind) == ("route-table", "route"):
        tables = [x for p in _pages(session, "ec2", "describe_route_tables", RouteTableIds=[pid]) for x in p.get("RouteTables", [])]
        return [
            _item(
                str(index),
                route.get("DestinationCidrBlock", route.get("DestinationIpv6CidrBlock", route.get("DestinationPrefixListId", str(index)))),
            )
            for table in tables
            for index, route in enumerate(
                route
                for route in table.get("Routes", [])
                if route.get("Origin") != "EnableVgwRoutePropagation"
                and route.get("GatewayId") != "local"
            )
        ]
    if (parent_kind, kind) == ("network-acl", "network-acl-rule"):
        acls = [x for p in _pages(session, "ec2", "describe_network_acls", NetworkAclIds=[pid]) for x in p.get("NetworkAcls", [])]
        return [
            _item(str(index), f"{entry['RuleNumber']}:{entry['Egress']}")
            for acl in acls
            for index, entry in enumerate(
                entry for entry in acl.get("Entries", []) if entry["RuleNumber"] != 32767
            )
        ]
    if (parent_kind, kind) == ("sns", "sns_subscription"):
        return [_item(x["SubscriptionArn"], x["SubscriptionArn"]) for p in _pages(session, "sns", "list_subscriptions_by_topic", TopicArn=pid) for x in p.get("Subscriptions", [])]
    if parent_kind in {"elasticache", "elasticache-replication-group"} and kind == "security-group":
        # Tag discovery identifies replication groups by ARN, but ElastiCache
        # control-plane APIs require the short replication-group ID.
        group = session.client("elasticache").describe_replication_groups(
            ReplicationGroupId=parent["name"]
        )["ReplicationGroups"][0]
        return [_item(x["SecurityGroupId"], x["SecurityGroupId"]) for x in group.get("SecurityGroups", [])]
    if parent_kind == "eks":
        raise ValueError(f"EKS child {kind!r} requires Kubernetes context and is not AWS API tag-resolvable")
    raise ValueError(f"unsupported AWS graph edge {parent_kind!r} -> {kind!r}")


def _pages(session, client, operation, **kwargs):
    return session.client(client).get_paginator(operation).paginate(**kwargs)


def _intersect(candidates, tagged):
    tagged_ids = {_normal(x["id"]) for x in tagged}
    return [x for x in candidates if _normal(x["id"]) in tagged_ids or any(_normal(x["id"]) in value for value in tagged_ids)]


def _match(resources, expected):
    expected = _normal(expected)
    return [x for x in resources if expected in {_normal(x["id"]), _normal(x["name"])}]


def _security_group_rule_id(permission, rules):
    for rule in rules:
        if (
            rule.get("IpProtocol") != permission.get("IpProtocol")
            or rule.get("FromPort") != permission.get("FromPort")
            or rule.get("ToPort") != permission.get("ToPort")
        ):
            continue
        if rule.get("CidrIpv4") in {item.get("CidrIp") for item in permission.get("IpRanges", [])}:
            return rule.get("SecurityGroupRuleId", "")
        if rule.get("CidrIpv6") in {item.get("CidrIpv6") for item in permission.get("Ipv6Ranges", [])}:
            return rule.get("SecurityGroupRuleId", "")
        if rule.get("PrefixListId") in {item.get("PrefixListId") for item in permission.get("PrefixListIds", [])}:
            return rule.get("SecurityGroupRuleId", "")
        if rule.get("ReferencedGroupInfo", {}).get("GroupId") in {
            item.get("GroupId") for item in permission.get("UserIdGroupPairs", [])
        }:
            return rule.get("SecurityGroupRuleId", "")
    return ""


def _normal(value):
    return str(value).rstrip("/").casefold()


def _item(identifier, name):
    return {"id": str(identifier), "name": str(name), "arn": str(identifier)}


def _resource(arn):
    return _item(arn, arn.rsplit(":", 1)[-1].split("/", 1)[-1])
