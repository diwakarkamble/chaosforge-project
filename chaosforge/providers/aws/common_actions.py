import time


def wait_for_duration(wait_seconds):

    duration = float(wait_seconds)

    print(f"Waiting for {duration} seconds...")

    time.sleep(duration)

    print("Wait completed.")
