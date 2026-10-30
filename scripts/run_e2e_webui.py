"""Run live Web UI functional E2E tests and retain an HTML report."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) == 1:
        print(
            "Usage: python scripts/run_e2e_webui.py "
            "--e2e-mode <tags|explicit> [pytest E2E options]"
        )
        return 2

    repository = Path(__file__).resolve().parent.parent
    report_dir = repository / "runtime" / "e2e-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_file = report_dir / f"webui-functional-{timestamp}.html"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-ra",
        f"--html={report_file}",
        "--self-contained-html",
        "e2e/webui/functional",
        *sys.argv[1:],
    ]
    result = subprocess.run(command, cwd=repository, check=False)
    print(f"HTML report: {report_file.relative_to(repository)}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
