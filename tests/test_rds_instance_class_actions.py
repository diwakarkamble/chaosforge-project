from unittest.mock import MagicMock, mock_open, patch

import pytest

from chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions import (
    capture_current_instance_class,
    restore_instance_class,
    update_instance_class,
    wait_for_duration,
)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.json.dump")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_capture_current_instance_class(
    mock_get_client, mock_open_file, mock_dump, mock_print
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceClass": "db.t3.medium"}]
    }

    mock_get_client.return_value = client

    capture_current_instance_class("db1", "eu-central-1")

    mock_dump.assert_called_once()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_instance_class_same_family(
    mock_get_client, mock_wait, mock_print, mock_input
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "Engine": "mysql",
                "EngineVersion": "8.0",
                "LicenseModel": "general-public-license",
                "DBInstanceClass": "db.t3.medium",
            }
        ]
    }

    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t3.medium", "db.t3.large", "db.m5.large"]}
            ]
        }
    }

    mock_get_client.return_value = client

    update_instance_class("db1", "eu-central-1")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", DBInstanceClass="db.t3.large", ApplyImmediately=True
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"]({"DBInstanceClass": "db.t3.large"}) is True


@patch("builtins.input")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_instance_class_uses_supplied_target_without_prompt(
    mock_get_client, mock_wait, _mock_print, mock_input
):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"Engine": "mysql", "EngineVersion": "8.0", "LicenseModel": "general-public-license", "DBInstanceClass": "db.t3.medium"}]
    }
    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t3.medium", "db.t3.large"]}
            ]
        }
    }
    mock_get_client.return_value = client

    update_instance_class("db1", "eu-central-1", target_instance_class="db.t3.large")

    mock_input.assert_not_called()
    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1", DBInstanceClass="db.t3.large", ApplyImmediately=True
    )
    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"]({"DBInstanceClass": "db.t3.large"}) is True


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_instance_class_rejects_unavailable_supplied_target(mock_get_client):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"Engine": "mysql", "EngineVersion": "8.0", "LicenseModel": "general-public-license", "DBInstanceClass": "db.t3.medium"}]
    }
    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t3.medium", "db.t3.large"]}
            ]
        }
    }
    mock_get_client.return_value = client

    with pytest.raises(ValueError, match="not a valid modification"):
        update_instance_class("db1", "eu-central-1", target_instance_class="db.m5.large")
    client.modify_db_instance.assert_not_called()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_instance_class_rejects_orderable_but_invalid_selected_instance_target(
    mock_get_client,
):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceClass": "db.t3.medium"}]
    }
    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.m5.large"]}
            ]
        }
    }
    mock_get_client.return_value = client

    with pytest.raises(ValueError, match="db.t3.large.*not a valid modification"):
        update_instance_class(
            "database-1", "eu-central-1", target_instance_class="db.t3.large"
        )

    client.modify_db_instance.assert_not_called()


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_instance_class_rejects_when_aws_returns_no_valid_modifications(
    mock_get_client,
):
    client = MagicMock()
    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceClass": "db.t3.medium"}]
    }
    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": []
        }
    }
    mock_get_client.return_value = client

    with pytest.raises(ValueError, match="did not return any valid"):
        update_instance_class("database-1", "eu-central-1", "db.t3.large")

    client.modify_db_instance.assert_not_called()


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_instance_class_other_family(
    mock_get_client, mock_wait, mock_print, mock_input
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "Engine": "mysql",
                "EngineVersion": "8.0",
                "LicenseModel": "general-public-license",
                "DBInstanceClass": "db.t3.medium",
            }
        ]
    }

    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t3.medium", "db.m5.large", "db.r5.large"]}
            ]
        }
    }

    mock_get_client.return_value = client

    update_instance_class("db1", "eu-central-1")

    client.modify_db_instance.assert_called_once()


@patch("builtins.input", side_effect=["abc", "1"])
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_invalid_then_valid(mock_get_client, mock_wait, mock_print, mock_input):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "Engine": "mysql",
                "EngineVersion": "8.0",
                "LicenseModel": "general-public-license",
                "DBInstanceClass": "db.t3.medium",
            }
        ]
    }

    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t3.medium", "db.t3.large"]}
            ]
        }
    }

    mock_get_client.return_value = client

    update_instance_class("db1", "eu-central-1")

    assert mock_input.call_count == 2


@patch("builtins.input", side_effect=["99", "1"])
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_update_invalid_index(mock_get_client, mock_wait, mock_print, mock_input):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "Engine": "mysql",
                "EngineVersion": "8.0",
                "LicenseModel": "general-public-license",
                "DBInstanceClass": "db.t3.medium",
            }
        ]
    }

    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.t3.medium", "db.t3.large"]}
            ]
        }
    }

    mock_get_client.return_value = client

    update_instance_class("db1", "eu-central-1")

    assert mock_input.call_count == 2


@patch("time.sleep")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
def test_wait_for_duration(mock_print, mock_sleep):
    wait_for_duration("10")

    mock_sleep.assert_called_once_with(10.0)


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_restore_instance_class(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    client = MagicMock()

    mock_get_client.return_value = client

    mock_load.return_value = {"original_class": "db.t3.medium"}
    client.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceClass": "db.t3.large"}]
    }

    restore_instance_class("db1", "eu-central-1")

    client.modify_db_instance.assert_called_once_with(
        DBInstanceIdentifier="db1",
        DBInstanceClass="db.t3.medium",
        ApplyImmediately=True,
    )

    args, kwargs = mock_wait.call_args
    assert args == (client, "db1")
    assert kwargs["expected_instance"]({"DBInstanceClass": "db.t3.medium"}) is True


@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.json.load")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.open", new_callable=mock_open)
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_restore_instance_class_skips_when_update_was_rejected(
    mock_get_client, mock_open_file, mock_load, mock_wait, mock_print
):
    mock_load.return_value = {"original_class": "db.t3.medium"}
    mock_get_client.return_value.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceClass": "db.t3.medium"}]
    }

    restore_instance_class("db1", "eu-central-1")

    mock_get_client.return_value.modify_db_instance.assert_not_called()
    mock_wait.assert_not_called()
    mock_print.assert_called_once_with("Instance Class was not changed; rollback skipped.")


@patch("builtins.input", return_value="1")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.print")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.wait_for_db_available")
@patch("chaosforge.providers.aws.components.rds.experiments.toolkit.actions.rds_instance_class_actions.get_client")
def test_describe_valid_modifications_called_for_selected_instance(
    mock_get_client, mock_wait, mock_print, mock_input
):
    client = MagicMock()

    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "Engine": "postgres",
                "EngineVersion": "15",
                "LicenseModel": "postgresql-license",
                "DBInstanceClass": "db.m5.large",
            }
        ]
    }

    client.describe_valid_db_instance_modifications.return_value = {
        "ValidDBInstanceModificationsMessage": {
            "ValidDBInstanceModifications": [
                {"ValidDBInstanceClasses": ["db.m5.xlarge"]}
            ]
        }
    }

    mock_get_client.return_value = client

    update_instance_class("db1", "eu-central-1")

    client.describe_valid_db_instance_modifications.assert_called_once_with(
        DBInstanceIdentifier="db1"
    )
