"""
Generic Campaign Builder
"""

from chaosforge.application.campaigns.factory import create_experiment
from chaosforge.application.campaigns.manager import add
from chaosforge.interfaces.cli.session import context


def build_experiment(service, metadata, variables=None):

    #
    # Create empty variables dictionary if not supplied
    #
    experiment = create_experiment(
        service,
        metadata,
        variables,
        default_region=context.region,
    )

    add(experiment)

    return experiment
