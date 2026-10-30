import time

import boto3


def get_client(region):
    """
    Returns an Amazon RDS client.
    """

    return boto3.client("rds", region_name=region)


def wait_for_db_available(
    client,
    db_instance_identifier,
    timeout=600,
    expected_instance=None,
):
    """
    Waits for an RDS modification to complete.

    Expected lifecycle:

        available
            ↓
        modifying
            ↓
        available

    When ``expected_instance`` is provided, completion is based on the
    authoritative instance fields as well as the available status. This is
    required for RDS settings that can apply without an observable
    ``modifying`` status transition.
    """

    print("\nWaiting for RDS modification...")

    modification_started = False

    elapsed = 0

    while elapsed < timeout:
        response = client.describe_db_instances(
            DBInstanceIdentifier=db_instance_identifier
        )

        status = response["DBInstances"][0]["DBInstanceStatus"]

        print(f"Current Status : {status}")

        instance = response["DBInstances"][0]

        if expected_instance is not None:
            if status == "available" and expected_instance(instance):
                print("Modification completed.")
                return

        # AWS has started applying the change.

        if status == "modifying":
            modification_started = True

        #
        # Modification completed
        #

        elif expected_instance is None and modification_started and status == "available":
            print("Modification completed.")

            return

        #
        # Wait before checking again
        #

        time.sleep(5)

        elapsed += 5

    raise TimeoutError(
        f"Timed out waiting for RDS instance "
        f"{db_instance_identifier} "
        f"to complete modification."
    )
