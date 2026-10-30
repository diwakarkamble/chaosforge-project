from unittest.mock import MagicMock, mock_open, patch

import pytest
from botocore.exceptions import ClientError

from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
    delete_state,
    get_bucket_encryption,
    get_bucket_lifecycle,
    get_bucket_policy,
    get_bucket_versioning,
    get_client,
    get_public_access_block,
    info,
    load_state,
    restore_bucket_policy,
    restore_encryption,
    restore_lifecycle,
    restore_public_access,
    restore_versioning,
    save_state,
    success,
    wait,
    warning,
)

# ============================================================
# Client
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.boto3.client")
def test_get_client(mock_client):

    get_client("eu-west-1")

    mock_client.assert_called_once_with(
        "s3",
        region_name="eu-west-1",
    )


# ============================================================
# save_state
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.datetime")
@patch("builtins.open", new_callable=mock_open)
def test_save_state(
    mock_file,
    mock_datetime,
):

    mock_datetime.now.return_value.isoformat.return_value = "timestamp"

    save_state(
        "experiment",
        {"bucket": "demo"},
    )

    handle = mock_file()

    handle.write.assert_called()


# ============================================================
# load_state
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data='{"bucket":"demo"}')
def test_load_state(
    mock_file,
    mock_exists,
):

    mock_exists.return_value = True

    state = load_state("experiment")

    assert state["bucket"] == "demo"


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.os.path.exists")
def test_load_state_missing(mock_exists):

    mock_exists.return_value = False

    with pytest.raises(RuntimeError):
        load_state("experiment")


def test_state_files_are_scoped_to_the_bucket():
    from chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common import (
        _state_file,
    )

    assert _state_file("s3_public_access", "bucket-a") != _state_file(
        "s3_public_access", "bucket-b"
    )


# ============================================================
# delete_state
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.os.remove")
@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.os.path.exists")
def test_delete_state(
    mock_exists,
    mock_remove,
):

    mock_exists.return_value = True

    delete_state("experiment")

    mock_remove.assert_called_once()


# ============================================================
# Logging
# ============================================================


def test_info(capsys):

    info("hello")

    assert "hello" in capsys.readouterr().out


def test_success(capsys):

    success("done")

    assert "done" in capsys.readouterr().out


def test_warning(capsys):

    warning("warn")

    assert "warn" in capsys.readouterr().out


# ============================================================
# wait
# ============================================================


@patch("chaosforge.providers.aws.components.s3.experiments.toolkit.actions.s3_common.time.sleep")
def test_wait(mock_sleep):

    wait(5)

    mock_sleep.assert_called_once_with(5)


# ============================================================
# Safe Read Helpers
# ============================================================


def test_get_bucket_versioning():

    client = MagicMock()

    client.get_bucket_versioning.return_value = {
        "Status": "Enabled",
    }

    result = get_bucket_versioning(
        client,
        "demo-bucket",
    )

    assert result == "Enabled"


def test_get_bucket_versioning_default():

    client = MagicMock()

    client.get_bucket_versioning.return_value = {}

    result = get_bucket_versioning(
        client,
        "demo-bucket",
    )

    assert result == "Suspended"


def test_get_bucket_encryption():

    client = MagicMock()

    client.get_bucket_encryption.return_value = {
        "ServerSideEncryptionConfiguration": {}
    }

    result = get_bucket_encryption(
        client,
        "demo-bucket",
    )

    assert result["ServerSideEncryptionConfiguration"] == {}


def test_get_bucket_encryption_not_configured():

    client = MagicMock()

    client.get_bucket_encryption.side_effect = ClientError(
        {
            "Error": {
                "Code": "ServerSideEncryptionConfigurationNotFoundError",
            }
        },
        "GetBucketEncryption",
    )

    assert get_bucket_encryption(client, "demo") is None


def test_get_bucket_policy():

    client = MagicMock()

    client.get_bucket_policy.return_value = {"Policy": "{}"}

    assert get_bucket_policy(client, "demo") == "{}"


def test_get_bucket_policy_none():

    client = MagicMock()

    client.get_bucket_policy.side_effect = ClientError(
        {
            "Error": {
                "Code": "NoSuchBucketPolicy",
            }
        },
        "GetBucketPolicy",
    )

    assert get_bucket_policy(client, "demo") is None


def test_get_bucket_lifecycle():

    client = MagicMock()

    client.get_bucket_lifecycle_configuration.return_value = {"Rules": []}

    result = get_bucket_lifecycle(
        client,
        "demo",
    )

    assert result["Rules"] == []


def test_get_bucket_lifecycle_none():

    client = MagicMock()

    client.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {
            "Error": {
                "Code": "NoSuchLifecycleConfiguration",
            }
        },
        "GetBucketLifecycleConfiguration",
    )

    assert get_bucket_lifecycle(client, "demo") is None


def test_get_public_access_block():

    client = MagicMock()

    client.get_public_access_block.return_value = {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
        }
    }

    result = get_public_access_block(
        client,
        "demo",
    )

    assert result["BlockPublicAcls"] is True


def test_get_public_access_block_none():

    client = MagicMock()

    client.get_public_access_block.side_effect = ClientError(
        {
            "Error": {
                "Code": "NoSuchPublicAccessBlockConfiguration",
            }
        },
        "GetPublicAccessBlock",
    )

    assert get_public_access_block(client, "demo") is None


# ============================================================
# Restore Helpers
# ============================================================


def test_restore_versioning():

    client = MagicMock()

    restore_versioning(
        client,
        "demo-bucket",
        "Enabled",
    )

    client.put_bucket_versioning.assert_called_once_with(
        Bucket="demo-bucket",
        VersioningConfiguration={"Status": "Enabled"},
    )


def test_restore_encryption_none():

    client = MagicMock()

    restore_encryption(
        client,
        "demo-bucket",
        None,
    )

    client.delete_bucket_encryption.assert_called_once_with(
        Bucket="demo-bucket",
    )


def test_restore_encryption():

    client = MagicMock()

    state = {"ServerSideEncryptionConfiguration": {"Rules": []}}

    restore_encryption(
        client,
        "demo-bucket",
        state,
    )

    client.put_bucket_encryption.assert_called_once_with(
        Bucket="demo-bucket",
        ServerSideEncryptionConfiguration=state["ServerSideEncryptionConfiguration"],
    )


def test_restore_bucket_policy_none():

    client = MagicMock()

    restore_bucket_policy(
        client,
        "demo-bucket",
        None,
    )

    client.delete_bucket_policy.assert_called_once_with(
        Bucket="demo-bucket",
    )


def test_restore_bucket_policy():

    client = MagicMock()

    restore_bucket_policy(
        client,
        "demo-bucket",
        "{}",
    )

    client.put_bucket_policy.assert_called_once_with(
        Bucket="demo-bucket",
        Policy="{}",
    )


def test_restore_lifecycle_none():

    client = MagicMock()

    restore_lifecycle(
        client,
        "demo-bucket",
        None,
    )

    client.delete_bucket_lifecycle.assert_called_once_with(
        Bucket="demo-bucket",
    )


def test_restore_lifecycle():

    client = MagicMock()

    state = {
        "Rules": [
            {
                "ID": "Rule1",
            }
        ]
    }

    restore_lifecycle(
        client,
        "demo-bucket",
        state,
    )

    client.put_bucket_lifecycle_configuration.assert_called_once_with(
        Bucket="demo-bucket",
        LifecycleConfiguration={
            "Rules": state["Rules"],
        },
    )


def test_restore_public_access_none():

    client = MagicMock()

    restore_public_access(
        client,
        "demo-bucket",
        None,
    )

    client.delete_public_access_block.assert_called_once_with(
        Bucket="demo-bucket",
    )


def test_restore_public_access():

    client = MagicMock()

    state = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }

    restore_public_access(
        client,
        "demo-bucket",
        state,
    )

    client.put_public_access_block.assert_called_once_with(
        Bucket="demo-bucket",
        PublicAccessBlockConfiguration=state,
    )


# ============================================================
# Exception Paths
# ============================================================


def test_get_bucket_encryption_other_exception():

    client = MagicMock()

    client.get_bucket_encryption.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
            }
        },
        "GetBucketEncryption",
    )

    with pytest.raises(ClientError):
        get_bucket_encryption(client, "demo")


def test_get_bucket_policy_other_exception():

    client = MagicMock()

    client.get_bucket_policy.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
            }
        },
        "GetBucketPolicy",
    )

    with pytest.raises(ClientError):
        get_bucket_policy(client, "demo")


def test_get_bucket_lifecycle_other_exception():

    client = MagicMock()

    client.get_bucket_lifecycle_configuration.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
            }
        },
        "GetBucketLifecycleConfiguration",
    )

    with pytest.raises(ClientError):
        get_bucket_lifecycle(client, "demo")


def test_get_public_access_block_other_exception():

    client = MagicMock()

    client.get_public_access_block.side_effect = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
            }
        },
        "GetPublicAccessBlock",
    )

    with pytest.raises(ClientError):
        get_public_access_block(client, "demo")


# ============================================================
# Ignore ClientError During Restore Delete
# ============================================================


def test_restore_encryption_delete_failure():

    client = MagicMock()

    client.delete_bucket_encryption.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}},
        "DeleteBucketEncryption",
    )

    # Should not raise
    restore_encryption(
        client,
        "demo-bucket",
        None,
    )


def test_restore_bucket_policy_delete_failure():

    client = MagicMock()

    client.delete_bucket_policy.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}},
        "DeleteBucketPolicy",
    )

    # Should not raise
    restore_bucket_policy(
        client,
        "demo-bucket",
        None,
    )


def test_restore_lifecycle_delete_failure():

    client = MagicMock()

    client.delete_bucket_lifecycle.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}},
        "DeleteBucketLifecycle",
    )

    # Should not raise
    restore_lifecycle(
        client,
        "demo-bucket",
        None,
    )


def test_restore_public_access_delete_failure():

    client = MagicMock()

    client.delete_public_access_block.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}},
        "DeletePublicAccessBlock",
    )

    # Should not raise
    restore_public_access(
        client,
        "demo-bucket",
        None,
    )
