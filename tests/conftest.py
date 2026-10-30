import pytest


@pytest.fixture
def sample_lambda():

    return {"id": "lambda", "name": "AWS Lambda"}


@pytest.fixture
def sample_experiment():

    return {"fis_action": "aws:lambda:invocation-add-delay", "target_key": "Functions"}
