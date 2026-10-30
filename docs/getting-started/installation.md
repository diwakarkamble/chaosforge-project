# Installation

## Prerequisites

- Python 3.14 or newer; Python 3.13 and older are unsupported
- Git
- Credentials for the cloud provider under test
- AWS CLI for AWS workflows
- Azure CLI for AKS and Azure Chaos Studio workflows
- A valid kubeconfig or in-cluster identity for Kubernetes experiments
- Helm when Chaos Mesh installation is requested; `kubectl` is optional

## Local Environment

The Python package and local Web interface support macOS, Linux, and Windows.
The setup commands vary only for Python launcher and virtual-environment
activation. Cloud and Kubernetes experiments additionally depend on the
provider tools available on the host.

### macOS and Linux

```bash
git clone <repository-url>
cd chaos-engineering
python3.14 -m venv .venv && source .venv/bin/activate && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -r requirements.txt && .venv/bin/python -m pip install -e .
```

The chained command stops on the first failed step. Activation makes
`chaosforge` available as the project-local CLI command in that shell.

### Windows PowerShell

```powershell
git clone <repository-url>
cd chaos-engineering
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

If PowerShell prevents activation, apply an organization-approved policy for
the current process before activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

### Windows Command Prompt

```bat
git clone <repository-url>
cd chaos-engineering
py -3.14 -m venv .venv
.venv\Scripts\activate.bat
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
```

## Configuration Defaults And Validation

Experiment metadata is the shared configuration contract for CLI, Web, and
YAML campaigns. It defines defaults, type constraints, allowed choices, and
numeric ranges. The CLI accepts a displayed default when Enter is pressed; Web
forms prefill the same value and restore it if a configuration input is blank.

Resource targets and environment-specific values must still be selected or
entered explicitly. YAML import, planning, and execution validate the same
metadata constraints before a provider action is started.

### Tooling Notes

- The macOS/Linux setup is intentionally one pasteable `&&` chain. Windows
  commands remain separate because Windows PowerShell 5.1 does not support `&&`.
- AWS experiments require AWS CLI and valid AWS SDK credentials.
- Azure experiments use `DefaultAzureCredential`; Azure CLI login is one
  supported local development credential source. Redis experiments use Azure SDK
  clients rather than Azure CLI commands.
- Kubernetes experiments use the Kubernetes Python client and require a valid
  EKS or AKS kubeconfig context or in-cluster identity. `kubectl` is optional as
  a compatibility fallback and for manual debugging.
- Helm is required only when Chaos Mesh installation is requested.
- Windows supports native AWS CLI, Azure CLI, `kubectl`, and Helm installations.
  WSL is also appropriate when Kubernetes tooling is standardized on Linux.

## Verification

```bash
.venv/bin/python --version
.venv/bin/chaosforge --help
.venv/bin/python -m pytest tests
.venv/bin/python -m ruff check chaosforge tests scripts loadtests
```

## Provider Authentication

ChaosForge uses the normal provider credential chains:

- AWS SDK and AWS CLI credentials for AWS resources and FIS.
- Azure CLI or `DefaultAzureCredential`-compatible credentials for Azure.
- The active kubeconfig context for Kubernetes operations.

Use least-privilege identities. Review generated IAM permissions and experiment
targets before approving a campaign.

## Example Campaigns

The maintained examples are portable YAML campaigns in `examples/campaigns/`.
They use placeholder resource names and must be updated for an approved
non-production environment before execution.
