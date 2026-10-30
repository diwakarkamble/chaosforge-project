import re
import threading
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from threading import Thread

from chaosforge.catalog import ExperimentCatalog
from chaosforge.common.execution_mode import set_web_execution
from chaosforge.interfaces.web.log_manager import get_log_manager, log_manager
from chaosforge.storage.campaign_history import CampaignHistoryStore

_TERMINAL_CONTROL = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_sessions = {"aws": [], "azure": []}
_sessions_lock = threading.Lock()
_TARGET_VARIABLES = (
    "resource_id",
    "bucket_name",
    "instance_id",
    "instance_ids",
    "lambda_name",
    "table_name",
    "topic_arn",
    "ecs_cluster",
    "db_instance_identifier",
    "cache_name",
    "replication_group_id",
    "cache_cluster_id",
    "serverless_cache_name",
    "redis_name",
    "function_name",
    "app_name",
    "target_arn",
)


def experiment_target(experiment):
    """Return the non-secret target variable used to bind Web E2E execution."""
    variables = getattr(experiment, "variables", {}) or {}
    if getattr(experiment, "service", "") == "aks":
        # AKS target fields are not generic resource selectors. Keep the full
        # Kubernetes target so historical runs cannot all match an empty target.
        target_fields = (
            "subscription_id", "resource_group", "aks_context", "namespace",
            "target_mode", "pod", "deployment", "target_node", "target_zone",
        )
        target = "|".join(
            f"{name}={variables[name]}" for name in target_fields if variables.get(name)
        )
        if target:
            return {"variable": "aks_target", "value": target}
    metadata = ExperimentCatalog().get_experiment(
        getattr(experiment, "service", ""), getattr(experiment, "id", "")
    )
    if metadata:
        for field in metadata.get("inputs", []):
            if field.get("parent") or field.get("type") not in {
                "aws_resource",
                "azure_component_resource",
                "aws_fis_template",
            }:
                continue
            if value := variables.get(field["name"]):
                return {"variable": field["name"], "value": str(value)}
    for name in _TARGET_VARIABLES:
        if value := variables.get(name):
            return {"variable": name, "value": str(value)}
    return {}


def execution_sessions(cloud):
    with _sessions_lock:
        return [dict(session) for session in _sessions.get(cloud, [])]


def execution_session(cloud, run_id):
    with _sessions_lock:
        return next(
            (dict(session) for session in _sessions.get(cloud, []) if session["id"] == run_id),
            None,
        )


def _update_session(cloud, run_id, **values):
    with _sessions_lock:
        for session in _sessions.get(cloud, []):
            if session["id"] == run_id:
                session.update(values)
                return


def _update_experiment_session(cloud, run_id, experiment, **values):
    with _sessions_lock:
        for session in _sessions.get(cloud, []):
            if session["id"] == run_id:
                session["experiments"][str(id(experiment))].update(values)
                return


class _WebLogStream:
    """Send line-oriented lifecycle output to the browser execution log."""

    def __init__(self, logs=None):
        self.buffer = ""
        self.logs = logs

    def write(self, value):
        # Rich emits ANSI styles and live-terminal redraw controls. Browsers do
        # not interpret those controls, so keep only the readable text.
        clean = _TERMINAL_CONTROL.sub("", str(value)).replace("\r", "")
        self.buffer += clean
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            (self.logs or log_manager).append(line)
        return len(str(value))

    def flush(self):
        """Accept per-character subprocess flushes without fragmenting lines."""

    def finish(self):
        if self.buffer:
            (self.logs or log_manager).append(self.buffer)
            self.buffer = ""


class ExecutionAlreadyRunning(RuntimeError):
    def __init__(self, cloud, run_id):
        self.cloud = cloud
        self.run_id = run_id
        super().__init__(f"A {cloud.upper()} campaign is already running.")


class WebExecution:
    def __init__(self, cloud="aws", history=None):

        self.cloud = cloud if cloud in {"aws", "azure"} else "aws"
        self.campaign = None
        self.thread = None
        self.run_id = None
        self.history = history or CampaignHistoryStore()
        self._admission_lock = threading.Lock()

    @property
    def logs(self):
        return log_manager if self.cloud == "aws" else get_log_manager(self.cloud)

    def _session_snapshot(self):
        return {
            "logs": self.logs.get_logs(),
            "progress": {
                "current": self.logs.current,
                "total": self.logs.total,
                "experiment": self.logs.current_experiment,
                "running": self.logs.running,
                "finished": self.logs.finished,
            },
        }

    def start(self, campaign=None, on_experiment_complete=None):

        print(">>> WEB EXECUTION STARTED <<<")

        with self._admission_lock:
            if self.run_id is not None:
                raise ExecutionAlreadyRunning(self.cloud, self.run_id)
            accepted_campaign = deepcopy(campaign if campaign is not None else self.campaign)
            if accepted_campaign is None:
                raise ValueError("No campaign selected.")

            self.logs.clear()

            self.logs.running = True
            run_id = None
            try:
                run_id = self.history.start_execution(accepted_campaign, "web")
                self.campaign = accepted_campaign
                self.run_id = run_id
                with _sessions_lock:
                    _sessions[self.cloud].insert(
                        0,
                        {
                            "id": run_id,
                            "campaign_name": getattr(accepted_campaign, "name", "Default Campaign"),
                            "status": "RUNNING",
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "completed_at": None,
                            "logs": [],
                            "progress": {},
                            "experiments": {
                                str(id(experiment)): {
                                    "name": experiment.name,
                                    "service": experiment.service,
                                    "experiment_id": experiment.id,
                                    "fis_service_id": experiment.variables.get("service_id", "") if experiment.service == "fis" else "",
                                    "fis_experiment_id": experiment.variables.get("experiment_id", "") if experiment.service == "fis" else "",
                                    "target": experiment_target(experiment),
                                    "status": "PENDING",
                                    "log_start": None,
                                }
                                for experiment in getattr(accepted_campaign, "experiments", [])
                            }
                        },
                    )

                # Keep this worker alive so an active lifecycle can complete rollback.
                self.thread = Thread(
                    target=self.execute,
                    args=(accepted_campaign, run_id, on_experiment_complete),
                    daemon=False,
                )
                self.thread.start()
            except Exception:
                self.logs.running = False
                try:
                    if run_id is not None:
                        self.history.finish_execution(run_id, accepted_campaign, "FAILED")
                        _update_session(
                            self.cloud,
                            run_id,
                            status="FAILED",
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                finally:
                    self.campaign = None
                    self.run_id = None
                    self.thread = None
                raise
            return run_id

    def wait_for_completion(self):
        """Wait for an active lifecycle execution to finish its cleanup."""

        if self.thread is not None and self.thread.is_alive():
            self.logs.append("Shutdown requested; waiting for active experiment rollback.")
            self.thread.join()

    def execute(self, campaign=None, run_id=None, on_experiment_complete=None):

        set_web_execution(True)
        report_file = None
        campaign = campaign if campaign is not None else self.campaign
        run_id = run_id if run_id is not None else self.run_id
        try:
            self.logs.append("")
            self.logs.append("=" * 60)
            self.logs.append("ChaosForge Campaign Started")
            self.logs.append("=" * 60)
            self.logs.append("")

            if campaign is None:
                raise ValueError("No campaign selected.")
            if run_id is None:
                run_id = self.history.start_execution(campaign, "web")

            from chaosforge.interfaces.web.runner import WebExperimentRunner

            runner = WebExperimentRunner(
                logs=self.logs,
                before_experiment=lambda _index, experiment: _update_experiment_session(
                    self.cloud,
                    run_id,
                    experiment,
                    status="RUNNING",
                    log_start=len(self.logs.get_logs()),
                ),
                after_experiment=lambda _index, experiment: self._after_experiment(
                    run_id, experiment, on_experiment_complete
                ),
            )

            stream = _WebLogStream(self.logs)
            with redirect_stdout(stream), redirect_stderr(stream):
                result = runner.execute_campaign(campaign)
            stream.finish()

            self.logs.append("")
            self.logs.append("=" * 60)
            self.logs.append(f"Campaign Completed: {result.status}")
            self.logs.append("=" * 60)
            status = result.status
            report_file = runner.report_file

        except Exception as ex:
            self.logs.append("")
            self.logs.append("=" * 60)
            self.logs.append("Campaign Failed")
            self.logs.append(str(ex))
            self.logs.append("=" * 60)
            status = "FAILED"
            report_file = None

        finally:
            set_web_execution(False)
            self.logs.running = False
            self.logs.finished = True
            snapshot = self._session_snapshot()
            if run_id is not None and campaign is not None:
                self.history.finish_execution(
                    run_id,
                    campaign,
                    status,
                    logs=snapshot["logs"],
                    report_path=report_file,
                )
            _update_session(
                self.cloud,
                run_id,
                status=status,
                completed_at=datetime.now(timezone.utc).isoformat(),
                **snapshot,
            )
            with self._admission_lock:
                if self.run_id == run_id:
                    self.campaign = None
                    self.run_id = None

    def _after_experiment(self, run_id, experiment, on_experiment_complete):
        _update_experiment_session(self.cloud, run_id, experiment, status=experiment.status)
        if on_experiment_complete is None:
            return
        try:
            on_experiment_complete(experiment)
        except Exception as exc:  # noqa: BLE001 - outcome persistence must not hide execution status.
            self.logs.append(f"Could not update the active campaign outcome: {exc}")


executor = WebExecution()
executors = {"aws": executor}


def get_executor(cloud=None):
    cloud = cloud if cloud in {"aws", "azure"} else "aws"
    if cloud not in executors:
        executors[cloud] = WebExecution(cloud)
    return executors[cloud]
