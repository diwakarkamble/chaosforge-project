"""
ValidationSession — sequential validation logging for AKS chaos experiments.

Creates a timestamped log folder:  logs/<experiment-id>/<YYYYMMDD_HHMMSS>/
Writes one log file per check, plus a combined session.log.
Runs checks sequentially, printing a tick/cross after each one completes.
"""

import os
import threading
import time
from datetime import datetime, timezone

from chaosforge.common.paths import repository_paths

_LOGS_ROOT = str(repository_paths().logs)


class ValidationSession:
    """
    One ValidationSession per chaos experiment run.

    Usage:
        session = ValidationSession(experiment_id)
        session.start()                         # opens log files
        session.run_checks(checks_dict)         # runs dict of {label: fn} in parallel
        session.stop()                          # closes files, prints summary path
    """

    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_id = experiment_id.replace("/", "-").replace(" ", "_")
        self.log_dir  = os.path.join(_LOGS_ROOT, safe_id, ts)
        self._session_log = None
        self._lock = threading.Lock()
        self._results: dict[str, dict] = {}

    # ── lifecycle ────────────────────────────────────────────────────────────

    @classmethod
    def reopen(cls, experiment_id: str, log_dir: str) -> "ValidationSession":
        """
        Re-attach to an existing log directory created by a prior start() call.
        Opens session.log in append mode so setup/run/cleanup phases all land in
        the same consolidated audit file without creating a second folder.
        Returns None if log_dir does not exist (backward-compat / dry-run paths).
        """
        if not log_dir or not os.path.exists(log_dir):
            return None
        obj = cls.__new__(cls)
        obj.experiment_id = experiment_id
        obj.log_dir = log_dir
        obj._lock = threading.Lock()
        obj._results = {}
        obj._session_log = open(
            os.path.join(log_dir, "session.log"), "a", buffering=1, encoding="utf-8"
        )
        return obj

    def start(self):
        os.makedirs(self.log_dir, exist_ok=True)
        self._session_log = open(
            os.path.join(self.log_dir, "session.log"), "w", buffering=1, encoding="utf-8"
        )
        self._write_header()

    def stop(self):
        if self._session_log:
            self._write_footer()
            self._session_log.close()
            self._session_log = None

    # ── parallel check runner ────────────────────────────────────────────────

    def run_checks(
        self,
        checks: "dict[str, callable]",
        *,
        phase: str = "validation",
        print_live: bool = True,
        advisory_labels: "set[str] | None" = None,
    ) -> "dict[str, dict]":
        """
        Run each check function sequentially, printing a tick/cross after each one.

        checks: {label: callable}  — each callable returns (passed: bool, detail: str)
                                      or raises RuntimeError on hard failure.
        advisory_labels: optional set of check labels that are non-blocking —
                          a failure on one of these is displayed as a distinct
                          warning (⚠, yellow) instead of a hard failure (✘, red),
                          and is excluded from the "N FAILED" summary count so
                          operators aren't alarmed by a check that never actually
                          blocks the experiment. Defaults to None (empty set),
                          which preserves the exact prior display for every
                          existing caller that doesn't pass this parameter.

        Returns the results dict so callers can inspect outcomes.
        """
        from chaosforge.interfaces.cli.interactive.ui.console import console

        advisory_labels = advisory_labels or set()

        if print_live:
            console.print()
            console.print(
                f"[bold bright_cyan]  [{phase.upper()}][/bold bright_cyan] "
                f"Running {len(checks)} check(s)..."
            )

        results: dict[str, dict] = {}

        for label, fn in checks.items():
            if print_live:
                console.print(f"    [dim]→ {label}...[/dim]", end="")

            t0 = time.monotonic()
            import re as _re
            _safe = _re.sub(r'[^a-z0-9_-]', '_', label.lower().replace(' ', '_'))
            check_log_path = os.path.join(self.log_dir, f"{_safe}.log")
            try:
                with open(check_log_path, "w", buffering=1, encoding="utf-8") as cf:
                    cf.write(f"[{datetime.now(timezone.utc).isoformat()}] CHECK: {label}\n")
                    passed, detail = fn()
                    elapsed = time.monotonic() - t0
                    cf.write(f"PASSED={passed}  elapsed={elapsed:.2f}s\n{detail}\n")
                result = {"passed": passed, "detail": detail, "elapsed": elapsed}
            except RuntimeError as exc:
                elapsed = time.monotonic() - t0
                result = {"passed": False, "detail": str(exc), "elapsed": elapsed, "error": True}
                with open(check_log_path, "a", encoding="utf-8") as cf:
                    cf.write(f"ERROR: {exc}\n")
            except Exception as exc:
                elapsed = time.monotonic() - t0
                result = {"passed": False, "detail": f"Unexpected: {exc}", "elapsed": elapsed, "error": True}

            results[label] = result
            self._log_check_result(phase, label, result)

            # Mirror check file contents into session.log so all backend check
            # output is captured in the single consolidated audit file.
            if os.path.exists(check_log_path):
                try:
                    with open(check_log_path, "r", encoding="utf-8") as cf:
                        check_contents = cf.read().strip()
                    if check_contents:
                        self._write(f"  [check detail] {label}")
                        for line in check_contents.splitlines():
                            self._write(f"    {line}")
                except Exception:
                    pass

            if print_live:
                is_advisory_fail = (not result["passed"]) and (label in advisory_labels)
                if is_advisory_fail:
                    icon, color = "[bold yellow]⚠[/bold yellow]", "yellow"
                elif result["passed"]:
                    icon, color = "[bold green]✔[/bold green]", "green"
                else:
                    icon, color = "[bold red]✘[/bold red]", "red"
                suffix = "  [dim](advisory — non-blocking)[/dim]" if is_advisory_fail else ""
                # Overwrite the "→ label..." spinner line with the final tick/cross
                console.print(
                    f"\r    {icon}  [{color}]{label}[/]"
                    f"  [dim]({result['elapsed']:.1f}s)[/dim]{suffix}"
                )
                # Structured metric checks emit multi-line detail (latency tables,
                # request counts, readiness) — print inline so the operator sees
                # the numbers without opening a log file.
                # Single-line detail is already readable from the tick/cross line.
                _EXPANDED_LABELS = {

                    "Baseline HTTP Response Time",
                    "Baseline DNS Resolution",
                    "Baseline DNS Resolution (UDP)",
                    "Baseline Ping RTT",
                    "Pod Restart Baseline",
                    "Baseline File I/O Timing",
                    "Residual I/O Fault Check",
                }
                detail_str = result.get("detail", "")
                if detail_str and label in _EXPANDED_LABELS and "\n" in detail_str:
                    for dline in detail_str.splitlines():
                        console.print(f"         [dim]{dline}[/dim]")

        self._results.update(results)

        if print_live:
            hard_fail_labels = [
                lbl for lbl, r in results.items()
                if not r["passed"] and lbl not in advisory_labels
            ]
            advisory_fail_labels = [
                lbl for lbl, r in results.items()
                if not r["passed"] and lbl in advisory_labels
            ]
            passed = len(results) - len(hard_fail_labels) - len(advisory_fail_labels)
            failed = len(hard_fail_labels)
            if failed == 0 and not advisory_fail_labels:
                status = "[bold green]ALL PASSED[/bold green]"
            elif failed == 0:
                status = f"[bold green]ALL PASSED[/bold green] [dim]({len(advisory_fail_labels)} advisory)[/dim]"
            else:
                status = f"[bold red]{failed} FAILED[/bold red]"
            console.print(
                f"\n  [dim]Checks complete:[/dim] {status}  "
                f"[dim]({passed}/{len(results)})  → logs/{self.experiment_id.replace('/', '-')}/[/dim]"
            )

        return results

    # ── log helpers ─────────────────────────────────────────────────────────

    def _write(self, line: str):
        with self._lock:
            if self._session_log:
                self._session_log.write(line + "\n")

    def _write_header(self):
        now = datetime.now(timezone.utc).isoformat()
        self._write("=" * 70)
        self._write("ChaosForge Validation Session")
        self._write(f"Experiment : {self.experiment_id}")
        self._write(f"Started    : {now}")
        self._write(f"Log dir    : {self.log_dir}")
        self._write("=" * 70)

    def _write_footer(self):
        now     = datetime.now(timezone.utc).isoformat()
        passed  = sum(1 for r in self._results.values() if r.get("passed"))
        total   = len(self._results)
        self._write("")
        self._write("=" * 70)
        self._write(f"Session complete  {now}")
        self._write(f"Total checks: {total}  Passed: {passed}  Failed: {total - passed}")
        self._write("=" * 70)

    def _log_check_result(self, phase: str, label: str, result: dict):
        ts      = datetime.now(timezone.utc).isoformat()
        status  = "PASS" if result["passed"] else "FAIL"
        elapsed = result.get("elapsed", 0)
        detail  = result.get("detail", "")
        self._write(
            f"[{ts}] [{phase.upper():<12}] [{status}] {label:<40}  {elapsed:.2f}s"
            + (f"\n          └─ {detail}" if detail else "")
        )

    def log_event(self, phase: str, message: str):
        """Write a free-form event (e.g. 'Fault injected', 'Polling started') to session.log."""
        ts = datetime.now(timezone.utc).isoformat()
        self._write(f"[{ts}] [{phase.upper():<12}] {message}")
