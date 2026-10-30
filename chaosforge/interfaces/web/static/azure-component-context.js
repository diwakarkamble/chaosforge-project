document.addEventListener("DOMContentLoaded", () => {
    const subscription = document.getElementById("subscription_id");
    const resourceGroup = document.getElementById("resource_group");
    const resource = document.querySelector("[data-azure-component-resource]");
    const instances = document.querySelector("[data-azure-vmss-instances]");
    const instancePicker = document.querySelector("[data-azure-vmss-instance-picker]");
    const identity = document.querySelector("[data-azure-component-chaos-identity]");
    const bootstrap = document.querySelector("[data-bootstrap-azure-component-chaos-identity]");
    if (!subscription || !resourceGroup || !resource) return;

    const component = resource.dataset.azureComponentResource;
    const status = document.querySelector(`[data-azure-component-identity-status="${component}"]`);
    const selected = (select) => select.value || select.dataset.initialValue || "";
    const sameArmId = (left, right) => String(left || "").toLowerCase() === String(right || "").toLowerCase();
    const displayName = (value) => String(value || "").replace(/\/$/, "").split("/").pop();
    const loadVersions = new WeakMap();

    function show(message, level) {
        if (!status) return;
        status.hidden = false;
        status.textContent = message;
        status.dataset.level = level;
    }

    async function load(select, url, placeholder, payload = {}) {
        const initial = selected(select);
        const version = (loadVersions.get(select) || 0) + 1;
        loadVersions.set(select, version);
        select.disabled = true;
        select.innerHTML = `<option value="">Loading ${placeholder.replace(/^Select\s+/i, "")}...</option>`;
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload),
            });
            const body = await response.json();
            if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
            if (loadVersions.get(select) !== version) return;
            select.innerHTML = `<option value="">${placeholder}</option>`;
            let matched = false;
            body.forEach((item) => {
                const option = document.createElement("option");
                option.value = item.id;
                option.textContent = item.name;
                option.selected = sameArmId(item.id, initial);
                matched = matched || option.selected;
                select.appendChild(option);
            });
            if (initial && !matched) {
                const option = document.createElement("option");
                option.value = initial;
                option.textContent = displayName(initial);
                option.selected = true;
                select.appendChild(option);
            }
        } catch (error) {
            if (loadVersions.get(select) !== version) return;
            select.innerHTML = "<option value=''>Unable to load options</option>";
            show(`Unable to load ${placeholder.toLowerCase()}: ${error.message}`, "error");
        } finally {
            if (loadVersions.get(select) === version) select.disabled = false;
        }
    }

    function loadResources() {
        if (instances && instancePicker) {
            instances.value = "";
            instancePicker.innerHTML = "<div class='text-muted'>Select a scale set first.</div>";
        }
        if (!resourceGroup.value) {
            resource.innerHTML = "<option value=''>Select a resource group first</option>";
            return;
        }
        load(
            resource,
            `/api/azure/components/${encodeURIComponent(component)}/resources/${encodeURIComponent(subscription.value)}`,
            "Select target resource",
            {resource_group: resourceGroup.value},
        );
    }

    function selectedInstances() {
        try {
            const values = JSON.parse(instances?.value || "[]");
            return Array.isArray(values) ? values.map(String) : [];
        } catch (_) {
            return [];
        }
    }

    function loadInstances() {
        if (!instances || !instancePicker) return;
        if (!resourceGroup.value || !resource.value) {
            instances.value = "";
            instancePicker.innerHTML = "<div class='text-muted'>Select a scale set first.</div>";
            return;
        }
        instancePicker.innerHTML = "<div class='text-muted'>Loading scale set instances...</div>";
        fetch(`/api/azure/components/azure_vmss/instances/${encodeURIComponent(subscription.value)}`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({resource_group: resourceGroup.value, resource_id: resource.value}),
        })
            .then(response => response.json().then(body => ({response, body})))
            .then(({response, body}) => {
                if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
                const checked = new Set(selectedInstances());
                instancePicker.replaceChildren();
                if (!body.length) {
                    instancePicker.textContent = "No instances found in this scale set.";
                    return;
                }
                body.forEach(instance => {
                    const wrapper = document.createElement("div");
                    wrapper.className = "form-check";
                    const checkbox = document.createElement("input");
                    checkbox.className = "form-check-input";
                    checkbox.type = "checkbox";
                    checkbox.id = `vmss-instance-${instance.id}`;
                    checkbox.value = instance.id;
                    checkbox.checked = checked.has(String(instance.id));
                    const label = document.createElement("label");
                    label.className = "form-check-label";
                    label.htmlFor = checkbox.id;
                    label.textContent = instance.name;
                    checkbox.addEventListener("change", () => {
                        instances.value = JSON.stringify(
                            Array.from(instancePicker.querySelectorAll("input:checked"), item => item.value)
                        );
                    });
                    wrapper.append(checkbox, label);
                    instancePicker.appendChild(wrapper);
                });
            })
            .catch(error => {
                instances.value = "";
                instancePicker.textContent = `Unable to load scale set instances: ${error.message}`;
            });
    }

    function loadIdentities() {
        if (!identity) return;
        load(
            identity,
            `/api/azure/components/${encodeURIComponent(component)}/chaos-identities/${encodeURIComponent(subscription.value)}`,
            "Select Azure Chaos identity",
            {identity_id: selected(identity)},
        );
    }

    resourceGroup.addEventListener("change", loadResources);
    resource.addEventListener("change", loadInstances);
    identity?.addEventListener("chaosforge-load-identity", loadIdentities);
    resourceGroup.addEventListener("azure-options-loaded", loadResources);
    bootstrap?.addEventListener("click", async () => {
        if (!resourceGroup.value || !resource.value) {
            show("Select a resource group and target resource before setup.", "warning");
            return;
        }
        if (!window.confirm("Create or configure chaosforge-managed-identity and grant the required target role?")) return;
        bootstrap.disabled = true;
        show("Checking Azure Chaos identity and target permission...", "info");
        try {
            const response = await fetch(
                `/api/azure/components/${encodeURIComponent(component)}/chaos-identities/${encodeURIComponent(subscription.value)}/bootstrap`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        resource_group: resourceGroup.value,
                        resource_id: resource.value,
                        experiment_id: document.querySelector("form")?.dataset.experimentId || "",
                    }),
                },
            );
            const body = await response.json();
            if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
            show(body.message || "Azure Chaos identity setup completed.", body.status === "ready" ? "success" : "warning");
            await loadIdentities();
        } catch (error) {
            show(`Setup failed: ${error.message}`, "error");
        } finally {
            bootstrap.disabled = false;
        }
    });

    if (resourceGroup.value) loadResources();
    loadIdentities();
});
