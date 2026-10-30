from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from chaosforge.application.services import cloud_identity


@pytest.fixture(autouse=True)
def clear_identity_cache():
    cloud_identity.clear_cloud_identity_cache()
    yield
    cloud_identity.clear_cloud_identity_cache()


def test_aws_identity_prefers_account_alias(monkeypatch):
    clients = {
        "sts": SimpleNamespace(
            get_caller_identity=lambda: {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/chaosforge",
            }
        ),
        "iam": SimpleNamespace(list_account_aliases=lambda: {"AccountAliases": ["engineering"]}),
    }
    monkeypatch.setattr(cloud_identity.boto3, "client", lambda service, **_: clients[service])

    assert cloud_identity.get_cloud_identity("aws") == {
        "authenticated": True,
        "label": "AWS account",
        "name": "engineering",
        "account_id": "123456789012",
        "principal_arn": "arn:aws:iam::123456789012:user/chaosforge",
    }


def test_aws_identity_falls_back_to_account_id_and_handles_missing_login(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda service, **_: SimpleNamespace(
            get_caller_identity=lambda: {"Account": "123456789012"}
        )
        if service == "sts"
        else (_ for _ in ()).throw(RuntimeError("not allowed")),
    )
    assert cloud_identity.get_cloud_identity("aws")["name"] == "123456789012"

    cloud_identity.clear_cloud_identity_cache()
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("expired")),
    )
    assert cloud_identity.get_cloud_identity("aws")["name"] == "Not logged in"


def test_aws_identity_keeps_transient_probe_failures_indeterminate(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network unavailable")),
    )

    identity = cloud_identity.get_cloud_identity("aws")

    assert identity["authenticated"] is False
    assert identity["status"] == "unknown"
    assert identity["name"] == "Identity check unavailable"


def test_aws_identity_marks_expired_credentials_unauthenticated(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("token expired")),
    )

    identity = cloud_identity.get_cloud_identity("aws")

    assert identity["authenticated"] is False
    assert identity["status"] == "unauthenticated"


def test_aws_identity_marks_missing_sdk_credentials_unauthenticated(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_caller_identity=lambda: (_ for _ in ()).throw(cloud_identity.NoCredentialsError())
        ),
    )

    assert cloud_identity.get_cloud_identity("aws")["status"] == "unauthenticated"


def test_aws_identity_classifies_client_error_tokens_and_transient_errors(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_caller_identity=lambda: (_ for _ in ()).throw(
                ClientError({"Error": {"Code": "ExpiredToken"}}, "GetCallerIdentity")
            )
        ),
    )
    assert cloud_identity.get_cloud_identity("aws")["status"] == "unauthenticated"

    cloud_identity.clear_cloud_identity_cache()
    monkeypatch.setattr(
        cloud_identity.boto3,
        "client",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_caller_identity=lambda: (_ for _ in ()).throw(
                ClientError({"Error": {"Code": "ThrottlingException"}}, "GetCallerIdentity")
            )
        ),
    )
    assert cloud_identity.get_cloud_identity("aws")["status"] == "unknown"


def test_azure_identity_uses_active_subscription_name(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout='{"name": "Platform"}'),
    )

    assert cloud_identity.get_cloud_identity("azure") == {
        "authenticated": True,
        "label": "Azure subscription",
        "name": "Platform",
    }


def test_azure_identity_uses_windows_azure_cli_entry_point(monkeypatch):
    monkeypatch.setattr("chaosforge.common.azure_cli.os.name", "nt")
    run = MagicMock(return_value=SimpleNamespace(returncode=0, stdout='{"name": "Platform"}'))
    monkeypatch.setattr(cloud_identity.subprocess, "run", run)

    assert cloud_identity.get_cloud_identity("azure")["name"] == "Platform"
    assert run.call_args.args[0][0] == "az.cmd"


def test_azure_identity_includes_active_subscription_id(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"name": "Platform", "id": "subscription-id"}',
        ),
    )

    assert cloud_identity.get_cloud_identity("azure")["subscription_id"] == "subscription-id"


def test_azure_identity_reports_missing_login(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )

    assert cloud_identity.get_cloud_identity("azure")["name"] == "Not logged in"
    assert cloud_identity.get_cloud_identity("azure")["status"] == "unauthenticated"
    assert cloud_identity.get_cloud_identity("azure")["status"] == "unauthenticated"


@pytest.mark.parametrize("outcome", [FileNotFoundError(), cloud_identity.subprocess.SubprocessError("bad")])
def test_azure_identity_handles_unavailable_cli(monkeypatch, outcome):
    monkeypatch.setattr(cloud_identity.subprocess, "run", MagicMock(side_effect=outcome))
    assert cloud_identity.get_cloud_identity("azure")["name"] == "Identity check unavailable"
    assert cloud_identity.get_cloud_identity("azure")["status"] == "unknown"


def test_azure_identity_handles_invalid_account_json_and_unknown_provider(monkeypatch):
    monkeypatch.setattr(
        cloud_identity.subprocess,
        "run",
        MagicMock(return_value=SimpleNamespace(returncode=0, stdout="not-json")),
    )
    assert cloud_identity.get_cloud_identity("azure")["name"] == "Identity check unavailable"
    assert cloud_identity.get_cloud_identity("azure")["status"] == "unknown"
    assert cloud_identity.get_cloud_identity("gcp") == {
        "authenticated": False,
        "label": "Cloud",
        "name": "Not logged in",
    }


def test_identity_cache_expires_after_twenty_seconds(monkeypatch):
    clock = iter((0, 19, 20, 20))
    monkeypatch.setattr(cloud_identity.time, "monotonic", lambda: next(clock))
    lookup = MagicMock(
        return_value={"authenticated": True, "label": "AWS account", "name": "engineering"}
    )
    monkeypatch.setattr(cloud_identity, "_lookup_cloud_identity", lookup)

    assert cloud_identity.get_cloud_identity("aws")["name"] == "engineering"
    assert cloud_identity.get_cloud_identity("aws")["name"] == "engineering"
    assert cloud_identity.get_cloud_identity("aws")["name"] == "engineering"
    assert lookup.call_count == 2
