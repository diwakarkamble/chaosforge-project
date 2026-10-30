import json

import pytest

from e2e.webui.functional.manifest import ManifestError, load_inputs, load_manifest


def test_load_manifest_supports_yaml_environment_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("E2E_REGION", "eu-central-1")
    manifest = tmp_path / "targets.yaml"
    manifest.write_text(
        """version: 1
components:
  aws:
    lambda:
      region: ${E2E_REGION}
      selector: '#function_name'
      target_variable: lambda_name
      experiments: [aws-lambda-concurrency]
""",
        encoding="utf-8",
    )

    loaded = load_manifest(manifest)

    assert loaded["components"]["aws"]["lambda"]["region"] == "eu-central-1"


def test_load_manifest_supports_json(tmp_path):
    manifest = tmp_path / "targets.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "components": {
                    "azure": {
                        "azure_vm": {
                            "resource_type": "Microsoft.Compute/virtualMachines",
                            "selector": "#resource_id",
                            "target_variable": "resource_id",
                            "experiments": ["azure-vm-reboot"],
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert load_manifest(manifest)["version"] == 1


def test_load_inputs_supports_defaults_overrides_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("E2E_CERT", "e2e-certificate")
    inputs = tmp_path / "inputs.yaml"
    inputs.write_text(
        """version: 1
defaults:
  wait_seconds: 30
components:
  azure_key_vault:
    experiments:
      azure-key-vault-disable-certificate:
        certificate_name: ${E2E_CERT}
""",
        encoding="utf-8",
    )

    assert load_inputs(inputs) == {
        "defaults": {"wait_seconds": 30},
        "components": {
            "azure_key_vault": {
                "experiments": {
                    "azure-key-vault-disable-certificate": {"certificate_name": "e2e-certificate"}
                }
            }
        },
    }


@pytest.mark.parametrize(
    "content, message",
    [
        ("version: 2\ncomponents: {}", "version: 1"),
        ("version: 1\ncomponents: {}", "non-empty components"),
        (
            """version: 1
components:
  aws:
    lambda:
      selector: '#function_name'
      target_variable: lambda_name
      experiments: [aws-lambda-concurrency]
""",
            "requires region",
        ),
        (
            """version: 1
components:
  aws:
    lambda:
      region: eu-central-1
      selector: '#function_name'
      target_variable: lambda_name
      inputs: invalid
      experiments: [aws-lambda-concurrency]
""",
            "inputs must be an object",
        ),
    ],
)
def test_load_manifest_rejects_invalid_configuration(tmp_path, content, message):
    manifest = tmp_path / "invalid.yaml"
    manifest.write_text(content, encoding="utf-8")

    with pytest.raises(ManifestError, match=message):
        load_manifest(manifest)
