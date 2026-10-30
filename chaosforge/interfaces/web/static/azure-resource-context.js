document.addEventListener("DOMContentLoaded", () => {
    const subscription = document.getElementById("subscription_id");
    const resourceGroup = document.getElementById("resource_group");
    const redis = document.querySelector("[data-azure-redis-caches]");
    const chaosIdentity = document.querySelector("[data-azure-redis-chaos-identities]");
    const bootstrapChaosIdentity = document.querySelector("[data-bootstrap-azure-redis-chaos-identity]");
    const resourceGroupError = document.getElementById("azure-resource-group-error");
    const identityStatus = document.getElementById("azure-redis-chaos-identity-status");
    if (!subscription || !resourceGroup || !subscription.value) return;

    function showIdentityStatus(message, level = "info") {
        if (!identityStatus) return;
        identityStatus.hidden = false;
        identityStatus.textContent = message;
        identityStatus.dataset.level = level;
    }

    function selectedValue(select) {
        return select.value || select.dataset.initialValue || "";
    }

    function displayName(value) {
        return String(value || "").replace(/\/$/, "").split("/").pop();
    }

    function sameAzureValue(left, right) {
        return String(left || "").toLowerCase() === String(right || "").toLowerCase();
    }

    async function loadOptions(select, url, placeholder) {
        const selected = selectedValue(select);
        select.disabled = true;
        const label = placeholder.replace(/^Select\s+/i, "");
        select.innerHTML = `<option value="">Loading ${label}...</option>`;
        try {
            const response = await fetch(url);
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                throw new Error(body.error || `HTTP ${response.status}`);
            }
            const resources = await response.json();
            if (resourceGroupError && select === resourceGroup) {
                resourceGroupError.hidden = true;
                resourceGroupError.textContent = "";
            }
            select.innerHTML = `<option value="">${placeholder}</option>`;
            resources.forEach((resource) => {
                const option = document.createElement("option");
                option.value = resource.id;
                option.textContent = resource.name;
                option.selected = sameAzureValue(resource.id, selected);
                select.appendChild(option);
            });
            if (selected && !resources.some((resource) => sameAzureValue(resource.id, selected))) {
                const option = document.createElement("option");
                option.value = selected;
                option.textContent = displayName(selected);
                option.selected = true;
                select.appendChild(option);
            }
            if (select === resourceGroup) {
                resourceGroup.dispatchEvent(new CustomEvent("azure-options-loaded"));
            }
        } catch (error) {
            select.innerHTML = "<option value=''>Unable to load options</option>";
            if (resourceGroupError && select === resourceGroup) {
                resourceGroupError.textContent = error.message;
                resourceGroupError.hidden = false;
            }
        } finally {
            select.disabled = false;
        }
    }

    function loadCaches() {
        if (!redis) return;
        if (!resourceGroup.value) {
            redis.innerHTML = "<option value=''>Select a resource group first</option>";
            return;
        }
        loadOptions(
            redis,
            `/api/azure/redis/caches/${encodeURIComponent(subscription.value)}/${encodeURIComponent(resourceGroup.value)}`,
            "Select Redis cache"
        );
    }

    function loadChaosIdentities() {
        if (!chaosIdentity) return;
        loadOptions(
            chaosIdentity,
            `/api/azure/redis/chaos-identities/${encodeURIComponent(subscription.value)}`,
            "Select Azure Chaos identity"
        );
    }

    bootstrapChaosIdentity?.addEventListener("click", async () => {
        const redisName = redis?.value;
        if (!resourceGroup.value || !redisName) {
            chaosIdentity.innerHTML = "<option value=''>Select a resource group and Redis cache first</option>";
            showIdentityStatus("Select a resource group and Redis cache before setup.", "warning");
            return;
        }
        if (!window.confirm(
            "Create or configure chaosforge-managed-identity and grant it Redis Cache Contributor on the selected Redis cache? " +
            "This requires Managed Identity Contributor and Owner or User Access Administrator permissions."
        )) return;
        bootstrapChaosIdentity.disabled = true;
        bootstrapChaosIdentity.innerHTML = '<i class="bi bi-arrow-repeat"></i> Checking Azure setup...';
        showIdentityStatus("Checking Azure Chaos identity and Redis Cache Contributor permission...", "info");
        try {
            const response = await fetch(
                `/api/azure/redis/chaos-identities/${encodeURIComponent(subscription.value)}/bootstrap`,
                {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({resource_group: resourceGroup.value, redis_name: redisName}),
                }
            );
            if (!response.ok) {
                const body = await response.json().catch(() => ({}));
                throw new Error(body.error || `HTTP ${response.status}`);
            }
            const result = await response.json();
            await loadChaosIdentities();
            if (result.status === "ready") {
                showIdentityStatus(result.message || "Azure Chaos identity is ready for the selected Redis cache.", "success");
            } else {
                showIdentityStatus(result.message || `Azure setup finished with status: ${result.status || "unknown"}.`, "warning");
            }
        } catch (error) {
            showIdentityStatus(`Setup failed: ${error.message}`, "error");
        } finally {
            bootstrapChaosIdentity.disabled = false;
            bootstrapChaosIdentity.innerHTML = '<i class="bi bi-shield-plus"></i> Set Up Azure Chaos Identity and Redis Permission';
        }
    });

    resourceGroup.dataset.initialValue = resourceGroup.value;
    resourceGroup.addEventListener("change", loadCaches);
    loadOptions(
        resourceGroup,
        `/api/azure/resource-groups/${encodeURIComponent(subscription.value)}`,
        "Select resource group"
    ).then(() => {
        loadCaches();
        loadChaosIdentities();
    });
});
