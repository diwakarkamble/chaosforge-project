"""
PhaseUI — buffered, phase-structured output for chaos experiment runs.

Replaces the raw print() stream from azure_aks_actions with clearly delineated
phases that each end with a completion tick:

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  PHASE 1 › Setup                                                        │
  │    [dim buffered log lines...]                                           │
  │  ✔  Setup complete                                             (2.14s)   │
  └─────────────────────────────────────────────────────────────────────────┘

Usage:
    ui = PhaseUI(experiment_id)
    with ui.phase("Setup"):
        ui.step("Registering Microsoft.Chaos provider...")
        # ... do work ...
        ui.step("AKS Chaos Studio target registered")
    # phase block auto-closes with ✔ on clean exit, ✘ on exception
"""

import time
from contextlib import contextmanager

from rich.rule import Rule

from chaosforge.interfaces.cli.interactive.ui.console import console

# ── ANSI/Rich colour tokens ──────────────────────────────────────────────────
_TICK   = "[bold green]✔[/bold green]"
_CROSS  = "[bold red]✘[/bold red]"
_BULLET = "[dim]  ›[/dim]"

# Phase labels shown in the rule headers
_PHASE_LABELS = {
    "setup":            "PHASE 1 › Setup",
    "pre-check":        "PHASE 2 › Pre-Experiment Steady-State",
    "experiment-setup": "PHASE 3 › Experiment Target Setup",
    "experiment":       "PHASE 4 › Experiment Execution",
    "rollback":         "PHASE 5 › Rollback",
    "post-check":       "PHASE 6 › Post-Experiment Steady-State",
}


class PhaseUI:
    """One PhaseUI instance per AKS chaos experiment invocation."""

    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        self._current_phase: str | None = None
        self._phase_start: float        = 0.0
        self._step_buffer: list[str]    = []

    # ── public API ────────────────────────────────────────────────────────────

    @contextmanager
    def phase(self, key: str):
        """
        Context manager that wraps a named phase.
        Prints a labelled separator on entry, flushes buffered steps, then prints
        a ✔ / ✘ completion line on exit.

        key: one of the keys in _PHASE_LABELS, or any free-form string.
        """
        label = _PHASE_LABELS.get(key.lower(), key)
        self._current_phase = key
        self._phase_start   = time.monotonic()
        self._step_buffer   = []

        console.print()
        console.print(Rule(
            f"[bold bright_cyan]{label}[/bold bright_cyan]",
            style="bright_blue",
        ))

        error_caught = None
        try:
            yield self
        except Exception as exc:
            error_caught = exc
        finally:
            elapsed = time.monotonic() - self._phase_start
            self._flush_steps()

            if error_caught is None:
                console.print(
                    f"\n  {_TICK}  [bold green]{label} — complete[/bold green]"
                    f"  [dim]({elapsed:.2f}s)[/dim]"
                )
            else:
                short = str(error_caught)
                if len(short) > 100:
                    short = short[:97] + "..."
                console.print(
                    f"\n  {_CROSS}  [bold red]{label} — failed[/bold red]"
                    f"  [dim]({elapsed:.2f}s)[/dim]"
                )
                console.print(f"  [dim red]{short}[/dim red]")
                # Re-raise so ChaosToolkit catches the error
                raise error_caught

    def step(self, message: str, *, live: bool = False):
        """
        Emit a step line.

        live=False (default): buffer the line; printed as a block when the phase ends.
        live=True: print immediately — use for lines that are informative in real-time
                   (e.g. countdown timers, polling progress).
        """
        if live:
            self._flush_steps()
            console.print(f"  {_BULLET} [dim]{message}[/dim]")
        else:
            self._step_buffer.append(message)

    def status(self, message: str, *, ok: bool = True):
        """Print a visually prominent status change inline (not buffered)."""
        self._flush_steps()
        icon = _TICK if ok else _CROSS
        style = "bold green" if ok else "bold red"
        console.print(f"\n  {icon}  [{style}]{message}[/{style}]")

    def info(self, message: str):
        """Print a dim informational note inline — not buffered."""
        self._flush_steps()
        console.print(f"  [dim]{message}[/dim]")

    # ── internal ──────────────────────────────────────────────────────────────

    def _flush_steps(self):
        if not self._step_buffer:
            return
        for msg in self._step_buffer:
            console.print(f"  {_BULLET} [dim]{msg}[/dim]")
        self._step_buffer = []


# ── Standalone countdown helper used by the polling loop ─────────────────────

def live_countdown(label: str, duration_secs: int, poll_interval: int = 10):
    """
    Generator that yields (remaining_secs, tick) every second.
    Callers use it to update a 'Xm Ys remaining' line via PhaseUI.step(live=True).

    for remaining, tick in live_countdown("Experiment running", 60):
        ui.step(f"{label}: {remaining}s remaining", live=True)
    """
    elapsed = 0
    while elapsed < duration_secs:
        remaining = max(0, duration_secs - elapsed)
        yield remaining, elapsed
        time.sleep(1)
        elapsed += 1
    yield 0, elapsed
