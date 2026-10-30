"""Azure Key Vault secret actions with a persisted enabled-state rollback."""

import json
import os
import ssl
from pathlib import Path

from chaosforge.common.paths import repository_paths
from chaosforge.providers.azure.resource_id import resource_name


def disable_secret(resource_id, secret_name):
    _require(resource_id, secret_name)
    vault_url = f"https://{resource_name(resource_id)}.vault.azure.net"
    client = _client(vault_url)
    secret = client.get_secret(secret_name)
    _state_path(vault_url, secret_name).write_text(
        json.dumps({"enabled": secret.properties.enabled, "version": secret.properties.version}),
        encoding="utf-8",
    )
    return client.update_secret_properties(secret_name, secret.properties.version, enabled=False)


def restore_secret(resource_id, secret_name):
    _require(resource_id, secret_name)
    vault_url = f"https://{resource_name(resource_id)}.vault.azure.net"
    path = _state_path(vault_url, secret_name)
    if not path.is_file():
        return "No secret state was recorded."
    state = json.loads(path.read_text(encoding="utf-8"))
    result = _client(vault_url).update_secret_properties(
        secret_name, state.get("version"), enabled=state["enabled"]
    )
    path.unlink(missing_ok=True)
    return result


def _client(vault_url):
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca_bundle and not Path(ca_bundle).is_file():
        raise RuntimeError(f"Azure CA bundle was not found: {ca_bundle}")
    try:
        import truststore
        from azure.core.pipeline.transport import RequestsTransport
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        from requests import Session
        from requests.adapters import HTTPAdapter
    except ImportError as exc:
        dependency = exc.name or str(exc)
        raise RuntimeError(
            f"Azure Key Vault dependency is unavailable: {dependency}. "
            "Run `python -m pip install -r requirements.txt` in the ChaosForge environment."
        ) from exc
    session = Session()
    if ca_bundle:
        session.verify = ca_bundle
    else:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        class SystemTrustAdapter(HTTPAdapter):
            def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
                kwargs["ssl_context"] = context
                super().init_poolmanager(connections, maxsize, block, **kwargs)

            def proxy_manager_for(self, proxy, **kwargs):
                kwargs["ssl_context"] = context
                return super().proxy_manager_for(proxy, **kwargs)

        session.mount("https://", SystemTrustAdapter())
    transport = RequestsTransport(session=session, session_owner=True)
    return SecretClient(
        vault_url=vault_url,
        credential=DefaultAzureCredential(),
        transport=transport,
    )


def _state_path(*parts):
    path = repository_paths().runtime / "azure_key_vault"
    path.mkdir(parents=True, exist_ok=True)
    return path / ("secret-" + "-".join(parts).replace("/", "-").replace(":", "-") + ".json")


def _require(*values):
    if not all(str(value or "").strip() for value in values):
        raise ValueError("vault_url and secret_name are required.")
