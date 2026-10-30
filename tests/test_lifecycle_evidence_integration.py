import json
import os
import shutil
import tempfile
import zipfile
from typing import ClassVar

from chaosforge.lifecycle.lifecycle_runner import LifecycleRunner
from chaosforge.storage.evidence_artifact import EvidenceArtifactWriter
from chaosforge.storage.evidence_bundle import EvidenceBundleWriter


class MockCheck:
    name = "mock-check"

    def capture(self, target):
        return {
            "desired_replicas": 3,
            "ready_replicas": 3,
            "available_replicas": 3,
        }

    def validate(self, target, baseline):
        return {
            "passed": True,
            "baseline": baseline,
            "current": baseline,
        }


class MockCheckResolver:
    def resolve(self, experiment, discovery):
        return MockCheck()


class MockRunner:
    def execute(self, experiment):
        experiment.status = "SUCCESS"
        experiment.error_message = ""


class MockExperiment:
    id = "eks-replica-reduction"
    service = "eks"
    name = "Replica Reduction"
    json_file = "mock.json"
    engine = "Chaos Toolkit"

    variables: ClassVar[dict] = {
        "eks_cluster": "mock-cluster",
        "namespace": "default",
        "deployment_name": "mock-api",
        "reduced_replicas": 2,
        "wait_seconds": 1,
        "aws_region": "eu-central-1",
    }

    status = "Pending"
    error_message = ""


def test_lifecycle_evidence_integration():
    temp_root = tempfile.mkdtemp()

    try:
        runner = LifecycleRunner(
            runner=MockRunner(),
            check_resolver=MockCheckResolver(),
        )

        artifact_writer = EvidenceArtifactWriter(
            evidence_root=temp_root
        )

        bundle_writer = EvidenceBundleWriter(
            evidence_root=temp_root
        )

        # Replace the writers used by LifecycleRunner with
        # temporary test writers so nothing is written into
        # the real project evidence directory.
        runner._evidence_artifact_writer = artifact_writer
        runner._evidence_bundle_writer = bundle_writer

        # The current LifecycleRunner creates its own writers.
        # For this integration test, patch the classes used by
        # the runner module.
        import chaosforge.lifecycle.lifecycle_runner as lifecycle_module

        original_artifact_writer = (
            lifecycle_module.EvidenceArtifactWriter
        )
        original_bundle_writer = (
            lifecycle_module.EvidenceBundleWriter
        )

        lifecycle_module.EvidenceArtifactWriter = (
            lambda: artifact_writer
        )

        lifecycle_module.EvidenceBundleWriter = (
            lambda: bundle_writer
        )

        try:
            experiment = MockExperiment()

            context = runner.execute(
                experiment
            )

        finally:
            lifecycle_module.EvidenceArtifactWriter = (
                original_artifact_writer
            )

            lifecycle_module.EvidenceBundleWriter = (
                original_bundle_writer
            )

        execution_id = context.execution_id

        evidence_directory = os.path.join(
            temp_root,
            execution_id,
        )

        bundle_path = os.path.join(
            temp_root,
            f"{execution_id}.zip",
        )

        assert os.path.isdir(
            evidence_directory
        )

        assert os.path.isfile(
            bundle_path
        )

        evidence_json = os.path.join(
            evidence_directory,
            "evidence.json",
        )

        assert os.path.isfile(
            evidence_json
        )

        with open(
            evidence_json,
            encoding="utf-8",
        ) as file:
            evidence = json.load(file)

        assert (
            evidence["execution"]["execution_id"]
            == execution_id
        )

        assert (
            evidence["execution"]["state"]
            == "VALIDATION_PASSED"
        )

        assert (
            evidence["experiment"]["status"]
            == "SUCCESS"
        )

        with zipfile.ZipFile(
            bundle_path,
            "r",
        ) as bundle:

            names = bundle.namelist()

        assert (
            f"{execution_id}/evidence.json"
            in names
        )

        assert (
            f"{execution_id}/execution.json"
            in names
        )

        assert (
            f"{execution_id}/experiment.json"
            in names
        )

        print(
            f"Evidence directory: "
            f"{evidence_directory}"
        )

        print(
            f"Evidence bundle: "
            f"{bundle_path}"
        )

    finally:
        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )
