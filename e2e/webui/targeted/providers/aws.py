"""AWS target resolver using boto3 for name/ID and Resource Groups Tagging API for tags.

Supported service keys: s3, lambda, dynamodb, elasticache, rds, sns, elb,
and kinesis. Credentials are taken from the normal boto3 credential chain or
from the optional per-target `profile` field.
"""
from __future__ import annotations

from typing import Any

import pytest

RESOURCE_TYPE_FILTERS = {
    "s3": ["s3"],
    "lambda": ["lambda:function"],
    "dynamodb": ["dynamodb:table"],
    "elasticache": ["elasticache:cluster", "elasticache:replicationgroup"],
    "rds": ["rds:db", "rds:cluster"],
    "sns": ["sns:topic"],
    "elb": ["elasticloadbalancing:loadbalancer"],
    "kinesis": ["kinesis:stream"],
}


def _session(target: dict[str, Any]):
    import boto3
    return boto3.Session(
        profile_name=target.get("profile") or None,
        region_name=target["region"],
    )


def _direct_resources(target: dict[str, Any]) -> list[dict[str, str]]:
    """List resources directly so name/ID targeting also works for untagged resources."""
    session = _session(target)
    service = target["service"].lower()
    result: list[dict[str, str]] = []

    if service == "s3":
        s3 = session.client("s3")
        for item in s3.list_buckets().get("Buckets", []):
            name = item["Name"]
            try:
                location = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
                location = location or "us-east-1"
            except Exception:
                continue
            if location == target["region"]:
                result.append({"id": f"arn:aws:s3:::{name}", "name": name})
    elif service == "lambda":
        client = session.client("lambda")
        for page in client.get_paginator("list_functions").paginate():
            result.extend({"id": f["FunctionArn"], "name": f["FunctionName"]}
                          for f in page.get("Functions", []))
    elif service == "dynamodb":
        client = session.client("dynamodb")
        names = []
        for page in client.get_paginator("list_tables").paginate():
            names.extend(page.get("TableNames", []))
        for name in names:
            table = client.describe_table(TableName=name)["Table"]
            result.append({"id": table["TableArn"], "name": name})
    elif service == "elasticache":
        client = session.client("elasticache")
        for page in client.get_paginator("describe_cache_clusters").paginate(ShowCacheClusters=True):
            for item in page.get("CacheClusters", []):
                result.append({"id": item.get("ARN", item["CacheClusterId"]), "name": item["CacheClusterId"]})
        for page in client.get_paginator("describe_replication_groups").paginate():
            for item in page.get("ReplicationGroups", []):
                result.append({"id": item.get("ARN", item["ReplicationGroupId"]), "name": item["ReplicationGroupId"]})
    elif service == "rds":
        client = session.client("rds")
        for page in client.get_paginator("describe_db_instances").paginate():
            for item in page.get("DBInstances", []):
                result.append({"id": item["DBInstanceArn"], "name": item["DBInstanceIdentifier"]})
        for page in client.get_paginator("describe_db_clusters").paginate():
            for item in page.get("DBClusters", []):
                result.append({"id": item["DBClusterArn"], "name": item["DBClusterIdentifier"]})
    elif service == "sns":
        client = session.client("sns")
        for page in client.get_paginator("list_topics").paginate():
            for item in page.get("Topics", []):
                arn = item["TopicArn"]
                result.append({"id": arn, "name": arn.rsplit(":", 1)[-1]})
    elif service == "elb":
        client = session.client("elbv2")
        for page in client.get_paginator("describe_load_balancers").paginate():
            for item in page.get("LoadBalancers", []):
                result.append({"id": item["LoadBalancerArn"], "name": item["LoadBalancerName"]})
    elif service == "kinesis":
        client = session.client("kinesis")
        for page in client.get_paginator("list_streams").paginate():
            for name in page.get("StreamNames", []):
                item = client.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
                result.append({"id": item["StreamARN"], "name": name})
    else:
        pytest.fail(f"AWS static targeting does not support service key {service!r} yet.")
    return result


def _tagged_resources(target: dict[str, Any]) -> list[dict[str, str]]:
    session = _session(target)
    client = session.client("resourcegroupstaggingapi")
    kwargs: dict[str, Any] = {"ResourceTypeFilters": RESOURCE_TYPE_FILTERS[target["service"].lower()]}
    kwargs["TagFilters"] = [
        {"Key": str(key), "Values": [str(value)]}
        for key, value in target["target"].items()
    ]
    found = []
    for page in client.get_paginator("get_resources").paginate(**kwargs):
        for item in page.get("ResourceTagMappingList", []):
            arn = str(item.get("ResourceARN", ""))
            found.append({"id": arn, "name": _name_from_arn(arn)})
    return found


def _name_from_arn(arn: str) -> str:
    if arn.startswith("arn:aws:s3:::"):
        return arn.rsplit(":::", 1)[-1]
    tail = arn.rsplit(":", 1)[-1]
    return tail.split("/", 1)[-1]


def resolve_aws_targets(target: dict[str, Any]) -> list[dict[str, str]]:
    service = target["service"].lower()
    if service not in RESOURCE_TYPE_FILTERS:
        pytest.fail(f"AWS static targeting does not support service key {service!r} yet.")
    try:
        if target["target_type"] == "tags":
            matches = _tagged_resources(target)
        else:
            expected = str(target["target"]).strip().rstrip("/").casefold()
            matches = []
            for resource in _direct_resources(target):
                if expected in {
                    resource["id"].strip().rstrip("/").casefold(),
                    resource["name"].strip().rstrip("/").casefold(),
                }:
                    matches.append(resource)
    except pytest.fail.Exception:
        raise
    except Exception as exc:
        pytest.fail(
            f"AWS resource lookup failed for service={service!r}, "
            f"region={target['region']!r}. Check AWS credentials and read permissions. Details: {exc}"
        )

    # Remove duplicates without hiding multiple distinct resource matches.
    unique = {(item["id"].casefold(), item["name"].casefold()): item for item in matches}
    return list(unique.values())
