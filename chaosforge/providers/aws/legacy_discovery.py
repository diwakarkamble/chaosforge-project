import boto3


def discover_lambda(region, profile=None):

    if profile:
        session = boto3.Session(profile_name=profile, region_name=region)

    else:
        session = boto3.Session(region_name=region)

    client = session.client("lambda")

    functions = []

    paginator = client.get_paginator("list_functions")

    for page in paginator.paginate():
        for function in page["Functions"]:
            functions.append(
                {
                    "name": function["FunctionName"],
                    "memory": function["MemorySize"],
                    "timeout": function["Timeout"],
                }
            )

    return sorted(functions, key=lambda x: x["name"])
