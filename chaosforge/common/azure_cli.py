"""Cross-platform Azure CLI command construction."""

import os


def azure_cli_command(*args):
    """Return an Azure CLI command executable by ``subprocess.run`` on this OS."""
    executable = "az.cmd" if os.name == "nt" else "az"
    return [executable, *args]
