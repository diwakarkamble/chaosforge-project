"""
Regression test for a real bug found via a live cluster + campaign report
(campaign-report-20260921-113959.txt): the "IOChaos CRD Cleaned Up"
post-check kept failing because the underlying IOChaos custom resource was
never actually deleted from the cluster (confirmed live: a CR from the
report's exact run timestamp was still present in the chaos-testing
namespace minutes after the experiment finished, with
status.conditions AllRecovered=True — the fault itself had stopped, but the
CR object was simply never removed).

Root cause: cleanup_experiment()'s explicit best-effort CRD-cleanup map
(_MESH_CRD_KINDS) already deletes stale dnschaos/httpchaos/timechaos/
podchaos resources during rollback, precisely because Azure Chaos Studio's
own cleanup is not always reliable/fast enough — but "aks-io-latency" and
"aks-io-errors" (IOChaos) were missing from that map entirely, so IOChaos
depended solely on Azure Studio's cleanup, and any time that was slow or
incomplete the CR was left behind indefinitely.

The fix adds both IOChaos experiment IDs to _MESH_CRD_KINDS -> "iochaos",
so cleanup_experiment() explicitly attempts to delete stale IOChaos CRs
during rollback, the same way it already does for the other experiment
types.
"""

from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import chaosforge.providers.azure.components.aks.experiments.chaos_studio.executor as azure_aks_actions


def test_cleanup_experiment_explicitly_deletes_stale_iochaos_crds():
    fake_session_instance = MagicMock()
    fake_session_instance.run_checks.return_value = {}

    mock_kubectl = MagicMock(
        return_value=CompletedProcess([], 0, stdout="", stderr="")
    )

    with patch.object(azure_aks_actions, "_kubectl", mock_kubectl), \
         patch.object(azure_aks_actions, "_load_state", return_value={"_setup_complete": True}), \
         patch.object(azure_aks_actions, "_reopen_session", return_value=None), \
         patch.object(azure_aks_actions, "ValidationSession",
                       return_value=fake_session_instance), \
         patch.object(azure_aks_actions, "build_post_experiment_checks",
                       return_value={}):
        azure_aks_actions.cleanup_experiment(
            "aks-io-latency", "ctx", "app-ns", "pvc-app",
            volume_path="/data",
        )

    iochaos_delete_calls = [
        call for call in mock_kubectl.call_args_list
        if call.args[:2] == ("delete", "iochaos")
    ]
    assert len(iochaos_delete_calls) == 1
    assert "--all" in iochaos_delete_calls[0].args
    assert iochaos_delete_calls[0].kwargs.get("context") == "ctx"
