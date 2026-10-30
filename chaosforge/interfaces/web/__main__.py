"""Run the current Flask interface as ``python -m chaosforge.interfaces.web``."""

import signal

from chaosforge.interfaces.web.app import app
from chaosforge.interfaces.web.execution import executor, executors


def _request_graceful_shutdown(_signum, _frame):
    """Translate termination signals into normal Python shutdown handling."""

    raise KeyboardInterrupt


def main():
    """Start the local Flask application."""

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _request_graceful_shutdown)
    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        executor.wait_for_completion()
        for cloud_executor in executors.values():
            if cloud_executor is not executor:
                cloud_executor.wait_for_completion()
        signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    main()
