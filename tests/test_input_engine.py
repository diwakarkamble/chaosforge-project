from unittest.mock import patch

import pytest

from chaosforge.interfaces.cli.interactive.input_engine import collect_inputs, get_input
from chaosforge.interfaces.cli.interactive.navigation import BackToMainMenu
from chaosforge.interfaces.cli.session import context


@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt")
def test_get_input_returns_value(mock_prompt):

    mock_prompt.return_value = "  hello  "

    result = get_input("Enter Value")

    assert result == "hello"


@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt")
def test_get_input_back_to_main_menu(mock_prompt):

    mock_prompt.return_value = "m"

    with pytest.raises(BackToMainMenu):
        get_input("Enter Value")


def test_collect_inputs_without_fields():

    context.region = "eu-central-1"

    metadata = {"name": "Dummy", "inputs": []}

    result = collect_inputs(metadata)

    assert result["aws_region"] == "eu-central-1"


@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate")
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_uses_default_value(mock_title, mock_prompt, mock_validate):

    context.region = "eu-central-1"

    mock_prompt.return_value = ""

    mock_validate.return_value = (True, "")

    metadata = {
        "name": "Dummy",
        "inputs": [{"name": "username", "label": "User Name", "default": "admin"}],
    }

    result = collect_inputs(metadata)

    assert result["username"] == "admin"


@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate", return_value=(True, ""))
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt", return_value="")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
@patch("chaosforge.interfaces.cli.interactive.input_engine.console.print")
def test_collect_inputs_displays_default_on_a_separate_aligned_line(
    mock_print, mock_title, mock_prompt, mock_validate
):
    context.region = "eu-central-1"

    collect_inputs(
        {
            "name": "Memory Modification",
            "inputs": [{"name": "memory", "label": "Memory (MB)", "default": 512}],
        }
    )

    mock_print.assert_any_call("[bold cyan]Memory (MB)[/bold cyan]")
    mock_print.assert_any_call("[bright_black]Default : 512[/bright_black]")


@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt", return_value="0")
@patch("chaosforge.interfaces.cli.interactive.input_engine.menu")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_chaos_mode_supports_back(mock_title, mock_menu, mock_prompt):
    context.region = "eu-central-1"

    result = collect_inputs({
        "id": "chaos-mesh-pod-kill",
        "name": "Pod Kill",
        "inputs": [{"name": "mode", "type": "chaos_mode"}],
    })

    assert result is None
    assert (0, "Back") in mock_menu.call_args.args[1]


@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate", return_value=(True, ""))
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt", return_value="")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_normalizes_legacy_local_duration_default(
    mock_title, mock_prompt, mock_validate
):
    context.region = "eu-central-1"
    metadata = {
        "name": "Duration",
        "inputs": [
            {
                "name": "wait_seconds",
                "label": "Wait",
                "type": "integer",
                "default": 300,
            }
        ],
    }

    assert collect_inputs(metadata)["wait_seconds"] == "PT300S"


@pytest.mark.parametrize(
    ("field", "expected_hint"),
    [
        ({"hint": "Custom guidance"}, "[bright_black]Custom guidance[/bright_black]"),
        (
            {"type": "iso8601_duration"},
            "[bright_black]Enter an ISO 8601 duration: PT5M means 5 minutes, PT100S means 100 seconds, and PT1H means 1 hour.[/bright_black]",
        ),
    ],
)
@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate", return_value=(True, ""))
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt", return_value="PT1M")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
@patch("chaosforge.interfaces.cli.interactive.input_engine.console.print")
def test_collect_inputs_displays_generic_field_hint(
    mock_print, mock_title, mock_prompt, mock_validate, field, expected_hint
):
    context.region = "eu-central-1"
    metadata = {"name": "Dummy", "inputs": [{"name": "value", "label": "Value", **field}]}

    assert collect_inputs(metadata)["value"] == "PT1M"
    mock_print.assert_any_call(expected_hint)


@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate", return_value=(True, ""))
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt", return_value="")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
@patch("chaosforge.interfaces.cli.interactive.input_engine.console.print")
def test_collect_inputs_does_not_duplicate_numeric_help(
    mock_print, mock_title, mock_prompt, mock_validate
):
    context.region = "eu-central-1"

    collect_inputs(
        {
            "name": "Memory Modification",
            "inputs": [{"name": "memory", "label": "Memory (MB)", "type": "integer", "default": 512}],
        }
    )

    rendered = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
    assert rendered.count("[bright_black]Enter a numeric value.[/bright_black]") == 0
    assert rendered.count("[bright_black]Enter a numeric value for memory.[/bright_black]") == 1


@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate", return_value=(True, ""))
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt", return_value="false")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_prompts_boolean_values_explicitly(
    mock_title, mock_prompt, mock_validate
):
    context.region = "eu-central-1"
    metadata = {
        "name": "Auto Minor Version Upgrade",
        "inputs": [
            {
                "name": "target_auto_minor_version_upgrade",
                "label": "Target Auto Minor Version Upgrade",
                "type": "boolean",
                "hint": "Enter the opposite of the current setting.",
            }
        ],
    }

    assert collect_inputs(metadata)["target_auto_minor_version_upgrade"] is False
    mock_prompt.assert_called_once_with("Enter true or false")


@patch("chaosforge.interfaces.cli.interactive.input_engine.error")
@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate")
@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_invalid_then_valid(
    mock_title, mock_prompt, mock_validate, mock_error
):

    context.region = "eu-central-1"

    mock_prompt.side_effect = ["abc", "admin"]

    mock_validate.side_effect = [(False, "Invalid value"), (True, "")]

    metadata = {
        "name": "Dummy",
        "inputs": [{"name": "username", "label": "User Name", "required": True}],
    }

    result = collect_inputs(metadata)

    assert result["username"] == "admin"

    mock_error.assert_called_once_with("Invalid value")


@patch("chaosforge.interfaces.cli.interactive.input_engine.error")
@patch("chaosforge.interfaces.cli.interactive.input_engine.menu")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_invalid_experiment_selection_value_error(
    mock_title,
    mock_catalog,
    mock_get_input,
    mock_menu,
    mock_error,
):
    context.region = "eu-central-1"

    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "exp1",
            "name": "Experiment 1",
            "parameters": [],
        }
    ]

    # First invalid (ValueError), then valid
    mock_get_input.side_effect = [
        "abc",
        "1",
    ]

    metadata = {
        "name": "Demo",
        "inputs": [
            {
                "name": "experiment_id",
                "label": "Experiment",
            }
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "lambda"},
    )

    assert result["experiment_id"] == "exp1"
    assert mock_get_input.call_count == 2
    mock_error.assert_called_once_with("Invalid Selection")


@patch("chaosforge.interfaces.cli.interactive.input_engine.error")
@patch("chaosforge.interfaces.cli.interactive.input_engine.menu")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_invalid_selection_valueerror_and_indexerror(
    mock_title,
    mock_catalog,
    mock_get_input,
    mock_menu,
    mock_error,
):
    context.region = "eu-central-1"

    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "exp1",
            "name": "Experiment 1",
            "parameters": [],
        }
    ]

    # ValueError -> IndexError -> Success
    mock_get_input.side_effect = [
        "abc",
        "99",
        "1",
    ]

    metadata = {
        "name": "Demo",
        "inputs": [
            {
                "name": "experiment_id",
                "label": "Experiment",
            }
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "lambda"},
    )

    assert result["experiment_id"] == "exp1"
    assert mock_error.call_count == 2


@patch("chaosforge.interfaces.cli.interactive.input_engine.prompt")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
def test_collect_inputs_prefilled_variables(mock_selector, mock_catalog, mock_prompt):

    context.region = "eu-central-1"

    mock_catalog.return_value.get_experiment.return_value = {
        "parameters": [{"name": "duration", "label": "Duration", "default": "PT5M"}]
    }

    mock_prompt.return_value = ""

    metadata = {
        "name": "Dummy",
        "inputs": [
            {"name": "service_id", "label": "Service"},
            {"name": "experiment_id", "label": "Experiment"},
        ],
    }

    result = collect_inputs(
        metadata, prefill={"service_id": "lambda", "experiment_id": "lambda-timeout"}
    )

    assert result["service_id"] == "lambda"

    assert result["experiment_id"] == "lambda-timeout"

    assert result["duration"] == "PT5M"


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_aws_resource(mock_title, mock_selector):

    context.region = "eu-central-1"

    selector = mock_selector.return_value

    selector.select.return_value = {
        "name": "lambda-test",
        "arn": "arn:aws:lambda:test",
        "id": "lambda-id",
    }

    metadata = {
        "name": "AWS Resource Test",
        "inputs": [
            {
                "name": "lambda_name",
                "label": "Lambda Function",
                "type": "aws_resource",
                "resource_type": "lambda",
                "return": "name",
            }
        ],
    }

    result = collect_inputs(metadata)

    assert result["lambda_name"] == "lambda-test"

    selector.select.assert_called_once_with("lambda")


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_fis_aws_resource_parameter(
    mock_title,
    mock_get_input,
    mock_catalog,
    mock_selector,
):

    context.region = "eu-central-1"

    mock_get_input.return_value = "1"

    selector = mock_selector.return_value

    selector.select.return_value = {
        "name": "eu-central-1a",
        "zone_name": "eu-central-1a",
        "zone_id": "euc1-az1",
    }

    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "zonal-autoshift",
            "name": "Zonal Autoshift",
            "parameters": [
                {
                    "name": "availability_zone",
                    "label": "Availability Zone",
                    "type": "aws_resource",
                    "resource_type": "availability-zone",
                    "return": "zone_name",
                    "aws_name": "availabilityZoneIdentifier",
                }
            ],
        }
    ]

    metadata = {
        "name": "AWS FIS",
        "inputs": [
            {
                "name": "service_id",
                "label": "AWS Service",
            },
            {
                "name": "experiment_id",
                "label": "Experiment",
            },
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={
            "service_id": "elb",
        },
    )

    assert result["experiment_id"] == "zonal-autoshift"

    assert result["availability_zone"] == ("eu-central-1a")

    selector.select.assert_called_once_with("availability-zone")


# ----------------------------------------------------------
# Target ARN
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_target_arn(
    mock_title,
    mock_selector,
):

    context.region = "eu-central-1"

    selector = mock_selector.return_value

    selector.select.return_value = {
        "arn": ("arn:aws:lambda:eu-central-1:111111111111:function:test")
    }

    metadata = {
        "name": "Target ARN Test",
        "inputs": [
            {
                "name": "target_arn",
                "label": "Target ARN",
            }
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "lambda"},
    )

    assert result["target_arn"] == (
        "arn:aws:lambda:eu-central-1:111111111111:function:test"
    )

    selector.select.assert_called_once_with("lambda")


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_parent_child_resource(mock_title, mock_selector):

    context.region = "eu-central-1"

    selector = mock_selector.return_value

    #
    # Parent resource
    #

    selector.select.return_value = {"id": "sg-123"}

    #
    # Child resource
    #

    selector.select_child.return_value = {"name": "Rule-1"}

    metadata = {
        "name": "Parent Child",
        "inputs": [
            {
                "name": "security_group",
                "label": "Security Group",
                "type": "aws_resource",
                "resource_type": "security-group",
                "return": "id",
            },
            {
                "name": "rule",
                "label": "Rule",
                "type": "aws_resource",
                "resource_type": "security-group-rule",
                "parent": "security_group",
            },
        ],
    }

    result = collect_inputs(metadata)

    assert result["security_group"] == "sg-123"

    assert result["rule"] == "Rule-1"

    selector.select_child.assert_called_once()


@patch("chaosforge.interfaces.cli.interactive.input_engine.console.print")
@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_describes_dependent_resources_without_internal_keys(
    _mock_title, mock_selector, mock_console_print
):
    context.region = "eu-central-1"
    selector = mock_selector.return_value
    selector.select.return_value = {"id": "sg-123"}
    selector.select_child.return_value = {"id": 0, "name": "HTTPS Rule"}
    metadata = {
        "name": "Security Group Rule Modification",
        "inputs": [
            {
                "name": "security_group_id",
                "label": "Security Group",
                "type": "aws_resource",
                "resource_type": "security-group",
                "return": "id",
            },
            {
                "name": "selected_rule",
                "label": "Security Group Rule",
                "type": "aws_resource",
                "resource_type": "security-group-rule",
                "parent": "security_group_id",
                "return": "id",
            },
        ],
    }

    result = collect_inputs(metadata)

    assert result == {"aws_region": "eu-central-1", "security_group_id": "sg-123", "selected_rule": 0}
    rendered = "\n".join(
        str(call.args[0]) for call in mock_console_print.call_args_list if call.args
    )
    assert "Loading Security Group Rule" in rendered
    assert "for Security Group" in rendered
    assert "PARENT FIELD" not in rendered
    assert "CHILD TYPE" not in rendered


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_edit_mode_skip_resource(mock_title, mock_selector):

    context.region = "eu-central-1"

    metadata = {
        "name": "Edit",
        "inputs": [
            {
                "name": "lambda_name",
                "label": "Lambda",
                "type": "aws_resource",
                "resource_type": "lambda",
            }
        ],
    }

    result = collect_inputs(
        metadata, prefill={"lambda_name": "ExistingLambda"}, edit_mode=True
    )

    assert result["lambda_name"] == "ExistingLambda"

    mock_selector.return_value.select.assert_not_called()


@patch("chaosforge.interfaces.cli.interactive.input_engine.error")
@patch("chaosforge.interfaces.cli.interactive.input_engine.menu")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_invalid_experiment_selection(
    mock_title,
    mock_catalog,
    mock_get_input,
    mock_menu,
    mock_error,
):
    context.region = "eu-central-1"

    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "exp1",
            "name": "Experiment 1",
            "parameters": [],
        }
    ]

    mock_get_input.side_effect = [
        "99",
        "1",
    ]

    metadata = {
        "name": "Test",
        "inputs": [
            {
                "name": "experiment_id",
                "label": "Experiment",
            }
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "lambda"},
    )

    assert result["experiment_id"] == "exp1"

    mock_error.assert_called_once_with("Invalid Selection")


@patch("chaosforge.interfaces.cli.interactive.input_engine.menu")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_select_experiment_and_parameters(
    mock_title,
    mock_catalog,
    mock_get_input,
    mock_menu,
):
    context.region = "eu-central-1"

    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "delay",
            "name": "Delay",
            "parameters": [
                {
                    "name": "duration",
                    "label": "Duration",
                    "default": "PT5M",
                }
            ],
        }
    ]

    mock_get_input.side_effect = [
        "1",
        "",
    ]

    metadata = {
        "name": "Demo",
        "inputs": [
            {
                "name": "experiment_id",
                "label": "Experiment",
            }
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "lambda"},
    )

    assert result["experiment_id"] == "delay"

    assert result["duration"] == "PT5M"


@patch("chaosforge.interfaces.cli.interactive.input_engine.error")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_fis_duration_reprompts_until_iso8601_value(
    mock_title,
    mock_catalog,
    mock_get_input,
    mock_error,
):
    context.region = "eu-central-1"
    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "stop-instances",
            "name": "Stop Instances",
            "parameters": [
                {
                    "name": "start_instances_after_duration",
                    "label": "Start Instances After Duration",
                    "default": "PT5M",
                }
            ],
        }
    ]
    mock_get_input.side_effect = ["1", "1M", "PT1M"]
    metadata = {
        "name": "AWS FIS",
        "inputs": [{"name": "experiment_id", "label": "Experiment"}],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "ec2"},
    )

    assert result["start_instances_after_duration"] == "PT1M"
    mock_error.assert_called_once()


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_target_arn_edit_mode(
    mock_title,
    mock_selector,
):
    context.region = "eu-central-1"

    metadata = {
        "name": "Demo",
        "inputs": [
            {
                "name": "target_arn",
                "label": "Target",
            }
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={
            "service_id": "lambda",
            "target_arn": "existing-arn",
        },
        edit_mode=True,
    )

    assert result["target_arn"] == "existing-arn"

    mock_selector.return_value.select.assert_not_called()


@patch("chaosforge.interfaces.cli.interactive.input_engine.Validator.validate")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.console.print")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_generic_field_with_range(
    mock_title,
    mock_print,
    mock_get_input,
    mock_validate,
):
    context.region = "eu-central-1"

    mock_get_input.return_value = "10"

    mock_validate.return_value = (
        True,
        "",
    )

    metadata = {
        "name": "Demo",
        "inputs": [
            {
                "name": "count",
                "label": "Count",
                "min": 1,
                "max": 20,
            }
        ],
    }

    result = collect_inputs(metadata)

    assert result["count"] == "10"

    assert mock_print.call_count > 0


@pytest.mark.parametrize(
    "resource_type,selector_service",
    [
        ("aws:ec2:instance", "ec2"),
        ("aws:ec2:spot-instance", "ec2-spot"),
        ("aws:iam:role", "iam-role"),
        ("aws:ec2:autoscaling-group", "autoscaling-group"),
        ("aws:arc:zonal-shift-managed-resource", "elb"),
    ],
)
@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.get_input")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_fis_ec2_target_resource_mapping(
    mock_title,
    mock_get_input,
    mock_catalog,
    mock_selector,
    resource_type,
    selector_service,
):
    context.region = "eu-central-1"

    selector = mock_selector.return_value

    selector.select.return_value = {
        "name": "test-resource",
        "arn": "arn:aws:test:test-resource",
    }

    mock_catalog.return_value.get_experiments.return_value = [
        {
            "id": "test-experiment",
            "name": "Test Experiment",
            "parameters": [],
            "resource_type": resource_type,
        }
    ]

    mock_catalog.return_value.get_experiment.return_value = {
        "id": "test-experiment",
        "name": "Test Experiment",
        "parameters": [],
        "resource_type": resource_type,
    }

    mock_get_input.side_effect = ["1"]

    metadata = {
        "name": "AWS FIS",
        "inputs": [
            {"name": "service_id", "label": "AWS Service"},
            {"name": "experiment_id", "label": "Experiment"},
            {"name": "target_arn", "label": "Target Resource"},
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={"service_id": "ec2"},
    )

    assert result["target_arn"] == "arn:aws:test:test-resource"
    selector.select.assert_called_once_with(selector_service)


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.FISCatalog")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_fis_ec2_target_falls_back_to_instance_id(
    mock_title,
    mock_catalog,
    mock_selector,
):
    context.region = "eu-central-1"
    mock_catalog.return_value.get_experiment.return_value = {
        "id": "stop-instances",
        "resource_type": "aws:ec2:instance",
    }
    mock_selector.return_value.select.return_value = {
        "name": "test-instance",
        "id": "i-123",
        "arn": "",
    }
    metadata = {
        "name": "AWS FIS",
        "inputs": [
            {"name": "target_arn", "label": "Target Resource"},
        ],
    }

    result = collect_inputs(
        metadata,
        prefill={
            "service_id": "ec2",
            "experiment_id": "stop-instances",
            "target_arn": "",
        },
        edit_mode=True,
    )

    assert result["target_arn"] == "i-123"


# ----------------------------------------------------------
# ELB Parent / Child Resource Selection
# ----------------------------------------------------------


@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_elb_target_chain(
    mock_title,
    mock_selector,
):

    context.region = "test-region"

    selector = mock_selector.return_value

    # ------------------------------------------------------
    # Load Balancer
    # ------------------------------------------------------

    selector.select.side_effect = [
        {
            "name": "test-lb",
            "arn": "lb-arn-123",
        }
    ]

    # ------------------------------------------------------
    # Target Group
    # ------------------------------------------------------

    selector.select_child.side_effect = [
        {
            "name": "test-target-group",
            "arn": "tg-arn-123",
        },
        {
            "name": "target-123 (healthy)",
            "id": "target-123",
        },
    ]

    metadata = {
        "name": "ELB Target Deregistration",
        "inputs": [
            {
                "name": "load_balancer",
                "label": "Load Balancer",
                "required": True,
                "type": "aws_resource",
                "resource_type": "elb",
                "return": "arn",
            },
            {
                "name": "target_group",
                "label": "Target Group",
                "required": True,
                "type": "aws_resource",
                "parent": "load_balancer",
                "resource_type": "elb-target-group",
                "return": "arn",
            },
            {
                "name": "target",
                "label": "Target",
                "required": True,
                "type": "aws_resource",
                "parent": "target_group",
                "resource_type": "elb-target",
                "return": "id",
            },
        ],
    }

    result = collect_inputs(metadata)

    # ------------------------------------------------------
    # Selected values
    # ------------------------------------------------------

    assert result["load_balancer"] == "lb-arn-123"
    assert result["target_group"] == "tg-arn-123"
    assert result["target"] == "target-123"

    # ------------------------------------------------------
    # Parent / child calls
    # ------------------------------------------------------

    selector.select.assert_called_once_with("elb")

    assert selector.select_child.call_count == 2

    selector.select_child.assert_any_call(
        "elb",
        "lb-arn-123",
        "elb-target-group",
    )

    selector.select_child.assert_any_call(
        "elb-target-group",
        "tg-arn-123",
        "elb-target",
    )


# ----------------------------------------------------------
# EKS Cluster / Namespace / Pod Resource Selection
# ----------------------------------------------------------

@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_eks_cluster_namespace_pod_chain(
    mock_title,
    mock_selector,
):
    context.region = "eu-central-1"

    selector = mock_selector.return_value

    # EKS Cluster
    selector.select.side_effect = [
        {"name": "Chaos-POC-v2"},
    ]

    # Namespace, then Pod
    selector.select_child.side_effect = [
        {"name": "default"},
        {
            "name": "chaosforge-io-test-897dbd5d5-cpx8t",
            "replicas": 1,
        },
    ]

    metadata = {
        "name": "EKS Pod Target",
        "inputs": [
            {
                "name": "eks_cluster",
                "label": "EKS Cluster",
                "type": "aws_resource",
                "resource_type": "eks",
                "return": "name",
                "required": True,
            },
            {
                "name": "namespace",
                "label": "Kubernetes Namespace",
                "type": "aws_resource",
                "resource_type": "eks-namespace",
                "parent": "eks_cluster",
                "return": "name",
                "required": True,
            },
            {
                "name": "pod",
                "label": "Target Pod",
                "type": "aws_resource",
                "resource_type": "eks-pod",
                "parent": "namespace",
                "return": "name",
                "required": True,
            },
        ],
    }

    result = collect_inputs(metadata)

    assert result["eks_cluster"] == "Chaos-POC-v2"
    assert result["namespace"] == "default"
    assert result["pod"] == "chaosforge-io-test-897dbd5d5-cpx8t"

    selector.select.assert_called_once_with("eks")

    selector.select_child.assert_any_call(
        "eks",
        "Chaos-POC-v2",
        "eks-namespace",
    )

    selector.select_child.assert_any_call(
        "eks-namespace",
        ("Chaos-POC-v2", "default"),
        "eks-pod",
    )

@patch("chaosforge.interfaces.cli.interactive.input_engine.ResourceSelector")
@patch("chaosforge.interfaces.cli.interactive.input_engine.title")
def test_collect_inputs_eks_resource_rediscovery_in_edit_mode(
    mock_title,
    mock_selector,
):
    context.region = "eu-central-1"

    selector = mock_selector.return_value

    # Current resources returned by EKS discovery
    selector.select.return_value = {
        "name": "Chaos-POC-v2",
    }

    selector.select_child.side_effect = [
        {"name": "default"},
        {
            "name": "chaosforge-io-test-897dbd5d5-cpx8t",
            "replicas": 1,
        },
    ]

    metadata = {
        "name": "EKS Pod Target",
        "inputs": [
            {
                "name": "eks_cluster",
                "label": "EKS Cluster",
                "type": "aws_resource",
                "resource_type": "eks",
                "return": "name",
                "required": True,
            },
            {
                "name": "namespace",
                "label": "Kubernetes Namespace",
                "type": "aws_resource",
                "resource_type": "eks-namespace",
                "parent": "eks_cluster",
                "return": "name",
                "required": True,
            },
            {
                "name": "pod",
                "label": "Target Pod",
                "type": "aws_resource",
                "resource_type": "eks-pod",
                "parent": "namespace",
                "return": "name",
                "required": True,
            },
        ],
    }

    prefill = {
        "eks_cluster": "Chaos-POC-v2",
        "namespace": "external-dns",
        "pod": "external-dns-old-pod",
    }

    result = collect_inputs(
        metadata,
        prefill=prefill,
        edit_mode=True,
    )

    assert result["eks_cluster"] == "Chaos-POC-v2"
    assert result["namespace"] == "default"
    assert result["pod"] == "chaosforge-io-test-897dbd5d5-cpx8t"

    selector.select.assert_called_once_with("eks")

    selector.select_child.assert_any_call(
        "eks",
        "Chaos-POC-v2",
        "eks-namespace",
    )

    selector.select_child.assert_any_call(
        "eks-namespace",
        ("Chaos-POC-v2", "default"),
        "eks-pod",
    )
