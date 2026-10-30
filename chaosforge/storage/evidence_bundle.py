import os
import zipfile

from chaosforge.common.paths import repository_paths


class EvidenceBundleWriter:
    """
    Creates a ZIP archive from a persisted ChaosForge
    evidence directory.
    """

    def __init__(self, evidence_root=None):
        if evidence_root is None:
            evidence_root = str(repository_paths().evidence)

        self.evidence_root = evidence_root

    def create_bundle(self, execution_id):
        """
        Create a ZIP evidence bundle for an execution.

        Returns:
            Path to the generated ZIP file.
        """

        execution_dir = os.path.join(
            self.evidence_root,
            execution_id,
        )

        if not os.path.isdir(execution_dir):
            raise FileNotFoundError(
                f"Evidence directory not found: "
                f"{execution_dir}"
            )

        bundle_path = os.path.join(
            self.evidence_root,
            f"{execution_id}.zip",
        )

        with zipfile.ZipFile(
            bundle_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as bundle:

            for root, _, files in os.walk(
                execution_dir
            ):
                for filename in files:

                    file_path = os.path.join(
                        root,
                        filename,
                    )

                    archive_path = os.path.relpath(
                        file_path,
                        self.evidence_root,
                    )

                    bundle.write(
                        file_path,
                        archive_path,
                    )

        return bundle_path
