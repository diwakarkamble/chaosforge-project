"""Cross-platform console encoding safeguards."""

import os
import sys


def configure_windows_output(streams=None, *, windows=None):
    """Replace unsupported output glyphs on legacy Windows console code pages."""
    if windows is None:
        windows = os.name
    if windows != "nt":
        return
    for stream in streams or (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
