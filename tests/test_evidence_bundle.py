import json
import os
import shutil
import tempfile

import pytest

from chaosforge.storage.evidence_bundle import EvidenceBundleWriter


def test_evidence_bundle_writer():
    temp_root = tempfile.mkdtemp()

    try:
        execution_id = "test-execution-001"

        execution_dir = os.path.join(
            temp_root,
            execution_id,
        )

        os.makedirs(
            execution_dir,
            exist_ok=True,
        )

        files = {
            "evidence.json": {
                "evidence_version": "1.0",
                "execution": {
                    "execution_id": execution_id,
                    "state": "FAULT_INJECTION_FAILED",
                },
            },
            "execution.json": {
                "execution_id": execution_id,
                "state": "FAULT_INJECTION_FAILED",
            },
            "experiment.json": {
                "id": "eks-replica-reduction",
                "status": "FAILED",
            },
            "errors.json": [
                "Simulated experiment failure"
            ],
        }

        for filename, data in files.items():
            with open(
                os.path.join(
                    execution_dir,
                    filename,
                ),
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    data,
                    file,
                    indent=2,
                )

        writer = EvidenceBundleWriter(
            evidence_root=temp_root
        )

        bundle_path = writer.create_bundle(
            execution_id
        )

        assert os.path.isfile(
            bundle_path
        )

        assert bundle_path.endswith(
            f"{execution_id}.zip"
        )

        import zipfile

        with zipfile.ZipFile(
            bundle_path,
            "r",
        ) as bundle:

            names = bundle.namelist()

        expected_files = {
            f"{execution_id}/evidence.json",
            f"{execution_id}/execution.json",
            f"{execution_id}/experiment.json",
            f"{execution_id}/errors.json",
        }

        assert expected_files.issubset(
            set(names)
        )

        print(
            f"Evidence bundle created: "
            f"{bundle_path}"
        )

    finally:
        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )

def test_evidence_bundle_writer_default_root():
    writer = EvidenceBundleWriter()

    expected_root = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        ),
        "runtime",
        "evidence",
    )

    assert writer.evidence_root == expected_root


def test_evidence_bundle_writer_missing_execution_directory():
    temp_root = tempfile.mkdtemp()

    try:
        writer = EvidenceBundleWriter(
            evidence_root=temp_root
        )

        with pytest.raises(
            FileNotFoundError,
            match="Evidence directory not found",
        ):
            writer.create_bundle(
                "missing-execution"
            )

    finally:
        shutil.rmtree(
            temp_root,
            ignore_errors=True,
        )
