let lastLogText = null;
let pollingStopped = false;
let pollingActive = false;
let focused = false;

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Request failed: ${response.status}`);
    return response.json();
}

async function updateConsole() {
    if (pollingActive || pollingStopped) return;
    pollingActive = true;
    const consoleBox = document.getElementById("console");
    const progressBar = document.getElementById("progress-bar");
    const currentExperiment = document.getElementById("current-exp");
    if (!consoleBox || !progressBar || !currentExperiment) return;

    try {
        const cloud = encodeURIComponent(window.chaosforgeCloud || "aws");
        const run = window.chaosforgeRun ? "&run=" + encodeURIComponent(window.chaosforgeRun) : "";
        const [lines, data] = await Promise.all([fetchJson("/execution/logs?cloud=" + cloud + run), fetchJson("/progress?cloud=" + cloud + run)]);
        const nextLogText = Array.isArray(lines) ? lines.join("\n") : "Execution log is unavailable.";
        if (nextLogText !== lastLogText) {
            const wasFollowingTail =
                consoleBox.scrollTop + consoleBox.clientHeight >= consoleBox.scrollHeight - 24;
            const previousScrollTop = consoleBox.scrollTop;

            consoleBox.textContent = nextLogText;
            lastLogText = nextLogText;

            if (!focused && window.chaosforgeFocus !== "") {
                const line = Number(window.chaosforgeFocus);
                if (Number.isFinite(line)) {
                    consoleBox.scrollTop = Math.max(0, line * 20);
                    focused = true;
                }
            }

            if (wasFollowingTail && !focused) {
                consoleBox.scrollTop = consoleBox.scrollHeight;
            } else {
                consoleBox.scrollTop = previousScrollTop;
            }
        }

        if (data.total > 0) {
            const percent = Math.max(0, Math.min(100, Math.floor((data.current / data.total) * 100)));
            progressBar.style.width = percent + "%";
            progressBar.textContent = percent + "%";
            progressBar.setAttribute("aria-valuenow", String(percent));

            if (data.finished || data.current >= data.total) {
                currentExperiment.textContent = "Campaign Completed";
                pollingStopped = true;
            }
            else {
                currentExperiment.textContent = "Running: " + (data.experiment || "Preparing...");
            }
        }
    } catch (error) {
        currentExperiment.textContent = "Connection issue. Retrying execution status...";
    } finally {
        pollingActive = false;
        if (!pollingStopped) window.setTimeout(updateConsole, 1000);
    }

}

updateConsole();
