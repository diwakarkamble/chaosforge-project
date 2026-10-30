from unittest.mock import patch

from chaosforge.engines.chaos_mesh.chaos_mesh_installer import (
    ChaosMeshInstaller,
    ChaosMeshInstallResult,
    ChaosMeshReleaseInfo,
    HelmReleaseStatus,
)


def test_release_info_reads_installed_chart_version():
    installer = ChaosMeshInstaller()
    result = type("Result", (), {
        "returncode": 0,
        "stdout": '{"chart":"chaos-mesh-2.8.7"}',
        "stderr": "",
    })()
    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        return_value=result,
    ) as run:
        info = installer.release_info()

    assert info == ChaosMeshReleaseInfo(
        HelmReleaseStatus.INSTALLED,
        "Chaos Mesh Helm release is installed.",
        "2.8.7",
    )
    assert "--output" in run.call_args.args[0]


def test_release_info_supports_nested_helm_chart_metadata_and_rejects_wrong_chart():
    installer = ChaosMeshInstaller()
    nested = type("Result", (), {
        "returncode": 0,
        "stdout": '{"chart":{"metadata":{"name":"chaos-mesh","version":"2.8.7"}}}',
        "stderr": "",
    })()
    wrong = type("Result", (), {
        "returncode": 0,
        "stdout": '{"chart":"other-chart-1.0.0"}',
        "stderr": "",
    })()
    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        side_effect=[nested, wrong],
    ):
        assert installer.release_info().version == "2.8.7"
        assert installer.release_info().status == HelmReleaseStatus.ERROR


def test_upgrade_reuses_values_and_pins_version():
    installer = ChaosMeshInstaller()
    successful = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    with patch.object(installer, "_ensure_repository"), patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        return_value=successful,
    ) as run:
        result = installer.upgrade()

    command = run.call_args.args[0]
    assert result.status == "UPGRADED"
    assert "--reuse-values" in command
    assert command[command.index("--version") + 1] == "2.8.7"


def test_helm_available():
    installer = ChaosMeshInstaller()

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.shutil.which",
        return_value="helm",
    ):
        assert installer.is_helm_available() is True


def test_helm_not_available():
    installer = ChaosMeshInstaller()

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.shutil.which",
        return_value=None,
    ):
        assert installer.is_helm_available() is False


def test_existing_release_is_not_reinstalled():
    installer = ChaosMeshInstaller()

    with patch.object(installer, "is_helm_available", return_value=True), \
         patch.object(
             installer,
             "release_status",
             return_value=(
                 HelmReleaseStatus.INSTALLED,
                 "Chaos Mesh Helm release is installed.",
             ),
         ), \
         patch.object(installer, "install") as install:

        result = installer.ensure_installed()

    assert result.status == "READY"
    assert result.installed is False
    install.assert_not_called()


def test_missing_helm_blocks_installation():
    installer = ChaosMeshInstaller()

    with patch.object(installer, "is_helm_available", return_value=False):
        result = installer.ensure_installed()

    assert result.status == "BLOCKED"
    assert "Helm CLI" in result.message
    assert result.installed is False


def test_missing_release_triggers_installation():
    installer = ChaosMeshInstaller()

    expected = {
        "status": "INSTALLED",
        "message": "installed",
        "installed": True,
    }

    with patch.object(installer, "is_helm_available", return_value=True), \
         patch.object(
             installer,
             "release_status",
             return_value=(
                 HelmReleaseStatus.ABSENT,
                 "Chaos Mesh Helm release is not installed.",
             ),
         ), \
         patch.object(
             installer,
             "install",
             return_value=ChaosMeshInstallResult(**expected),
         ) as install:

        result = installer.ensure_installed()

    assert result.status == "INSTALLED"
    assert result.installed is True
    install.assert_called_once()


def test_helm_status_error_blocks_installation():
    installer = ChaosMeshInstaller()

    with patch.object(installer, "is_helm_available", return_value=True), \
         patch.object(
             installer,
             "release_status",
             return_value=(
                 HelmReleaseStatus.ERROR,
                 "Unable to determine release status.",
             ),
         ), \
         patch.object(installer, "install") as install:

        result = installer.ensure_installed()

    assert result.status == "BLOCKED"
    assert "Unable to determine release status" in result.message
    assert result.installed is False
    install.assert_not_called()


def test_install_builds_expected_helm_command():
    installer = ChaosMeshInstaller(
        version="2.8.7",
        kubeconfig_path="C:\\temp\\chaosforge-eks.config",
        kube_context="arn:aws:eks:eu-central-1:123456789012:cluster/Chaos-POC-v2",
    )

    repo_commands = [
        type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "chaos-mesh",
                "stderr": "",
            },
        )(),
        type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        )(),
    ]

    install_result = type(
        "Result",
        (),
        {
            "returncode": 0,
            "stdout": "deployed",
            "stderr": "",
        },
    )()

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        side_effect=repo_commands + [install_result],
    ) as run:

        result = installer.install()

    assert result.status == "INSTALLED"
    assert result.installed is True

    commands = [call.args[0] for call in run.call_args_list]

    assert commands[0] == [
        "helm",
        "repo",
        "list",
        "--kubeconfig",
        "C:\\temp\\chaosforge-eks.config",
        "--kube-context",
        "arn:aws:eks:eu-central-1:123456789012:cluster/Chaos-POC-v2",
    ]

    assert commands[1] == [
        "helm",
        "repo",
        "update",
        "chaos-mesh",
        "--kubeconfig",
        "C:\\temp\\chaosforge-eks.config",
        "--kube-context",
        "arn:aws:eks:eu-central-1:123456789012:cluster/Chaos-POC-v2",
    ]

    install_command = commands[2]

    assert install_command[:8] == [
        "helm",
        "upgrade",
        "--install",
        "chaos-mesh",
        "chaos-mesh/chaos-mesh",
        "--namespace",
        "chaos-mesh",
        "--create-namespace",
    ]

    assert "--version" in install_command
    assert "2.8.7" in install_command
    assert "chaosDaemon.runtime=containerd" in install_command
    assert (
        "chaosDaemon.socketPath=/run/containerd/containerd.sock"
        in install_command
    )
    assert "--wait" in install_command
    assert "--timeout" in install_command

    assert install_command[-4:] == [
        "--kubeconfig",
        "C:\\temp\\chaosforge-eks.config",
        "--kube-context",
        "arn:aws:eks:eu-central-1:123456789012:cluster/Chaos-POC-v2",
    ]


def test_install_without_kubeconfig_does_not_add_kubernetes_options():
    installer = ChaosMeshInstaller(version="2.8.7")

    repo_commands = [
        type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "chaos-mesh",
                "stderr": "",
            },
        )(),
        type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        )(),
    ]

    install_result = type(
        "Result",
        (),
        {
            "returncode": 0,
            "stdout": "deployed",
            "stderr": "",
        },
    )()

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        side_effect=repo_commands + [install_result],
    ) as run:

        result = installer.install()

    assert result.status == "INSTALLED"

    commands = [call.args[0] for call in run.call_args_list]

    for command in commands:
        assert "--kubeconfig" not in command
        assert "--kube-context" not in command


def test_install_failure_returns_blocked():
    installer = ChaosMeshInstaller()

    repo_list = type(
        "Result",
        (),
        {
            "returncode": 0,
            "stdout": "chaos-mesh",
            "stderr": "",
        },
    )()

    repo_update = type(
        "Result",
        (),
        {
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        },
    )()

    helm_failure = type(
        "Result",
        (),
        {
            "returncode": 1,
            "stdout": "",
            "stderr": "connection refused",
        },
    )()

    with patch(
        "chaosforge.engines.chaos_mesh.chaos_mesh_installer.subprocess.run",
        side_effect=[repo_list, repo_update, helm_failure],
    ):
        result = installer.install()

    assert result.status == "BLOCKED"
    assert "connection refused" in result.message
    assert result.installed is False
