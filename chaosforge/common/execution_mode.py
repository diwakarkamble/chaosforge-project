"""Tracks whether the current thread is running an experiment under the web UI.

The interactive CLI confirmation prompts block on real process stdin, which
the web server never receives input on. Code paths that would otherwise call
`prompt()`/`confirm()` should check `is_web_execution()` and skip the prompt
when running inside a web-triggered execution thread.
"""

import threading

_state = threading.local()


def set_web_execution(active):
    _state.active = active


def is_web_execution():
    return getattr(_state, "active", False)
