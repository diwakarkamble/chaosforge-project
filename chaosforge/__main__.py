"""Run the ChaosForge command-line interface as ``python -m chaosforge``."""

from chaosforge.common.console_encoding import configure_windows_output

configure_windows_output()
from chaosforge.interfaces.cli.main import main

if __name__ == "__main__":
    main()
