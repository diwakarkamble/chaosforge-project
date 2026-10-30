import json
import os
import tempfile

from chaosforge.interfaces.cli.session import context

from .apigateway_common import (
    get_client,
    get_stage,
)

STATE_FILE = os.path.join(
    tempfile.gettempdir(),
    "apigateway_access_logging_state.json",
)


def is_http_api():
    return getattr(context, "apigateway_protocol", "REST").upper() == "HTTP"


def capture_and_disable_access_logging(
    rest_api_id,
    stage_name,
    region,
):

    client = get_client(region)

    stage = get_stage(
        rest_api_id,
        stage_name,
        region,
    )

    settings = stage.get("AccessLogSettings") or stage.get("accessLogSettings") or {}

    destination = settings.get("DestinationArn") or settings.get("destinationArn")

    log_format = settings.get("Format") or settings.get("format")

    print(f"Current Destination : {destination}")
    print(f"Current Format      : {log_format}")

    with open(STATE_FILE, "w") as fp:
        json.dump(
            {
                "rest_api_id": rest_api_id,
                "stage_name": stage_name,
                "region": region,
                "destinationArn": destination,
                "format": log_format,
            },
            fp,
            indent=2,
        )

    if not destination and not log_format:
        print("Access Logging already disabled.")
        return

    print("Disabling Access Logging...")

    if is_http_api():
        client.update_stage(
            ApiId=rest_api_id,
            StageName=stage_name,
            AccessLogSettings={},
        )

    else:
        client.update_stage(
            restApiId=rest_api_id,
            stageName=stage_name,
            patchOperations=[
                {
                    "op": "remove",
                    "path": "/accessLogSettings/destinationArn",
                },
                {
                    "op": "remove",
                    "path": "/accessLogSettings/format",
                },
            ],
        )

    print("Access Logging disabled.")


def restore_access_logging():

    if not os.path.exists(STATE_FILE):
        raise FileNotFoundError("State file not found.")

    with open(STATE_FILE) as fp:
        state = json.load(fp)

    client = get_client(state["region"])

    if state["destinationArn"]:
        if is_http_api():
            client.update_stage(
                ApiId=state["rest_api_id"],
                StageName=state["stage_name"],
                AccessLogSettings={
                    "DestinationArn": state["destinationArn"],
                    "Format": state["format"],
                },
            )

        else:
            client.update_stage(
                restApiId=state["rest_api_id"],
                stageName=state["stage_name"],
                patchOperations=[
                    {
                        "op": "replace",
                        "path": "/accessLogSettings/destinationArn",
                        "value": state["destinationArn"],
                    },
                    {
                        "op": "replace",
                        "path": "/accessLogSettings/format",
                        "value": state["format"],
                    },
                ],
            )

    os.remove(STATE_FILE)

    print("Access Logging restored.")
