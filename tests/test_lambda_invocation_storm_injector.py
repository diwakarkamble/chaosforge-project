import argparse
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError

MODULE_NAME = (
    "chaosforge.providers.aws.components.lambda.experiments.custom."
    "lambda_invocation_storm_injector"
)


def _load_module_without_locust():
    locust = ModuleType("locust")

    class EventHook:
        def __init__(self):
            self.listeners = []

        def add_listener(self, listener):
            self.listeners.append(listener)
            return listener

    class LoadTestShape:
        pass

    class User:
        def __init__(self, environment):
            self.environment = environment

    def identity_decorator(*decorator_args):
        if len(decorator_args) == 1 and callable(decorator_args[0]):
            return decorator_args[0]
        return lambda function: function

    locust.LoadTestShape = LoadTestShape
    locust.User = User
    locust.between = lambda minimum, maximum: lambda: (minimum, maximum)
    locust.events = SimpleNamespace(init_command_line_parser=EventHook())
    locust.tag = identity_decorator
    locust.task = identity_decorator

    sys.modules.pop(MODULE_NAME, None)
    with patch.dict(sys.modules, {"locust": locust}):
        module = importlib.import_module(MODULE_NAME)
    return module, locust


@pytest.fixture(scope="module")
def injector():
    module, _ = _load_module_without_locust()
    return module


def test_registers_all_custom_command_line_arguments():
    _, locust = _load_module_without_locust()
    parser = argparse.ArgumentParser()

    assert len(locust.events.init_command_line_parser.listeners) == 1
    locust.events.init_command_line_parser.listeners[0](parser)
    options = parser.parse_args(
        [
            "--aws-region",
            "eu-central-1",
            "--lambda-name",
            "orders",
            "--topic",
            "orders/created",
            "--data",
            "payload",
            "--broker-timestamp",
            "123456",
        ]
    )

    assert vars(options) == {
        "aws_region": "eu-central-1",
        "lambda_name": "orders",
        "topic": "orders/created",
        "data": "payload",
        "broker_timestamp": 123456,
        "spike_size": 1,
        "payload_size": 1,
        "retry_count": 1,
    }


def test_custom_command_line_arguments_accept_overrides():
    _, locust = _load_module_without_locust()
    parser = argparse.ArgumentParser()
    locust.events.init_command_line_parser.listeners[0](parser)

    options = parser.parse_args(
        [
            "--aws-region",
            "us-east-1",
            "--lambda-name",
            "fn",
            "--topic",
            "topic",
            "--data",
            "x",
            "--broker-timestamp",
            "7",
            "--spike-size",
            "8",
            "--payload-size",
            "9",
            "--retry-count",
            "3",
        ]
    )

    assert (options.spike_size, options.payload_size, options.retry_count) == (8, 9, 3)


@pytest.mark.parametrize(
    ("run_time", "expected"),
    [
        (0, (3, 4)),
        (119.999, (3, 4)),
        (120, (6, 8)),
        (240, (12, 16)),
        (600, (96, 128)),
        (600.001, None),
    ],
)
def test_storm_shape_scales_every_two_minutes_and_stops(injector, run_time, expected):
    shape = injector.StormInjectionShape()
    shape.get_run_time = MagicMock(return_value=run_time)
    shape.runner = SimpleNamespace(
        environment=SimpleNamespace(
            parsed_options=SimpleNamespace(users=3, spawn_rate=4)
        )
    )

    assert shape.tick() == expected


def test_storm_shape_defaults_falsy_base_values(injector):
    shape = injector.StormInjectionShape()
    shape.get_run_time = MagicMock(return_value=120)
    shape.runner = SimpleNamespace(
        environment=SimpleNamespace(
            parsed_options=SimpleNamespace(users=0, spawn_rate=None)
        )
    )

    assert shape.tick() == (2, 2)


def test_lambda_client_configures_high_capacity_boto_client(injector):
    request_event = MagicMock()
    config = object()
    boto_client = MagicMock()

    with (
        patch.object(injector, "Config", return_value=config) as config_factory,
        patch.object(injector.boto3, "client", return_value=boto_client) as client_factory,
    ):
        client = injector.LambdaClient(request_event, "eu-west-1")

    config_factory.assert_called_once_with(
        max_pool_connections=200, retries={"max_attempts": 3}
    )
    client_factory.assert_called_once_with(
        "lambda", region_name="eu-west-1", config=config
    )
    assert client.client is boto_client
    assert client._request_event is request_event


def _lambda_client(injector):
    client = injector.LambdaClient.__new__(injector.LambdaClient)
    client.client = MagicMock()
    client._request_event = MagicMock()
    return client


def test_invoke_lambda_reports_success_and_response_size(injector):
    client = _lambda_client(injector)
    response_payload = MagicMock()
    response_payload.read.return_value = b"lambda response"
    client.client.invoke.return_value = {"Payload": response_payload}

    with patch.object(injector.time, "perf_counter", side_effect=[10.0, 10.125]):
        client.invoke_lambda("orders", {"message": "hello"})

    client.client.invoke.assert_called_once_with(
        FunctionName="orders",
        InvocationType="RequestResponse",
        Payload=b'{"message": "hello"}',
    )
    response_payload.read.assert_called_once_with()
    client._request_event.fire.assert_called_once_with(
        request_type="lambda",
        name="orders",
        response_length=15,
        exception=None,
        context={},
        response_time=125.0,
    )


def test_invoke_lambda_handles_response_without_payload(injector):
    client = _lambda_client(injector)
    client.client.invoke.return_value = {"StatusCode": 202}

    with patch.object(injector.time, "perf_counter", side_effect=[1.0, 1.01]):
        client.invoke_lambda("orders", {})

    assert client._request_event.fire.call_args.kwargs["response_length"] == 0
    assert client._request_event.fire.call_args.kwargs["exception"] is None


@pytest.mark.parametrize(
    "error",
    [
        ClientError(
            {"Error": {"Code": "TooManyRequestsException", "Message": "throttled"}},
            "Invoke",
        ),
        OSError("connection reset"),
    ],
)
def test_invoke_lambda_reports_handled_failures(injector, error):
    client = _lambda_client(injector)
    client.client.invoke.side_effect = error

    with patch.object(injector.time, "perf_counter", side_effect=[5.0, 5.2]):
        client.invoke_lambda("orders", {"id": 1})

    client._request_event.fire.assert_called_once_with(
        request_type="lambda",
        name="orders",
        response_length=0,
        exception=error,
        context={},
        response_time=pytest.approx(200.0),
    )


def test_invoke_lambda_does_not_hide_unexpected_errors(injector):
    client = _lambda_client(injector)
    client.client.invoke.side_effect = RuntimeError("programming error")

    with (
        patch.object(injector.time, "perf_counter", return_value=1.0),
        pytest.raises(RuntimeError, match="programming error"),
    ):
        client.invoke_lambda("orders", {})

    client._request_event.fire.assert_not_called()


def _environment(**overrides):
    values = {
        "aws_region": "eu-central-1",
        "lambda_name": "orders",
        "topic": "orders/created",
        "data": "ab",
        "broker_timestamp": 123456,
        "payload_size": 3,
        "retry_count": 2,
        "spike_size": 4,
    }
    values.update(overrides)
    return SimpleNamespace(
        parsed_options=SimpleNamespace(**values),
        events=SimpleNamespace(request=MagicMock()),
    )


def _user(injector, environment):
    user = injector.AWSLambdaUser.__new__(injector.AWSLambdaUser)
    user.environment = environment
    user.client = MagicMock()
    return user


def test_user_initializes_client_and_builds_payload(injector):
    environment = _environment()
    lambda_client = MagicMock()

    with patch.object(injector, "LambdaClient", return_value=lambda_client) as factory:
        user = injector.AWSLambdaUser(environment)

    factory.assert_called_once_with(
        request_event=environment.events.request, region="eu-central-1"
    )
    assert user.client is lambda_client
    assert user.build_payload() == {
        "topic": "orders/created",
        "data": "ab",
        "brokerTimestamp": 123456,
        "userProperties": [],
    }


def test_normal_task_invokes_lambda_once_with_base_payload(injector):
    user = _user(injector, _environment())

    user.normal_test()

    user.client.invoke_lambda.assert_called_once_with(
        "orders",
        {
            "topic": "orders/created",
            "data": "ab",
            "brokerTimestamp": 123456,
            "userProperties": [],
        },
    )


def test_payload_task_repeats_data_by_payload_size(injector):
    user = _user(injector, _environment(payload_size=3))

    user.payload_test()

    assert user.client.invoke_lambda.call_args.args[1]["data"] == "ababab"


@pytest.mark.parametrize("retry_count", [0, 3])
def test_retry_task_invokes_lambda_requested_number_of_times(injector, retry_count):
    user = _user(injector, _environment(retry_count=retry_count))
    expected_payload = user.build_payload()

    user.retry_test()

    assert user.client.invoke_lambda.call_args_list == [
        call("orders", expected_payload) for _ in range(retry_count)
    ]


def test_spike_task_repeats_data_by_spike_size(injector):
    user = _user(injector, _environment(spike_size=4))

    user.spike_test()

    assert user.client.invoke_lambda.call_args.args == (
        "orders",
        {
            "topic": "orders/created",
            "data": "abababab",
            "brokerTimestamp": 123456,
            "userProperties": [],
        },
    )
