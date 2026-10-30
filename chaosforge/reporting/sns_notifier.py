import boto3


def publish_summary(topic_arn, region, campaign, report_file):
    """
    Publish campaign summary to Amazon SNS.
    """

    client = boto3.client("sns", region_name=region)

    success = sum(
        1
        for experiment in campaign.experiments
        if experiment.status.upper() in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
    )

    warnings = sum(
        1
        for experiment in campaign.experiments
        if experiment.status.upper() == "SUCCESS_WITH_WARNINGS"
    )

    failed = len(campaign.experiments) - success

    if failed == 0:
        result = "SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS"
    elif success == 0:
        result = "FAILED"
    else:
        result = "PARTIAL SUCCESS"

    message = f"""
CHAOSFORGE EXECUTION REPORT

Campaign : {campaign.name}

Result : {result}

Started : {campaign.start_time}

Finished : {campaign.end_time}

Total Duration : {campaign.duration:.1f} sec

Successful : {success}

Failed : {failed}

With Warnings : {warnings}

Report File

{report_file}
"""

    client.publish(
        TopicArn=topic_arn, Subject=f"ChaosForge - {campaign.name}", Message=message
    )

    print()
    print("✓ SNS notification sent successfully")
