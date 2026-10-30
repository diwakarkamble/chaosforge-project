import json
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from locust import LoadTestShape, User, between, events, tag, task

# ============================================================================
# CUSTOM CLI PARAMETERS
# ============================================================================


@events.init_command_line_parser.add_listener
def _(parser):
    parser.add_argument("--aws-region", type=str, required=True)
    parser.add_argument("--lambda-name", type=str, required=True)
    parser.add_argument("--topic", type=str, required=True)
    parser.add_argument("--data", type=str, required=True)
    parser.add_argument("--broker-timestamp", type=int, required=True)
    parser.add_argument("--spike-size", type=int, default=1)
    parser.add_argument("--payload-size", type=int, default=1)
    parser.add_argument("--retry-count", type=int, default=1)


# ============================================================================
# CUSTOM LOAD SHAPE (Invocation Storm Injection)
# ============================================================================


class StormInjectionShape(LoadTestShape):
    """
    Doubles the user count and spawn rate every 2 minutes.
    Forces the test to stop at 10 minutes (600 seconds).
    """

    def tick(self):
        run_time = self.get_run_time()

        # Hard cap the test at 10 minutes (600 seconds)
        if run_time > 600:
            return None

        # Fetch base options parsed from CLI
        options = self.runner.environment.parsed_options
        base_users = options.users if options.users else 1
        base_spawn_rate = options.spawn_rate if options.spawn_rate else 1

        # Calculate step index (every 120 seconds)
        # 0-119s: step 0 (1x) | 120-239s: step 1 (2x) | 240-359s: step 2 (4x)...
        step = int(run_time // 120)
        multiplier = 2**step

        current_users = base_users * multiplier
        current_spawn_rate = base_spawn_rate * multiplier

        return (current_users, current_spawn_rate)


# ============================================================================
# LAMBDA CLIENT
# ============================================================================


class LambdaClient:
    def __init__(self, request_event, region):
        self._request_event = request_event
        config = Config(max_pool_connections=200, retries={"max_attempts": 3})
        self.client = boto3.client("lambda", region_name=region, config=config)

    def invoke_lambda(self, function_name, payload):
        start_time = time.perf_counter()
        request_meta = {
            "request_type": "lambda",
            "name": function_name,
            "response_length": 0,
            "exception": None,
            "context": {},
        }

        try:
            response = self.client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload).encode("utf-8"),
            )
            if "Payload" in response:
                request_meta["response_length"] = len(response["Payload"].read())
        except (ClientError, OSError) as e:
            request_meta["exception"] = e

        request_meta["response_time"] = (time.perf_counter() - start_time) * 1000
        self._request_event.fire(**request_meta)


# ============================================================================
# LOCUST USER
# ============================================================================


class AWSLambdaUser(User):
    wait_time = between(0, 0)

    def __init__(self, environment):
        super().__init__(environment)
        options = environment.parsed_options
        self.client = LambdaClient(
            request_event=environment.events.request, region=options.aws_region
        )

    def build_payload(self):
        options = self.environment.parsed_options
        return {
            "topic": options.topic,
            "data": options.data,
            "brokerTimestamp": options.broker_timestamp,
            "userProperties": [],
        }

    @tag("normal")
    @task
    def normal_test(self):
        options = self.environment.parsed_options
        payload = self.build_payload()
        self.client.invoke_lambda(options.lambda_name, payload)

    @tag("payload")
    @task
    def payload_test(self):
        options = self.environment.parsed_options
        payload = self.build_payload()
        payload["data"] = payload["data"] * options.payload_size
        self.client.invoke_lambda(options.lambda_name, payload)

    @tag("retry")
    @task
    def retry_test(self):
        options = self.environment.parsed_options
        payload = self.build_payload()
        for _ in range(options.retry_count):
            self.client.invoke_lambda(options.lambda_name, payload)

    @tag("spike")
    @task
    def spike_test(self):
        options = self.environment.parsed_options
        payload = self.build_payload()
        payload["data"] = payload["data"] * options.spike_size
        self.client.invoke_lambda(options.lambda_name, payload)
