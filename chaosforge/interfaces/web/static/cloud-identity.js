(() => {
    const identity = document.getElementById("cloud-identity");
    if (!identity) return;

    const icon = document.getElementById("cloud-identity-icon");
    const label = document.getElementById("cloud-identity-label");
    const name = document.getElementById("cloud-identity-name");
    const uploadPanel = document.querySelector("[data-yaml-upload-panel]");
    const loginPanel = document.querySelector("[data-yaml-login-panel]");
    let authenticated = identity.classList.contains("cloud-identity-authenticated");
    const storageKey = `chaosforge-cloud-authenticated-${identity.dataset.cloud}`;

    function setAuthenticatedUI(value) {
        authenticated = value;
        identity.classList.toggle("cloud-identity-authenticated", authenticated);
        identity.classList.toggle("cloud-identity-anonymous", !authenticated);
        icon.className = `bi ${authenticated ? "bi-shield-check" : "bi-shield-exclamation"}`;
        if (uploadPanel) uploadPanel.hidden = !authenticated;
        if (loginPanel) loginPanel.hidden = authenticated;
    }

    if (!authenticated && window.sessionStorage.getItem(storageKey) === "true") {
        setAuthenticatedUI(true);
    }

    function refreshIdentity() {
        fetch(`/api/cloud-identity/${encodeURIComponent(identity.dataset.cloud)}`)
            .then((response) => response.ok ? response.json() : Promise.reject(response.status))
            .then((data) => {
                const nextAuthenticated = Boolean(data.authenticated);
                const status = data.status || (nextAuthenticated ? "authenticated" : "unauthenticated");
                if (status === "unknown" && authenticated) return;
                authenticated = nextAuthenticated;
                label.textContent = data.label;
                name.textContent = data.name;
                if (authenticated) window.sessionStorage.setItem(storageKey, "true");
                else window.sessionStorage.removeItem(storageKey);
                setAuthenticatedUI(authenticated);
            })
            .catch(() => {});
    }

    refreshIdentity();
    window.setInterval(refreshIdentity, 20000);
})();
