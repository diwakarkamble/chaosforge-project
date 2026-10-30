import time
from urllib.parse import urlencode

TERMINAL_STATUSES = {"SUCCESS", "FAILED", "CANCELLED", "PARTIAL"}


def validate_campaign_review(review, expected_service, expected_experiment, expected_target=None):
    """Reject a review unless it covers exactly the expected experiment."""
    experiments = review.get("experiments") if isinstance(review, dict) else None

    if not isinstance(experiments, list) or len(experiments) != 1:
        raise AssertionError(
            "Refusing execution: permission review must contain exactly one "
            f"experiment; received {experiments!r}"
        )

    actual = experiments[0]
    if (
        not isinstance(actual, dict)
        or actual.get("service") != expected_service
        or str(actual.get("id")) != str(expected_experiment)
    ):
        raise AssertionError(
            "Refusing execution: reviewed experiment does not match the "
            f"configured experiment {expected_service}/{expected_experiment}; "
            f"received {actual!r}"
        )
    if expected_target is not None and actual.get("target") != expected_target:
        raise AssertionError(
            "Refusing execution: reviewed experiment target does not match the selected resource; "
            f"expected {expected_target!r}, received {actual.get('target')!r}"
        )


def wait_for_execution(
    page,
    base_url,
    cloud,
    run_id,
    timeout_seconds=600,
    poll_interval_seconds=2,
):
    """Wait for execution completion and fail unless it succeeds."""
    query = urlencode({"cloud": cloud, "run": run_id})
    status_url = (
        f"{base_url.rstrip('/')}/api/execution/status?{query}"
    )
    deadline = time.monotonic() + timeout_seconds
    last_status = None

    while time.monotonic() < deadline:
        response = page.request.get(status_url, timeout=15000)

        if response.status == 404:
            time.sleep(poll_interval_seconds)
            continue

        assert response.ok, (
            f"Execution status request failed: HTTP {response.status}; "
            f"body={response.text()}"
        )

        data = response.json()
        last_status = data

        if data.get("completed"):
            status = str(data.get("status", "")).upper()

            if status not in TERMINAL_STATUSES:
                raise AssertionError(
                    f"Unexpected terminal status {status!r} "
                    f"for execution {run_id}. Details: {data}"
                )

            if status != "SUCCESS":
                logs = page.request.get(
                    f"{base_url.rstrip('/')}/execution/logs?{query}", timeout=15000
                )
                output = logs.json() if logs.ok else logs.text()
                raise AssertionError(
                    f"Execution {run_id} finished with status {status}. "
                    f"Details: {data}. Execution log: {output}"
                )

            return data

        time.sleep(poll_interval_seconds)

    raise AssertionError(
        f"Execution {run_id} did not complete within "
        f"{timeout_seconds}s. Last status: {last_status}"
    )
