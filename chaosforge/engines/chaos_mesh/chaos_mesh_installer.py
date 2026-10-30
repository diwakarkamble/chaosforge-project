from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum

CHAOS_MESH_VERSION = "2.8.7"


class HelmReleaseStatus(str, Enum):
    INSTALLED = "INSTALLED"
    ABSENT = "ABSENT"
    ERROR = "ERROR"


@dataclass
class ChaosMeshInstallResult:
    status: str
    message: str
    installed: bool = False


@dataclass
class ChaosMeshReleaseInfo:
    status: HelmReleaseStatus
    message: str
    version: str | None = None


class ChaosMeshInstaller:
    """
    Installs Chaos Mesh into an EKS cluster using Helm.

    This class is intentionally separate from ChaosMeshPreflight.
    Preflight is read-only; this class performs installation only when
    Chaos Mesh is confirmed to be absent.
    """

    RELEASE_NAME = "chaos-mesh"
    CHART = "chaos-mesh/chaos-mesh"
    NAMESPACE = "chaos-mesh"
    REPOSITORY_NAME = "chaos-mesh"
    REPOSITORY_URL = "https://charts.chaos-mesh.org"
    DEFAULT_VERSION = CHAOS_MESH_VERSION

    def __init__(
        self,
        version: str | None = None,
        runtime: str = "containerd",
        socket_path: str = "/run/containerd/containerd.sock",
        timeout: str = "10m",
        kubeconfig_path: str | None = None,
        kube_context: str | None = None,
        release_name: str | None = None,
        namespace: str | None = None,
    ) -> None:
        self.version = version or self.DEFAULT_VERSION
        self.runtime = runtime
        self.socket_path = socket_path
        self.timeout = timeout
        self.kubeconfig_path = kubeconfig_path
        self.kube_context = kube_context
        self.release_name = release_name or self.RELEASE_NAME
        self.namespace = namespace or self.NAMESPACE

    def is_helm_available(self) -> bool:
        """Return True when the Helm CLI is available."""
        return shutil.which("helm") is not None

    def _helm_command(self, *args: str) -> list[str]:
        """Build a Helm command using the configured Kubernetes context."""
        command = ["helm", *args]

        if self.kubeconfig_path:
            command.extend(["--kubeconfig", self.kubeconfig_path])

        if self.kube_context:
            command.extend(["--kube-context", self.kube_context])

        return command

    def release_status(self) -> tuple[HelmReleaseStatus, str]:
        info = self.release_info()
        return info.status, info.message

    def release_info(self) -> ChaosMeshReleaseInfo:
        """
        Determine whether the Chaos Mesh Helm release exists.

        Returns:
            INSTALLED: release exists.
            ABSENT: Helm confirms that the release does not exist.
            ERROR: Helm could not determine the release state.
        """
        try:
            result = subprocess.run(
                self._helm_command(
                    "status", self.release_name,
                    "--namespace", self.namespace,
                    "--output", "json",
                ),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return ChaosMeshReleaseInfo(
                HelmReleaseStatus.ERROR,
                f"Unable to determine Chaos Mesh Helm release status: {exc}",
            )

        if result.returncode == 0:
            try:
                import json

                chart = json.loads(result.stdout).get("chart", "")
                if isinstance(chart, str):
                    prefix = "chaos-mesh-"
                    chart_name = "chaos-mesh" if chart.startswith(prefix) else chart
                    version = chart.removeprefix(prefix) if chart.startswith(prefix) else None
                elif isinstance(chart, dict):
                    metadata = chart.get("metadata") or {}
                    chart_name = metadata.get("name", "")
                    version = metadata.get("version")
                else:
                    chart_name, version = "", None
            except (ValueError, TypeError, AttributeError):
                if "status:" in result.stdout.lower():
                    chart_name, version = "chaos-mesh", None
                else:
                    chart_name, version = "", None
            if chart_name != "chaos-mesh":
                return ChaosMeshReleaseInfo(
                    HelmReleaseStatus.ERROR,
                    f"The Helm release named '{self.release_name}' does not use the Chaos Mesh chart.",
                )
            return ChaosMeshReleaseInfo(
                HelmReleaseStatus.INSTALLED,
                "Chaos Mesh Helm release is installed.",
                version,
            )

        output = (
            f"{result.stdout}\n{result.stderr}"
        ).strip().lower()

        not_found_indicators = (
            "release: not found",
            "release not found",
            "not found",
        )

        if any(indicator in output for indicator in not_found_indicators):
            return ChaosMeshReleaseInfo(
                HelmReleaseStatus.ABSENT,
                "Chaos Mesh Helm release is not installed.",
            )

        return ChaosMeshReleaseInfo(
            HelmReleaseStatus.ERROR,
            (
                "Unable to determine Chaos Mesh Helm release status"
                + (f": {output}" if output else ".")
            ),
        )

    def is_release_installed(self) -> bool:
        """Return True only when the Helm release definitely exists."""
        status, _ = self.release_status()
        return status == HelmReleaseStatus.INSTALLED

    def ensure_installed(self) -> ChaosMeshInstallResult:
        """
        Install Chaos Mesh only when Helm confirms that the release
        is absent.
        """
        if not self.is_helm_available():
            return ChaosMeshInstallResult(
                status="BLOCKED",
                message="Helm CLI is not installed or not available in PATH.",
            )

        release_status, message = self.release_status()

        if release_status == HelmReleaseStatus.INSTALLED:
            return ChaosMeshInstallResult(
                status="READY",
                message=message,
                installed=False,
            )

        if release_status == HelmReleaseStatus.ERROR:
            return ChaosMeshInstallResult(
                status="BLOCKED",
                message=message,
                installed=False,
            )

        return self.install()

    def install(self) -> ChaosMeshInstallResult:
        """Install the configured Chaos Mesh Helm release."""
        try:
            self._ensure_repository()

            command = self._helm_command(
                "upgrade",
                "--install",
                self.release_name,
                self.CHART,
                "--namespace",
                self.namespace,
                "--create-namespace",
                "--version",
                self.version,
                "--set",
                f"chaosDaemon.runtime={self.runtime}",
                "--set",
                f"chaosDaemon.socketPath={self.socket_path}",
                "--wait",
                "--timeout",
                self.timeout,
            )

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                details = result.stderr.strip() or result.stdout.strip()

                return ChaosMeshInstallResult(
                    status="BLOCKED",
                    message=(
                        "Chaos Mesh Helm installation failed"
                        + (f": {details}" if details else ".")
                    ),
                )

            return ChaosMeshInstallResult(
                status="INSTALLED",
                message=(
                    f"Chaos Mesh {self.version} installed successfully "
                    f"in namespace '{self.namespace}'."
                ),
                installed=True,
            )

        except (OSError, RuntimeError) as exc:
            return ChaosMeshInstallResult(
                status="BLOCKED",
                message=f"Chaos Mesh installation failed: {exc}",
            )

    def upgrade(self) -> ChaosMeshInstallResult:
        """Upgrade an existing release to the pinned version without downgrading."""
        try:
            self._ensure_repository()
            result = subprocess.run(
                self._helm_command(
                    "upgrade", self.release_name, self.CHART,
                    "--namespace", self.namespace,
                    "--version", self.version,
                    "--reuse-values", "--wait", "--timeout", self.timeout,
                ),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                details = result.stderr.strip() or result.stdout.strip()
                return ChaosMeshInstallResult(
                    "BLOCKED",
                    "Chaos Mesh Helm upgrade failed"
                    + (f": {details}" if details else "."),
                )
            return ChaosMeshInstallResult(
                "UPGRADED",
                f"Chaos Mesh upgraded to {self.version} successfully.",
                installed=True,
            )
        except (OSError, RuntimeError) as exc:
            return ChaosMeshInstallResult(
                "BLOCKED", f"Chaos Mesh upgrade failed: {exc}"
            )

    def _ensure_repository(self) -> None:
        """Ensure the Chaos Mesh Helm repository is available."""
        repo_list = subprocess.run(
            self._helm_command("repo", "list"),
            capture_output=True,
            text=True,
            check=False,
        )

        if self.REPOSITORY_NAME not in repo_list.stdout:
            result = subprocess.run(
                self._helm_command(
                    "repo",
                    "add",
                    self.REPOSITORY_NAME,
                    self.REPOSITORY_URL,
                ),
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                details = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(
                    "Unable to add Chaos Mesh Helm repository"
                    + (f": {details}" if details else ".")
                )

        result = subprocess.run(
            self._helm_command(
                "repo",
                "update",
                self.REPOSITORY_NAME,
            ),
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                "Unable to update Chaos Mesh Helm repository"
                + (f": {details}" if details else ".")
            )
