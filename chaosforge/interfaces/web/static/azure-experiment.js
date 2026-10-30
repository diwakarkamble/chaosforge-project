document.addEventListener("DOMContentLoaded", function () {
    const selects = Array.from(document.querySelectorAll("[data-azure-resource]"));
    const byType = Object.fromEntries(selects.map(select => [select.dataset.azureResource, select]));
    function resourceRequest() {
        return {
            context: byType.azure_aks_cluster?.value || "",
            namespace: byType.azure_aks_namespace?.value || "",
            deployment: byType.azure_aks_deployment?.value || "",
            pod: byType.azure_aks_pod?.value || "",
            resource_group: document.getElementById("resource_group")?.value || "",
            subscription_id: document.getElementById("subscription_id")?.value || "",
        };
    }

    function requestOptions() {
        return {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(resourceRequest()),
        };
    }

    function loadResources(type) {
        switch (type) {
            case "azure_aks_cluster":
                return fetch("/api/azure/aks/resources/azure_aks_cluster", requestOptions());
            case "azure_aks_namespace":
                return fetch("/api/azure/aks/resources/azure_aks_namespace", requestOptions());
            case "azure_aks_deployment":
                return fetch("/api/azure/aks/resources/azure_aks_deployment", requestOptions());
            case "azure_aks_pod":
                return fetch("/api/azure/aks/resources/azure_aks_pod", requestOptions());
            case "azure_aks_container":
                return fetch("/api/azure/aks/resources/azure_aks_container", requestOptions());
            case "azure_aks_node":
                return fetch("/api/azure/aks/resources/azure_aks_node", requestOptions());
            case "azure_aks_zone":
                return fetch("/api/azure/aks/resources/azure_aks_zone", requestOptions());
            default:
                return null;
        }
    }

    async function load(select) {
        const type = select.dataset.azureResource;
        if (type === "azure_aks_cluster" && !resourceRequest().resource_group) {
            select.innerHTML = "<option value=''>Select a resource group first</option>";
            return;
        }
        const request = loadResources(type);
        if (!request) return;
        select.innerHTML = "<option value=''>Loading...</option>";
        try {
            const response = await request;
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const resources = await response.json();
            select.innerHTML = `<option value="">Select ${select.name.replaceAll("_", " ")}</option>`;
            resources.forEach(resource => {
                const option = document.createElement("option");
                option.value = resource.id;
                option.textContent = resource.name;
                select.appendChild(option);
            });
        } catch (error) {
            select.innerHTML = "<option value=''>Unable to load resources</option>";
        }
    }

    const dependencies = {
        azure_aks_cluster: ["azure_aks_namespace", "azure_aks_node", "azure_aks_zone"],
        azure_aks_namespace: ["azure_aks_deployment", "azure_aks_pod"],
        azure_aks_deployment: ["azure_aks_container"],
    };

    selects.forEach(select => {
        select.addEventListener("change", () => {
            (dependencies[select.dataset.azureResource] || []).forEach(type => {
                if (byType[type]) load(byType[type]);
            });
        });
    });
    document.getElementById("resource_group")?.addEventListener("change", () => {
        if (byType.azure_aks_cluster) load(byType.azure_aks_cluster);
    });
    if (byType.azure_aks_cluster && document.getElementById("resource_group")?.value) {
        load(byType.azure_aks_cluster);
    }
});
