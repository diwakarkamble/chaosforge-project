document.addEventListener("DOMContentLoaded", function () {

    const selectAll = document.getElementById("select-all");

    const checkboxes = document.querySelectorAll(".exp-check");
    const selectionStatus = document.getElementById("campaign-selection-status");

    function syncSelectAll() {
        if (!selectAll) return;
        const selectedCount = document.querySelectorAll(".exp-check:checked").length;
        selectAll.checked = selectedCount === checkboxes.length && checkboxes.length > 0;
        selectAll.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
    }

    if (selectAll) {

        selectAll.addEventListener("change", function () {

            checkboxes.forEach(cb => {

                cb.checked = selectAll.checked;

            });

        });

    }

    checkboxes.forEach(cb => cb.addEventListener("change", syncSelectAll));

    const executeButton = document.getElementById("execute-selected");
    const executeAllButton = document.getElementById("execute-all");
    const viewPermissionsButton = document.getElementById("view-permissions");
    const permissionModalElement = document.getElementById("permission-review-modal");
    const permissionReport = document.getElementById("permission-review-report");
    const permissionCards = document.getElementById("permission-review-cards");
    const awsPolicyReview = document.getElementById("aws-policy-review");
    const awsPolicyReport = document.getElementById("aws-policy-report");
    const bootstrapPermissions = document.getElementById("bootstrap-permission-review");
    const bootstrapCards = document.getElementById("bootstrap-permission-cards");
    const confirmReviewButton = document.getElementById("confirm-permission-review");
    const irreversibleWarning = document.getElementById("irreversible-review-warning");
    const irreversibleList = document.getElementById("irreversible-review-list");
    const irreversibleAcknowledgement = document.getElementById("acknowledge-irreversible");
    const chaosMeshVersionReview = document.getElementById("chaos-mesh-version-review");
    const chaosMeshVersionOptions = document.getElementById("chaos-mesh-version-options");
    const permissionModal = permissionModalElement && window.bootstrap
        ? new window.bootstrap.Modal(permissionModalElement)
        : null;
    let pendingExecution = null;

    function selectedIds() {
        return Array.from(document.querySelectorAll(".exp-check:checked"), cb => Number(cb.value));
    }

    function formatAwsPermissions(report) {
        const warnings = report.warnings || [];
        const lines = [
            "AWS IAM POLICY",
            "",
            "Apply the complete policy below to the AWS identity that runs ChaosForge.",
            "All statements in this policy are required for the selected experiments.",
            "",
            JSON.stringify(report.policy, null, 2),
        ];
        if (warnings.length) {
            lines.push("", "WARNINGS", ...warnings.map(warning => `- ${warning}`));
        }
        return lines.join("\n");
    }

    function formatAzureSection(title, audience, requirements) {
        const lines = ["", title, audience];
        requirements.forEach((requirement, index) => {
            if (requirement.alternatives) {
                lines.push(
                    "",
                    `${index + 1}. Choose ONE: ${requirement.alternatives.join(" OR ")}`,
                    ...requirement.commands.map(command => `   ${command}`),
                );
                return;
            }
            lines.push(
                "",
                `${index + 1}. ${requirement.role}`,
                `   ${requirement.command}`,
            );
        });
        return lines;
    }

    function formatAzurePermissions(report) {
        const rbac = report.rbac || {};
        const runtime = rbac.runtime || [];
        const chaosStudio = rbac.chaos_studio_uami || [];
        const bootstrap = rbac.bootstrap || [];
        if (runtime.length && !chaosStudio.length && !bootstrap.length) {
            const lines = [
                "AZURE RUNTIME PERMISSIONS",
                "",
                "Assign the following role assignments to the DefaultAzureCredential identity running ChaosForge.",
            ];
            runtime.forEach(requirement => {
                lines.push(
                    "",
                    ...(requirement.alternatives ? requirement.commands : [requirement.command]),
                );
            });
            const warnings = report.warnings || [];
            if (warnings.length) {
                lines.push("", "WARNINGS", ...warnings.map(warning => `- ${warning}`));
            }
            return lines.join("\n");
        }
        const lines = [
            "AZURE REQUIRED PERMISSIONS",
            "",
            "Run each command with the object ID of the identity named by its section.",
            "Skip a command when that role is already assigned at this scope or an inherited scope.",
        ];
        if (chaosStudio.length) {
            lines.push(...formatAzureSection(
                "CHAOS STUDIO IDENTITY",
                "chaosforge-managed-identity ($CHAOS_STUDIO_UAMI_PRINCIPAL_ID)",
                chaosStudio,
            ));
        }
        if (runtime.length) {
            lines.push(...formatAzureSection(
                "CHAOSFORGE RUNTIME IDENTITY",
                "DefaultAzureCredential identity running ChaosForge ($RUNTIME_PRINCIPAL_ID)",
                runtime,
            ));
        }
        const warnings = report.warnings || [];
        if (warnings.length) {
            lines.push("", "WARNINGS", ...warnings.map(warning => `- ${warning}`));
        }
        return lines.join("\n");
    }

    function formatBootstrapPermissions(report) {
        const requirements = (report.rbac || {}).bootstrap || [];
        if (!requirements.length) return "";
        return [
            "Only needed when creating a Chaos Studio identity or assigning its roles.",
            ...formatAzureSection(
                "BOOTSTRAP / SETUP IDENTITY",
                "administrator or automation identity ($BOOTSTRAP_PRINCIPAL_ID)",
                requirements,
            ),
        ].join("\n");
    }

    function formatPermissionReport(report) {
        return report.provider === "azure"
            ? formatAzurePermissions(report)
            : formatAwsPermissions(report);
    }

    function scopeLabel(scope) {
        const parts = String(scope || "").split("/").filter(Boolean);
        return parts.at(-1) || scope;
    }

    function copyCommand(button, command) {
        navigator.clipboard?.writeText(command).then(() => {
            button.textContent = "Copied";
            setTimeout(() => { button.textContent = "Copy command"; }, 1500);
        });
    }

    function permissionCard(requirement) {
        const card = document.createElement("article");
        card.className = "permission-assignment-card";
        const heading = document.createElement("div");
        heading.className = "permission-assignment-heading";
        const role = document.createElement("strong");
        role.textContent = requirement.role || requirement.label;
        const label = document.createElement("span");
        label.className = "permission-scope-label";
        label.textContent = scopeLabel(requirement.scope);
        heading.append(role, label);
        card.appendChild(heading);
        const scope = document.createElement("code");
        scope.className = "permission-scope";
        scope.textContent = requirement.scope;
        card.appendChild(scope);
        const provenance = document.createElement("div");
        provenance.className = "permission-provenance";
        const provenanceLabel = document.createElement("span");
        provenanceLabel.textContent = "Required by";
        provenance.appendChild(provenanceLabel);
        (requirement.experiments || []).forEach(experiment => {
            const badge = document.createElement("span");
            badge.className = `permission-experiment-badge ${experiment.reversibility === "irreversible" ? "permission-experiment-irreversible" : ""}`;
            badge.textContent = experiment.name;
            provenance.appendChild(badge);
        });
        card.appendChild(provenance);
        const commands = requirement.alternatives ? requirement.commands : requirement.command ? [requirement.command] : [];
        commands.forEach((command, index) => {
            const commandRow = document.createElement("div");
            commandRow.className = "permission-command-row";
            const code = document.createElement("code");
            code.textContent = command;
            const copy = document.createElement("button");
            copy.type = "button";
            copy.className = "btn btn-sm btn-outline-light";
            copy.textContent = requirement.alternatives ? `Copy option ${index + 1}` : "Copy command";
            copy.addEventListener("click", () => copyCommand(copy, command));
            commandRow.append(code, copy);
            card.appendChild(commandRow);
        });
        if (requirement.actions?.length) {
            const actions = document.createElement("code");
            actions.className = "permission-actions";
            actions.textContent = requirement.actions.join("\n");
            card.appendChild(actions);
        }
        if (requirement.note) {
            const note = document.createElement("p");
            note.className = "permission-note";
            note.textContent = requirement.note;
            card.appendChild(note);
        }
        if (requirement.policy) {
            const copyPolicy = document.createElement("button");
            copyPolicy.type = "button";
            copyPolicy.className = "btn btn-sm btn-outline-info mt-2";
            copyPolicy.textContent = "Copy IAM policy";
            copyPolicy.addEventListener("click", () => copyCommand(copyPolicy, JSON.stringify(requirement.policy, null, 2)));
            card.appendChild(copyPolicy);
        }
        if (requirement.trust_policy) {
            const copyTrust = document.createElement("button");
            copyTrust.type = "button";
            copyTrust.className = "btn btn-sm btn-outline-secondary mt-2 ms-2";
            copyTrust.textContent = "Copy FIS trust policy";
            copyTrust.addEventListener("click", () => copyCommand(copyTrust, JSON.stringify(requirement.trust_policy, null, 2)));
            card.appendChild(copyTrust);
        }
        return card;
    }

    function renderIdentityCards(requirementsByIdentity, container, sections) {
        container.replaceChildren();
        sections.forEach(({key, title, identity, tone}) => {
            const requirements = requirementsByIdentity[key] || [];
            if (!requirements.length) return;
            const group = document.createElement("section");
            group.className = `permission-identity-card permission-identity-${tone}`;
            const heading = document.createElement("div");
            heading.className = "permission-identity-heading";
            const label = document.createElement("span");
            label.textContent = title;
            const identityLabel = document.createElement("strong");
            identityLabel.textContent = identity;
            heading.append(label, identityLabel);
            group.appendChild(heading);
            requirements.forEach(requirement => group.appendChild(permissionCard(requirement)));
            container.appendChild(group);
        });
    }

    function renderAwsCards(report) {
        renderIdentityCards(report.iam || {}, permissionCards, [
            {key: "runtime", title: "ChaosForge Runtime Identity", identity: "AWS identity running ChaosForge", tone: "runtime"},
            {key: "fis_execution", title: "AWS FIS Execution Role", identity: "Role assumed by AWS FIS", tone: "studio"},
        ].map(section => ({...section, key: section.key})));
    }

    function reviewPermissions(cloud, ids, executeAfterReview) {
        fetch("/api/campaign/permissions", {
            method: "POST",
            credentials: "same-origin",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({cloud, ids}),
        })
            .then(response => response.json().then(body => ({response, body})))
            .then(({response, body}) => {
                if (!response.ok) throw new Error(body.error || "Unable to generate permission report.");
                const irreversibleExperiments = body.irreversible_experiments || [];
                const chaosMeshVersions = body.chaos_mesh_versions || [];
                pendingExecution = {cloud, ids, token: body.review_token, executeAfterReview, irreversibleExperiments, chaosMeshVersions};
                const isAzure = body.report.provider === "azure";
                permissionReport.hidden = true;
                permissionCards.hidden = false;
                awsPolicyReview.hidden = isAzure;
                if (isAzure) {
                    renderIdentityCards(body.report.rbac || {}, permissionCards, [
                        {key: "chaos_studio_uami", title: "Chaos Studio Identity", identity: "chaosforge-managed-identity", tone: "studio"},
                        {key: "runtime", title: "ChaosForge Runtime Identity", identity: "DefaultAzureCredential", tone: "runtime"},
                    ]);
                    renderIdentityCards(body.report.rbac || {}, bootstrapCards, [
                        {key: "bootstrap", title: "Optional Setup Identity", identity: "Administrator or automation identity", tone: "bootstrap"},
                    ]);
                    bootstrapPermissions.parentElement.hidden = !bootstrapCards.children.length;
                } else {
                    renderAwsCards(body.report);
                    awsPolicyReport.textContent = JSON.stringify(body.report.policy, null, 2);
                    bootstrapPermissions.parentElement.hidden = true;
                }
                irreversibleAcknowledgement.checked = false;
                irreversibleList.replaceChildren();
                irreversibleExperiments.forEach(experiment => {
                    const item = document.createElement("li");
                    item.textContent = `${experiment.service}: ${experiment.name}`;
                    irreversibleList.appendChild(item);
                });
                irreversibleWarning.classList.toggle("visually-hidden", !irreversibleExperiments.length);
                chaosMeshVersionOptions.replaceChildren();
                chaosMeshVersions.forEach(item => {
                    const wrapper = document.createElement("div");
                    wrapper.className = `alert ${item.blocked ? "alert-danger" : item.state === "newer" ? "alert-warning" : "alert-info"}`;
                    const message = document.createElement("p");
                    message.className = "mb-2";
                    message.textContent = `${item.cluster}: ${item.message}`;
                    wrapper.appendChild(message);
                    if (item.requires_decision) {
                        const select = document.createElement("select");
                        select.className = "form-select chaos-mesh-version-choice";
                        select.dataset.clusterKey = item.key;
                        select.required = true;
                        select.innerHTML = item.state === "absent"
                            ? `<option value="">Select an action</option><option value="install">Install ${item.target_version}</option><option value="cancel">Cancel execution</option>`
                            : `<option value="">Select an action</option><option value="upgrade">Upgrade to ${item.target_version}</option><option value="continue">Continue with ${item.installed_version}</option><option value="cancel">Cancel execution</option>`;
                        wrapper.appendChild(select);
                    }
                    chaosMeshVersionOptions.appendChild(wrapper);
                });
                chaosMeshVersionReview.hidden = !chaosMeshVersions.length;
                permissionModal.show();
            })
            .catch(error => {
                if (selectionStatus) {
                    selectionStatus.textContent = error.message;
                    selectionStatus.classList.remove("visually-hidden");
                    selectionStatus.focus();
                }
            });
    }

    if (executeButton) {

        executeButton.addEventListener("click", function () {

            const selected = selectedIds();

            if (selected.length === 0) {

                if (selectionStatus) {
                    selectionStatus.textContent = "Select at least one experiment to execute.";
                    selectionStatus.classList.remove("visually-hidden");
                    selectionStatus.focus();
                }

                return;

            }

            reviewPermissions(executeButton.dataset.cloud || "", selected, true);

        });

    }

    if (executeAllButton) {
        executeAllButton.addEventListener("click", function () {
            reviewPermissions(executeAllButton.dataset.cloud || "", null, true);
        });
    }

    if (viewPermissionsButton) {
        viewPermissionsButton.addEventListener("click", function () {
            reviewPermissions(viewPermissionsButton.dataset.cloud || "", null, false);
        });
    }

    if (confirmReviewButton) {
        confirmReviewButton.addEventListener("click", function () {
            if (!pendingExecution) return;
            if (pendingExecution.irreversibleExperiments.length && !irreversibleAcknowledgement.checked) {
                selectionStatus.textContent = "Acknowledge the irreversible experiments before continuing.";
                selectionStatus.classList.remove("visually-hidden");
                selectionStatus.focus();
                return;
            }
            if (!pendingExecution.executeAfterReview) {
                permissionModal.hide();
                pendingExecution = null;
                return;
            }
            const chaosMeshDecisions = {};
            for (const select of document.querySelectorAll(".chaos-mesh-version-choice")) {
                if (!select.value || select.value === "cancel") {
                    selectionStatus.textContent = select.value === "cancel"
                        ? "Chaos Mesh execution was cancelled."
                        : "Select a Chaos Mesh version action for every cluster.";
                    selectionStatus.classList.remove("visually-hidden");
                    selectionStatus.focus();
                    return;
                }
                chaosMeshDecisions[select.dataset.clusterKey] = select.value;
            }
            fetch("/api/campaign/permissions/confirm", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    review_token: pendingExecution.token,
                    irreversible_acknowledged: irreversibleAcknowledgement.checked,
                    chaos_mesh_decisions: chaosMeshDecisions,
                }),
            })
                .then(response => response.json().then(body => ({response, body})))
                .then(({response, body}) => {
                    if (!response.ok) throw new Error(body.error || "Unable to confirm permission review.");
                    const params = new URLSearchParams({
                        cloud: pendingExecution.cloud,
                        review: pendingExecution.token,
                    });
                    const path = pendingExecution.ids
                        ? "/campaign/execute-selected?ids=" + pendingExecution.ids.join(",") + "&" + params.toString()
                        : "/campaign/execute?" + params.toString();
                    window.location = path;
                })
                .catch(error => {
                    if (selectionStatus) {
                        selectionStatus.textContent = error.message;
                        selectionStatus.classList.remove("visually-hidden");
                        selectionStatus.focus();
                    }
                });
        });
    }

});
