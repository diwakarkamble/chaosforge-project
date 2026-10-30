import json
import os
import shutil
import tempfile
from types import SimpleNamespace

import pytest

from chaosforge.lifecycle.evidence import EvidenceBuilder
from chaosforge.lifecycle.execution_context import ExecutionContext
from chaosforge.lifecycle.execution_states import ExecutionState
from chaosforge.storage.evidence_artifact import EvidenceArtifactWriter


def test_evidence_artifact_writer():
    temp_root = tempfile.mkdtemp()

    try:
        context = ExecutionContext(
            execution_id="test-execution-001",
            experiment_id="eks-replica-reduction",
            service="eks",
            experiment_name="Replica Reduction",
        )

        context.transition(
            ExecutionState.FAULT_INJECTION_FAILED
        )

        context.start()

        context.precheck = {
            "passed": True,
            "baseline_captured": True,
        }

        context.baseline = {
            "desired_replicas": 10,
            "ready_replicas": 10,
        }

        context.injection = {
            "passed": False,
            "experiment_status": "FAILED",
            "error": "Simulated injection failure",
        }

        context.errors = [
            "Simulated injection failure"
        ]

        context.complete()

        experiment = SimpleNamespace(
            id="eks-replica-reduction",
            service="eks",
            name="Replica Reduction",
            json_file="chaosforge/providers/aws/components/eks/experiments/toolkit/definitions/replica-reduction.json",
            engine="Chaos Toolkit",
            variables={
                "eks_cluster": "mock-cluster",
                "namespace": "default",
                "deployment_name": "test-api",
                "reduced_replicas": 7,
                "wait_seconds": 30,
                "aws_region": "eu-central-1",
            },
            status="FAILED",
            error_message="Simulated injection failure",
        )

        builder = EvidenceBuilder()

        evidence = builder.build(
            context,
            experiment,
        )

        writer = EvidenceArtifactWriter(
            evidence_root=temp_root
        )

        evidence_directory = writer.write(
            evidence
        )

        assert os.path.isdir(
            evidence_directory
        )

        expected_files = [
            "evidence.json",
            "execution.json",
            "experiment.json",
            "target.json",
            "precheck.json",
            "baseline.json",
            "injection.json",
            "validation.json",
            "recovery.json",
            "errors.json",
        ]

        for filename in expected_files:
            path = os.path.join(
                evidence_directory,
                filename,
            )

            assert os.path.isfile(path), (
                f"Missing evidence file: {filename}"
            )

        with open(
            os.path.join(
                evidence_directory,
                "evidence.json",
            ),
            encoding="utf-8",
        ) as file:
            saved_evidence = json.load(file)

        assert (
            saved_evidence["execution"]["execution_id"]
            == "test-execution-001"
        )

        assert (
            saved_evidence["execution"]["state"]
            == "FAULT_INJECTION_FAILED"
        )

        assert (
            saved_evidence["experiment"]["status"]
            == "FAILED"
        )

        assert (
            saved_evidence["injection"]["passed"]
            is False
        )

        assert (
            saved_evidence["target"]["resolved"]["eks_cluster"]
            == "mock-cluster"
        )

        print(
            f"Evidence artifact created: "
            f"{evidence_directory}"
        )

    finally:
        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )

def test_serialize_datetime_none():
    assert EvidenceBuilder._serialize_datetime(None) is None

def test_evidence_artifact_writer_missing_execution_id():
    writer = EvidenceArtifactWriter(evidence_root=tempfile.mkdtemp())

    evidence = {
        "execution": {},  # execution_id intentionally missing
    }

    with pytest.raises(
        ValueError,
        match="Evidence is missing execution_id.",
    ):
        writer.write(evidence)
