from chaosforge.models import Campaign, Experiment


def test_experiment_defaults():

    experiment = Experiment(
        id="exp-1",
        service="lambda",
        name="Memory Chaos",
        json_file="memory.json",
        variables={"memory": 512},
    )

    assert experiment.id == "exp-1"
    assert experiment.service == "lambda"
    assert experiment.name == "Memory Chaos"
    assert experiment.json_file == "memory.json"
    assert experiment.variables == {"memory": 512}

    # Default values
    assert experiment.engine == "Chaos Toolkit"
    assert experiment.status == "Pending"


def test_experiment_custom_values():

    experiment = Experiment(
        id="fis-1",
        service="fis",
        name="FIS Experiment",
        json_file="fis.json",
        variables={},
        engine="AWS FIS",
        status="Completed",
    )

    assert experiment.engine == "AWS FIS"
    assert experiment.status == "Completed"


def test_campaign_defaults():

    campaign = Campaign()

    assert campaign.name == "Default Campaign"
    assert campaign.experiments == []


def test_campaign_independent_lists():

    campaign1 = Campaign()
    campaign2 = Campaign()

    campaign1.experiments.append("Experiment 1")

    assert campaign1.experiments == ["Experiment 1"]
    assert campaign2.experiments == []
