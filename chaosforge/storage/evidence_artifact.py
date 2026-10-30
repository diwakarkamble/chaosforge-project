import json
import os
from typing import Any

from chaosforge.common.paths import repository_paths

EVIDENCE_ROOT = str(repository_paths().evidence)


class EvidenceArtifactWriter:
    """
    Persists a structured ChaosForge evidence record
    to the local filesystem.

    Each execution receives its own evidence directory.

    The evidence directory contains:
        - artifact.json
        - evidence.json
        - execution.json
        - experiment.json
        - target.json
        - precheck.json
        - baseline.json
        - injection.json
        - validation.json
        - recovery.json
        - errors.json
        - logs/
        - events/

    artifact.json is the canonical client-facing evidence artifact.
    evidence.json is retained for backward compatibility.
    """

    def __init__(
        self,
        evidence_root: str | None = None,
    ):
        self.evidence_root = (
            evidence_root
            if evidence_root is not None
            else EVIDENCE_ROOT
        )

    def write(
        self,
        evidence: dict[str, Any],
    ) -> str:
        """
        Write an evidence record to disk.

        Returns:
            Path to the execution evidence directory.
        """

        execution = evidence.get(
            "execution",
            {},
        )

        execution_id = execution.get(
            "execution_id"
        )

        if not execution_id:
            raise ValueError(
                "Evidence is missing execution_id."
            )

        execution_dir = os.path.join(
            self.evidence_root,
            execution_id,
        )

        os.makedirs(
            execution_dir,
            exist_ok=True,
        )

        # ---------------------------------------------------------
        # CANONICAL EVIDENCE ARTIFACT
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "artifact.json",
            ),
            evidence,
        )

        # ---------------------------------------------------------
        # BACKWARD-COMPATIBLE EVIDENCE FILE
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "evidence.json",
            ),
            evidence,
        )

        # ---------------------------------------------------------
        # EXECUTION
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "execution.json",
            ),
            evidence.get(
                "execution",
                {},
            ),
        )

        # ---------------------------------------------------------
        # EXPERIMENT
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "experiment.json",
            ),
            evidence.get(
                "experiment",
                {},
            ),
        )

        # ---------------------------------------------------------
        # TARGET
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "target.json",
            ),
            evidence.get(
                "target",
                {},
            ),
        )

        # ---------------------------------------------------------
        # PRECHECK
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "precheck.json",
            ),
            evidence.get(
                "precheck",
                {},
            ),
        )

        # ---------------------------------------------------------
        # BASELINE
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "baseline.json",
            ),
            evidence.get(
                "baseline",
                {},
            ),
        )

        # ---------------------------------------------------------
        # FAULT INJECTION
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "injection.json",
            ),
            evidence.get(
                "injection",
                {},
            ),
        )

        # ---------------------------------------------------------
        # VALIDATION
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "validation.json",
            ),
            evidence.get(
                "validation",
                {},
            ),
        )

        # ---------------------------------------------------------
        # RECOVERY
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "recovery.json",
            ),
            evidence.get(
                "recovery",
                {},
            ),
        )

        # ---------------------------------------------------------
        # ERRORS
        # ---------------------------------------------------------

        self._write_json(
            os.path.join(
                execution_dir,
                "errors.json",
            ),
            evidence.get(
                "errors",
                [],
            ),
        )

        # ---------------------------------------------------------
        # LOGS / EVENTS
        #
        # These directories are created now so the evidence
        # bundle has a stable structure. Provider-specific
        # logs/events will be populated in later steps.
        # ---------------------------------------------------------

        os.makedirs(
            os.path.join(
                execution_dir,
                "logs",
            ),
            exist_ok=True,
        )

        os.makedirs(
            os.path.join(
                execution_dir,
                "events",
            ),
            exist_ok=True,
        )

        return execution_dir

    @staticmethod
    def _write_json(
        path: str,
        data: Any,
    ) -> None:
        """
        Write JSON data using UTF-8 encoding.
        """

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

            file.write("\n")
