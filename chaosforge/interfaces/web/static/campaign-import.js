document.addEventListener("DOMContentLoaded", function () {
    const zone = document.getElementById("yaml-drop-zone");
    const input = document.getElementById("campaign-yaml-input");
    const form = document.getElementById("yaml-drop-form");
    const status = document.getElementById("yaml-drop-status");
    if (!zone || !input || !form) return;

    function setStatus(message) {
        if (status) status.textContent = message;
    }

    function submitUpload() {
        if (input.files[0]) {
            zone.classList.add("is-uploading");
            setStatus("Uploading campaign YAML.");
            form.requestSubmit();
        }
    }

    ["dragenter", "dragover"].forEach(eventName => {
        zone.addEventListener(eventName, event => {
            event.preventDefault();
            zone.classList.add("drag-active");
        });
    });
    ["dragleave", "drop"].forEach(eventName => {
        zone.addEventListener(eventName, event => {
            event.preventDefault();
            zone.classList.remove("drag-active");
        });
    });
    zone.addEventListener("drop", event => {
        const file = event.dataTransfer.files[0];
        const filename = file?.name.toLowerCase() || "";
        if (!filename.endsWith(".yaml") && !filename.endsWith(".yml")) {
            setStatus("Choose a YAML file ending in .yaml or .yml.");
            return;
        }
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        const title = zone.querySelector(".yaml-drop-title");
        if (title) title.textContent = file.name;
        submitUpload();
    });
    input.addEventListener("change", () => {
        if (input.files[0]) {
            const title = zone.querySelector(".yaml-drop-title");
            if (title) title.textContent = input.files[0].name;
            submitUpload();
        }
    });
});
