from chaosforge.application.validation.yaml import YAMLValidator


def test_valid_yaml_structure():
    data = {
        "campaign": {
            "name": "Lambda Memory Test",
            "continue_on_failure": False,
        },
        "cloud": {
            "provider": "aws",
        },
        "environment": {
            "account_id": "123456789012",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-memory",
                "variables": {
                    "lambda_name": "test-function",
                    "target_memory_size": 256,
                },
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is True
    assert result["errors"] == []


def test_irreversible_acknowledgement_must_be_boolean():
    result = YAMLValidator().validate(
        {
            "campaign": {"irreversible_operations_acknowledged": "yes"},
            "experiments": [],
        }
    )

    assert "campaign.irreversible_operations_acknowledged: must be a boolean." in result["errors"]


def test_missing_experiments():
    data = {
        "campaign": {
            "name": "Invalid Campaign",
        }
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert "experiments: is required." in result["errors"]


def test_experiments_must_be_list():
    data = {
        "experiments": {},
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert "experiments: must be a list." in result["errors"]


def test_experiment_required_keys():
    data = {
        "experiments": [
            {
                "variables": {},
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False

    assert "experiments[0].service: is required." in result["errors"]
    assert "experiments[0].experiment: is required." in result["errors"]


def test_unknown_root_key():
    data = {
        "campaign": {
            "name": "Test",
        },
        "experiments": [],
        "something_else": True,
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert "root: unknown key 'something_else'." in result["errors"]


def test_timezone_settings_require_curated_iana_zone():
    result = YAMLValidator().validate(
        {"settings": {"timezone": "Mars/Olympus"}, "experiments": []}
    )

    assert result["valid"] is False
    assert "settings.timezone: must be a supported IANA timezone." in result["errors"]


def test_timezone_settings_require_mapping_and_string_timezone():
    non_mapping = YAMLValidator().validate({"settings": "Asia/Shanghai", "experiments": []})
    non_string = YAMLValidator().validate({"settings": {"timezone": 8}, "experiments": []})

    assert "settings: must be a mapping/object." in non_mapping["errors"]
    assert "settings.timezone: must be a supported IANA timezone." in non_string["errors"]


def test_unknown_experiment_key():
    data = {
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-memory",
                "variables": {},
                "invalid_key": "value",
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert (
        "experiments[0]: unknown key 'invalid_key'."
        in result["errors"]
    )


def test_invalid_cloud_provider():
    data = {
        "cloud": {
            "provider": "gcp",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-memory",
                "variables": {},
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert any(
        "cloud.provider: unsupported provider 'gcp'."
        in error
        for error in result["errors"]
    )


def test_invalid_campaign_types():
    data = {
        "campaign": {
            "name": 123,
            "continue_on_failure": "yes",
        },
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-memory",
                "variables": {},
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False

    assert "campaign.name: must be a string." in result["errors"]

    assert (
        "campaign.continue_on_failure: must be a boolean."
        in result["errors"]
    )


def test_variables_must_be_mapping():
    data = {
        "experiments": [
            {
                "service": "lambda",
                "experiment": "lambda-memory",
                "variables": [],
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert (
        "experiments[0].variables: "
        "must be a mapping/object."
        in result["errors"]
    )


def test_multiple_validation_errors():
    data = {
        "bad_root_key": True,
        "cloud": {
            "provider": "gcp",
        },
        "experiments": [
            {
                "service": "",
                "variables": [],
            }
        ],
    }

    result = YAMLValidator().validate(data)

    assert result["valid"] is False
    assert len(result["errors"]) >= 4
