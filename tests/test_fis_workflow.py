from chaosforge.providers.aws.fis.workflow import FISWorkflow


def test_fis_workflow_initialization():

    workflow = FISWorkflow()

    assert workflow.catalog is not None
