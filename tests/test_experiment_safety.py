from chaosforge.application.campaigns.factory import create_experiment
from chaosforge.application.safety import irreversible_experiments, reversibility
from chaosforge.models import Campaign, Experiment


def test_safety_classifies_known_persistent_and_reversible_experiments():
    assert reversibility("azure_redis", "azure-redis-flush") == "irreversible"
    assert reversibility("azure_app_service", "azure-app-service-toolkit-stop") == "reversible"
    assert reversibility(
        "fis",
        "fis-create-experiment",
        {"service_id": "ecs", "experiment_id": "stop-task"},
    ) == "irreversible"
    assert reversibility(
        "fis",
        "fis-create-experiment",
        {"service_id": "ec2", "experiment_id": "stop-instances"},
    ) == "reversible"


def test_irreversible_experiments_reresolves_catalog_safety_over_saved_display_value():
    campaign = Campaign(
        experiments=[
            Experiment(
                "azure-redis-flush",
                "azure_redis",
                "Flush",
                "",
                {},
                reversibility="reversible",
            ),
            Experiment(
                "lambda-timeout",
                "lambda",
                "Timeout",
                "",
                {},
                reversibility="irreversible",
            ),
        ]
    )

    assert [experiment.id for experiment in irreversible_experiments(campaign)] == [
        "azure-redis-flush"
    ]


def test_factory_sets_catalog_owned_reversibility():
    experiment = create_experiment(
        "azure_redis",
        {"id": "azure-redis-flush", "name": "Flush", "engine": "Azure SDK", "inputs": []},
    )

    assert experiment.reversibility == "irreversible"
