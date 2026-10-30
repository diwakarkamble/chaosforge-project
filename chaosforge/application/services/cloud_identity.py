"""Best-effort identity summaries for the selected cloud provider."""

import json
import subprocess
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

from chaosforge.common.azure_cli import azure_cli_command

IDENTITY_CLIENT_CONFIG = Config(connect_timeout=1, read_timeout=1, retries={"max_attempts": 1})
IDENTITY_CACHE_SECONDS = 20
_identity_cache = {}


def get_cloud_identity(provider, region="us-east-1", *, refresh=False):
    """Return a display-safe login state without raising on unavailable credentials."""
    key = (provider, region)
    cached = _identity_cache.get(key)
    if not refresh and cached and time.monotonic() - cached[0] < IDENTITY_CACHE_SECONDS:
        return cached[1]

    identity = _lookup_cloud_identity(provider, region)
    _identity_cache[key] = (time.monotonic(), identity)
    return identity


def clear_cloud_identity_cache():
    _identity_cache.clear()


def get_cached_cloud_identity(provider, region="us-east-1"):
    """Return a cached identity without blocking page rendering on cloud SDK calls."""
    cached = _identity_cache.get((provider, region))
    if cached and time.monotonic() - cached[0] < IDENTITY_CACHE_SECONDS:
        return cached[1]
    label = "AWS" if provider == "aws" else "Azure"
    return {"authenticated": False, "status": "unknown", "label": label, "name": "Checking identity"}


def _lookup_cloud_identity(provider, region):
    if provider == "aws":
        try:
            identity = boto3.client(
                "sts", region_name=region, config=IDENTITY_CLIENT_CONFIG
            ).get_caller_identity()
            account_id = identity.get("Account", "Unknown account")
            try:
                aliases = boto3.client(
                    "iam", region_name=region, config=IDENTITY_CLIENT_CONFIG
                ).list_account_aliases()
                name = aliases.get("AccountAliases", [account_id])[0]
            except Exception:  # noqa: BLE001 - aliases are optional IAM metadata.
                name = account_id
            result = {
                "authenticated": True,
                "label": "AWS account",
                "name": name,
                "account_id": account_id,
            }
            if identity.get("Arn"):
                result["principal_arn"] = identity["Arn"]
            return result
        except (NoCredentialsError, PartialCredentialsError):
            return {"authenticated": False, "status": "unauthenticated", "label": "AWS", "name": "Not logged in"}
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId", "UnrecognizedClientException"}:
                return {"authenticated": False, "status": "unauthenticated", "label": "AWS", "name": "Not logged in"}
            return {"authenticated": False, "status": "unknown", "label": "AWS", "name": "Identity check unavailable"}
        except Exception as exc:  # noqa: BLE001 - identity status must not block the UI.
            if "expired" in str(exc).lower():
                return {"authenticated": False, "status": "unauthenticated", "label": "AWS", "name": "Not logged in"}
            return {"authenticated": False, "status": "unknown", "label": "AWS", "name": "Identity check unavailable"}

    if provider == "azure":
        try:
            result = subprocess.run(
                azure_cli_command("account", "show", "--output", "json"),
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                account = json.loads(result.stdout)
                identity = {
                    "authenticated": True,
                    "label": "Azure subscription",
                    "name": account.get("name") or account.get("id", "Unknown subscription"),
                }
                if account.get("id"):
                    identity["subscription_id"] = account["id"]
                return identity
            return {"authenticated": False, "status": "unauthenticated", "label": "Azure", "name": "Not logged in"}
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            return {"authenticated": False, "status": "unknown", "label": "Azure", "name": "Identity check unavailable"}

    return {"authenticated": False, "label": "Cloud", "name": "Not logged in"}
