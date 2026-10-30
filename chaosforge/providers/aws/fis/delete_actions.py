import boto3
from botocore.exceptions import ClientError

from chaosforge.interfaces.cli.interactive.ui.status import error, success


def delete_fis_template(experiment_template_id, region):

    client = boto3.client("fis", region_name=region)

    try:
        client.delete_experiment_template(id=experiment_template_id)

        success("FIS Experiment Template deleted successfully.")

    except ClientError as e:
        error(str(e))
