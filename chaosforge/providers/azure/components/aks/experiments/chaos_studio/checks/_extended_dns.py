import datetime as _dt
import json

from ._extended_common import (
    _AUTH_DOMAIN_FRAGMENTS,
    _check_chaos_crd,
    _check_no_stale_chaos_crd,
    _first_running_pod,
    _get_pods_json,
    _kubectl,
)


def build_dns_chaos_pre_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    *,
    dns_pattern: str = "",
    duration: str = "60s",
) -> "dict[str, callable]":
    """
    Pre-chaos checks for DNSChaos.

    Hard blocks:
      - dns_pattern matches shared auth/secrets infrastructure (STS, Vault,
        OIDC issuers, Kerberos, LDAP, cloud auth endpoints). DNS failure
        on these revokes tokens cluster-wide, not just for the target pod.
      - CoreDNS is not running (experiment would fail silently — DNS already broken)
      - dns_pattern matches cluster-internal service FQDN that auth infrastructure
        depends on (kubernetes.default.svc, vault.vault.svc, etc.)

    Soft warnings:
      - cert-manager's ACME issuer domain matches the dns_pattern
        (certificate renewal will fail for the duration)
      - dns_pattern is a wildcard (including the default bare '*') that covers
        more domains than a single dependency — blast radius stays bounded by
        the pod selector, so this is advisory, not a block

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    _dns_pattern = (dns_pattern or "").strip().lower()

    # ── 0a. DNSChaos CRD installed ────────────────────────────────────────────
    def _dnschaos_crd():
        return _check_chaos_crd(aks_context, "dnschaos.chaos-mesh.org")
    checks["DNSChaos CRD Installed"] = _dnschaos_crd

    # ── 0b. No stale DNSChaos resource active ─────────────────────────────────
    def _no_stale_dnschaos():
        return _check_no_stale_chaos_crd(aks_context, "dnschaos")
    checks["No Stale DNSChaos Resource"] = _no_stale_dnschaos

    # ── 0c. dns_pattern not empty or unreplaced placeholder (HARD BLOCK) ──────
    # Rationale: the spec ships with a bare '*' as its default pattern, which is
    # a valid (if broad) target — check 4 below surfaces it as an advisory rather
    # than blocking. This check catches the states that are genuinely invalid:
    # empty, an unreplaced '<...>' placeholder, or loopback — any of which would
    # let the experiment run while proving nothing.
    import re as _re
    def _dns_pattern_valid():
        if not _dns_pattern:
            return False, (
                "dns_pattern is empty.\n"
                "  ✘ No domain to fail — experiment will inject nothing. "
                "Set dns_pattern to the specific external domain the target pod calls."
            )
        if _re.search(r"^<.+>$", _dns_pattern):
            return False, (
                f"dns_pattern='{_dns_pattern}'\n"
                "  ✘ Unreplaced placeholder detected. This domain does not exist — "
                "experiment will run but inject a fault that no service queries, "
                "proving nothing. Replace with the actual external domain to target."
            )
        if _dns_pattern in ("localhost", "127.0.0.1", "0.0.0.0"):
            return False, (
                f"dns_pattern='{_dns_pattern}'\n"
                "  ✘ Loopback target — DNS failure on localhost has no observable effect. "
                "Use a real external service domain."
            )
        # Chaos Mesh's k8s_dns_chaos CoreDNS plugin only accepts '*' as a whole
        # label: either the entire pattern ('*') or a leading/trailing label
        # ('*.example.com', 'example.*'). An infix wildcard such as
        # '*substring*' is silently rejected by chaos-dns-server at inject time
        # with "insert into schema selector: pattern ... not valid" — the
        # DNSChaos CRD still reports AllInjected and the run appears to succeed
        # while injecting nothing. Catch it here instead.
        # Chaos Mesh's k8s_dns_chaos CoreDNS plugin only accepts '*' at the END
        # of the pattern (or as the entire pattern). Verified empirically against
        # chaos-dns-server: '*', 'csas*' and 'chaos-mesh.*' are accepted, while
        # '*.example.com', '*nonprod', 'git*.com' and '*sub*' are all rejected.
        # NOTE: the upstream docs list 'git*.com' as valid — it is NOT.
        # An invalid pattern is rejected at inject time with "insert into schema
        # selector: pattern ... not valid", yet the DNSChaos CRD still reports
        # AllInjected=True, so the run looks successful while injecting nothing.
        if (
            _dns_pattern != "*"
            and "*" in _dns_pattern
            and (_dns_pattern.count("*") > 1 or not _dns_pattern.endswith("*"))
        ):
            return False, (
                    f"dns_pattern='{_dns_pattern}'\n"
                    "  ✘ Invalid wildcard placement. Chaos Mesh accepts '*' only as the "
                    "entire pattern or as a single trailing character.\n"
                    "     This is rejected by chaos-dns-server at inject time, but the "
                    "DNSChaos CRD still reports AllInjected=True — the run would appear "
                    "to succeed while injecting nothing.\n"
                    "     Valid:   '*', 'csas*', 'chaos-mesh.*', 'api.example.com'\n"
                    "     Invalid: '*.example.com', '*nonprod', 'git*.com', '*sub*'"
            )
        return True, (
            f"dns_pattern='{_dns_pattern}'\n"
            "  ✔ Pattern is non-empty, non-placeholder, non-loopback, wildcard placement valid"
        )
    checks["DNS Pattern Valid (non-empty, non-placeholder)"] = _dns_pattern_valid

    # ── 1. Auth/secrets infrastructure domain guard (HARD BLOCK) ─────────────
    # Rationale: STS endpoints, Vault, OIDC issuers, and cloud auth endpoints are
    # used by every pod's workload identity, service account token projection,
    # and application-level OAuth flows. A DNS failure on these domains causes
    # cascading token validation failures across ALL workloads, not just the target.
    # The experiment's blast radius becomes the entire cluster.
    def _no_auth_domain():
        if not _dns_pattern:
            return True, "No dns_pattern configured — skipping auth domain check"

        matched = [frag for frag in _AUTH_DOMAIN_FRAGMENTS if frag in _dns_pattern]
        detail = (
            f"DNS pattern: '{_dns_pattern}'\n"
            f"  Checked against {len(_AUTH_DOMAIN_FRAGMENTS)} protected auth domain fragments\n"
            f"  Matches: {matched if matched else 'none'}"
        )
        if matched:
            return False, (
                detail + f"\n  ✘ DNS pattern '{_dns_pattern}' matches auth/secrets infrastructure "
                f"domain(s): {matched}. Failing DNS for these domains will revoke tokens/certs "
                f"cluster-wide — blast radius extends to ALL workloads, not just the target. "
                f"Use a domain specific to the application under test."
            )
        return True, detail + "\n  ✔ DNS pattern does not match protected auth domains"
    checks["Auth Domain Safety Check"] = _no_auth_domain

    # ── 2. CoreDNS is running ─────────────────────────────────────────────────
    # Rationale: DNSChaos works by patching CoreDNS to return errors for the
    # target domain. If CoreDNS is already degraded, the chaos injection will
    # fail silently — the experiment measures nothing — and rolling back will not
    # restore DNS that was already broken before the experiment.
    def _coredns_running():
        r = _kubectl("get", "pods", "-n", "kube-system",
                     "-l", "k8s-app=kube-dns", "-o", "json", context=aks_context)
        detail = "kubectl get pods -n kube-system -l k8s-app=kube-dns --context {aks_context}"
        if r.returncode != 0:
            return False, detail + f"\n  ✘ Could not query CoreDNS pods: {r.stderr.strip()}"
        try:
            pods = json.loads(r.stdout).get("items", [])
        except ValueError:
            return False, detail + "\n  ✘ Could not parse CoreDNS pod list"

        running = [
            p.get("metadata", {}).get("name", "?") for p in pods
            if p.get("status", {}).get("phase") == "Running"
            and any(c.get("type") == "Ready" and c.get("status") == "True"
                    for c in p.get("status", {}).get("conditions", []))
        ]
        detail = (
            f"kubectl get pods -n kube-system -l k8s-app=kube-dns --context {aks_context}\n"
            f"  CoreDNS pods ready: {len(running)}/{len(pods)}  {running}"
        )
        if not running:
            return False, (
                detail + "\n  ✘ No CoreDNS pods running. DNSChaos injects via CoreDNS — "
                "if CoreDNS is down, the experiment will fail silently and DNS is already broken. "
                "Restore CoreDNS before running this experiment."
            )
        return True, detail + "\n  ✔ CoreDNS is running"
    checks["CoreDNS Running"] = _coredns_running

    # ── 2b. Shell presence — HARD BLOCK for distroless images ───────────────────
    # Rationale: Chaos Mesh's nsexec helper backs up /etc/resolv.conf before
    # rewriting it by running:
    #   sh -c "ls /etc/resolv.conf.chaos.bak || cp /etc/resolv.conf /etc/resolv.conf.chaos.bak"
    # inside the target container's own mount namespace. Distroless/scratch images
    # have no /bin/sh — the Rust helper panics with Os { code: 2, kind: NotFound }
    # on every retry. The DNSChaos CRD still reports AllInjected=True (the
    # controller layer only tracks whether the request was accepted, not whether
    # the shell command ran), so the experiment appears to succeed while injecting
    # nothing — a false positive. Hard-block here instead of letting it run.
    # DNS tools (nslookup/dig) are needed only for our verification probes —
    # their absence is a soft warning, not a block, since chaos still injects.
    _PROBE_EXEC_FAILURE_MARKERS = (
        "executable file not found",
        "OCI runtime exec failed",
        "unable to start container process",
        "cannot exec in a stopped",
        "container not found",
    )

    def _in_pod_probe_capability():
        selector = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
        pod = _first_running_pod(aks_context, namespace, selector)
        if not pod:
            return True, "No running pod found — cannot assess shell presence"

        # Step 1: is there a shell at all? (HARD BLOCK if absent)
        r = _kubectl("exec", pod, "-n", namespace, "--", "sh", "-c", "echo ok",
                     context=aks_context)
        out = (r.stdout or "") + (r.stderr or "")
        if any(m in out for m in _PROBE_EXEC_FAILURE_MARKERS):
            return False, (
                f"pod: {pod}\n"
                "  ✘ No shell (/bin/sh) in container image (distroless/scratch).\n"
                "     Chaos Mesh's nsexec helper runs:\n"
                "       sh -c \"ls /etc/resolv.conf.chaos.bak || cp /etc/resolv.conf /etc/resolv.conf.chaos.bak\"\n"
                "     inside the pod's mount namespace before rewriting /etc/resolv.conf.\n"
                "     Without /bin/sh this panics — injection stays 'pending' for the full\n"
                "     duration while DNSChaos CRD falsely reports AllInjected=True.\n"
                "     Fix: target a deployment whose image includes /bin/sh (e.g. alpine,\n"
                "     debian-slim, or an image with busybox), or add a debug sidecar."
            )
        if r.returncode != 0:
            return True, (
                f"pod: {pod}\n"
                f"  ⚠ Shell probe failed ({out.strip()[:100]}) — "
                "could not confirm shell presence; proceed with caution."
            )

        # Step 2: which DNS tools exist? Soft warning only — chaos injects fine
        # without them, but our verification probes (pre-resolution, canary) can't run.
        found = []
        for tool in ("nslookup", "dig", "getent", "host"):
            t = _kubectl("exec", pod, "-n", namespace, "--", "sh", "-c",
                         f"command -v {tool} 2>/dev/null || which {tool} 2>/dev/null",
                         context=aks_context)
            if t.returncode == 0 and t.stdout.strip():
                found.append(tool)

        if not found:
            return True, (
                f"pod: {pod}\n"
                "  ✔ Shell (/bin/sh) present — chaos-daemon backup step will succeed.\n"
                "  ⚠ No DNS tools (nslookup/dig/getent/host) in image.\n"
                "     Chaos will inject correctly, but in-pod verification probes cannot run.\n"
                "     Verify impact via chaos-dns-server logs and Datadog instead."
            )
        return True, (
            f"pod: {pod}\n"
            f"  ✔ Shell present; DNS tools available: {', '.join(found)}\n"
            "     In-pod probes (pre-resolution, in-fault canary) will work."
        )
    checks["Shell Present in Target Pod (DNSChaos Requirement)"] = _in_pod_probe_capability

    # ── 3. DNS resolves the target domain before injection ────────────────────
    # Rationale: verify the domain resolves *now* so post-chaos recovery check
    # has a baseline. If the domain doesn't resolve pre-chaos, the post-check
    # "DNS recovered" assertion is meaningless.
    # A wildcard cannot be resolved literally, so probe a concrete canary domain
    # that the wildcard also covers — this still establishes a real baseline.
    _canary_domain = "kubernetes.default.svc.cluster.local"
    _probe_domain  = _canary_domain if "*" in _dns_pattern else _dns_pattern

    def _dns_pre_resolution():
        if not _dns_pattern:
            return True, "DNS pattern is empty — skipping pre-resolution check"
        pod = _first_running_pod(aks_context, namespace,
                                  f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}")
        if not pod:
            return True, "No running pod found — cannot exec DNS lookup pre-chaos"

        _via = (f" (canary for wildcard '{_dns_pattern}')"
                if _probe_domain != _dns_pattern else "")

        # Try nslookup then dig as fallback
        for tool, args in [
            ("nslookup", [f"nslookup {_probe_domain}"]),
            ("dig",      [f"dig +short {_probe_domain}"]),
            ("getent",   [f"getent hosts {_probe_domain}"]),
        ]:
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "sh", "-c", args[0], context=aks_context)
            if r.returncode == 0 and r.stdout.strip():
                detail = (
                    f"kubectl exec {pod} -n {namespace} -- sh -c '{args[0]}'\n"
                    f"  result: {r.stdout.strip()[:120]}"
                )
                return True, detail + f"\n  ✔ '{_probe_domain}'{_via} resolves pre-chaos (baseline confirmed)"
            if r.returncode == 0 and not r.stdout.strip():
                # Tool ran but returned empty — domain may not resolve
                continue
            # Tool not available in container — try next

        detail = (
            f"DNS pre-resolution check for '{_probe_domain}'{_via} from pod {pod}\n"
            f"  No DNS lookup tool available (nslookup/dig/getent) or resolution failed"
        )
        return True, (
            "⚠ " + detail +
            "\n  Could not verify DNS resolution pre-chaos. Post-chaos recovery check will still run. "
            "Install busybox/curl/dnsutils in the container for better DNS observability."
        )
    checks[f"DNS Pre-Resolution ({_dns_pattern or 'not set'})"] = _dns_pre_resolution

    # ── 4. Wildcard blast-radius warning (soft warning) ───────────────────────
    # Rationale: a wildcard pattern like "*.example.com" or "*" will fail ALL
    # DNS queries matching it — not just the specific service being tested.
    # Bare "*" is the spec's default (total DNS blackout for the selected pods),
    # which is a legitimate resilience test, so it is surfaced as a loud advisory
    # rather than a hard block. The selector still bounds the fault to the
    # targeted pods — it never reaches the rest of the cluster.
    def _wildcard_blast_radius():
        if not _dns_pattern:
            return True, "No DNS pattern — skipping wildcard check"
        if "*" not in _dns_pattern:
            return True, (
                f"DNS pattern '{_dns_pattern}' is not a wildcard — blast radius is bounded"
            )
        detail = f"DNS pattern: '{_dns_pattern}'"
        if _dns_pattern.strip() == "*":
            return True, (
                "⚠ " + detail +
                "\n  Pattern is bare '*' — ALL DNS queries from the targeted pod(s) will fail "
                "(total DNS blackout for those pods, including cluster-internal service lookups). "
                "Blast radius is bounded by the pod selector and does not extend cluster-wide. "
                "Set a specific domain if you intended to fail only one dependency."
            )
        # Partial wildcard: warn but don't block
        return True, (
            "⚠ " + detail +
            "\n  Wildcard DNS pattern will fail all subdomains matching the pattern, "
            "not just one service. Verify the intended blast radius before proceeding."
        )
    checks["DNS Pattern Blast Radius"] = _wildcard_blast_radius

    # ── 5. cert-manager ACME issuer domain match (soft warning) ──────────────
    # Rationale: cert-manager ACME HTTP-01/DNS-01 challenges contact the ACME
    # issuer's server. If the dns_pattern matches the ACME server domain, any
    # certificate renewal that happens during the experiment will fail permanently
    # (ACME orders time out after ~90s and must be re-initiated).
    def _certmanager_acme_issuer():
        if not _dns_pattern or "*" in _dns_pattern:
            return True, "Wildcard or empty pattern — skipping ACME issuer check"

        # Check ClusterIssuers and Issuers for ACME configuration
        acme_servers = []
        for res_type in ("clusterissuers", "issuers"):
            namespace_flag = [] if res_type == "clusterissuers" else ["-n", namespace]
            r = _kubectl("get", res_type, *namespace_flag, "-o", "json",
                         context=aks_context)
            if r.returncode != 0:
                continue
            try:
                for issuer in json.loads(r.stdout).get("items", []):
                    server = (issuer.get("spec", {}).get("acme", {}).get("server") or "").lower()
                    if server:
                        acme_servers.append(server)
            except ValueError:
                pass

        if not acme_servers:
            return True, (
                "kubectl get clusterissuers,issuers — no ACME issuers found\n"
                "  No cert-manager ACME configuration — skipping issuer check"
            )

        matched_issuers = [s for s in acme_servers if _dns_pattern in s]
        detail = (
            f"DNS pattern: '{_dns_pattern}'\n"
            f"  ACME issuer servers: {acme_servers}\n"
            f"  Pattern in issuer URL: {matched_issuers if matched_issuers else 'none'}"
        )
        if matched_issuers:
            return True, (
                "⚠ " + detail +
                "\n  DNS pattern matches the ACME issuer server URL. "
                "Any certificate renewal during this experiment will fail — "
                "ACME challenge cannot contact the issuer. Certificates with imminent "
                "renewal will remain unrenewed until the experiment completes."
            )
        return True, detail + "\n  ✔ DNS pattern does not overlap with ACME issuer URLs"
    checks["cert-manager ACME Issuer Domain (Advisory)"] = _certmanager_acme_issuer

    return checks


# ═════════════════════════════════════════════════════════════════════════════
# DNS CHAOS (DNSChaos) — Post-Checks
# ═════════════════════════════════════════════════════════════════════════════

def build_dns_chaos_post_checks(
    aks_context: str,
    namespace: str,
    deployment: str,
    label_key: str = "",
    label_val: str = "",
    *,
    dns_pattern: str = "",
) -> "dict[str, callable]":
    """
    Post-chaos checks for DNSChaos. Confirms DNS resolution recovered inside
    the target pod and the Chaos Mesh CRD resource was cleaned up.

    Returns {label: fn} dict.
    """
    checks: dict[str, callable] = {}
    selector    = f"{label_key}={label_val}" if (label_key and label_val) else f"app={deployment}"
    _dns_pattern = (dns_pattern or "").strip().lower()

    # ── 1. DNS resolution recovered in pod ───────────────────────────────────
    # Rationale: exec into the target pod and resolve the chaos domain.
    # This is the ground-truth check — the Chaos Mesh CRD being deleted is
    # necessary but not sufficient. CoreDNS config must also have been restored.
    def _dns_resolved_in_pod():
        if not _dns_pattern or "*" in _dns_pattern:
            return True, (
                f"DNS pattern '{_dns_pattern}' is empty or wildcard — "
                "skipping in-pod resolution check"
            )

        pod = _first_running_pod(aks_context, namespace, selector)
        if not pod:
            return False, (
                f"No running pod found matching selector '{selector}' in namespace '{namespace}'\n"
                "  Cannot exec DNS lookup — verify pod is Running"
            )

        for tool, cmd_str in [
            ("nslookup", f"nslookup {_dns_pattern}"),
            ("dig",      f"dig +short {_dns_pattern}"),
            ("getent",   f"getent hosts {_dns_pattern}"),
            ("ping",     f"ping -c1 -W2 {_dns_pattern} 2>&1 | head -2"),
        ]:
            r = _kubectl("exec", pod, "-n", namespace, "--",
                         "sh", "-c", cmd_str, context=aks_context)
            detail = (
                f"kubectl exec {pod} -n {namespace} -- sh -c '{cmd_str}'\n"
                f"  exit={r.returncode}\n"
                f"  output: {r.stdout.strip()[:200]}"
            )
            if r.returncode == 0 and r.stdout.strip():
                # Verify output doesn't contain error phrases
                output_lower = r.stdout.lower()
                error_phrases = ("can't find", "nxdomain", "servfail", "refused",
                                 "no such host", "connection refused", "timed out")
                if any(phrase in output_lower for phrase in error_phrases):
                    return False, (
                        detail + "\n  ✘ DNS still returning error response. "
                        "Chaos Mesh DNSChaos may still be active or CoreDNS not yet recovered."
                    )
                return True, detail + f"\n  ✔ '{_dns_pattern}' resolves post-chaos — DNS recovered"
            if r.returncode != 0 and "not found" in r.stderr.lower():
                # Tool not in container — try next
                continue

        return True, (
            f"DNS post-resolution check for '{_dns_pattern}' from pod {pod}\n"
            "  ⚠ No DNS lookup tool available — could not verify in-pod DNS recovery. "
            "Check pod logs for connection errors as a proxy for DNS health."
        )
    checks[f"DNS Recovered in Pod ({_dns_pattern or 'not set'})"] = _dns_resolved_in_pod

    # ── 2. DNSChaos CRD resource removed ─────────────────────────────────────
    # Rationale: Chaos Mesh deletes the DNSChaos resource when the experiment
    # duration expires. If it persists, CoreDNS still has the error rule active.
    def _dnschaos_crd_deleted():
        r = _kubectl("get", "dnschaos", "-n", "chaos-testing",
                     "--no-headers", context=aks_context)
        detail = "kubectl get dnschaos -n chaos-testing"
        if r.returncode != 0:
            return True, detail + "\n  (query failed — assuming cleaned up)"
        existing = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        if existing:
            return False, (
                detail + f"\n  ✘ DNSChaos resources still present: {existing}\n"
                f"  CoreDNS error rule for '{_dns_pattern}' may still be ACTIVE."
            )
        return True, detail + "\n  ✔ All DNSChaos CRD resources removed — CoreDNS rule reverted"
    checks["DNSChaos CRD Cleaned Up"] = _dnschaos_crd_deleted

    # ── 3. No DNS-related pod events in last 5m ───────────────────────────────
    # Rationale: applications that hit DNS errors during the chaos window often
    # emit Warning events (BackOff, Failed) from retried connections. Persisting
    # events after revert indicate the app's connection pool or cache has not
    # yet recovered.
    def _no_dns_events():
        r = _kubectl("get", "events", "-n", namespace, "-o", "json",
                     context=aks_context)
        if r.returncode != 0:
            return True, f"Could not query events (non-fatal): {r.stderr.strip()}"
        try:
            events = json.loads(r.stdout).get("items", [])
        except ValueError:
            return True, "Could not parse events — skipping"

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
        dns_keywords = ("dns", "lookup", "resolve", "nxdomain", "connection refused",
                        "no such host", "i/o timeout", "dial tcp", "backoff")
        found = []
        for ev in events:
            if ev.get("type") != "Warning":
                continue
            ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ""
            try:
                ts = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                pass
            msg = ev.get("message", "").lower()
            obj = ev.get("involvedObject", {}).get("name", "?")
            if any(kw in msg for kw in dns_keywords):
                found.append(f"  {obj}: {ev.get('reason','')} — {ev.get('message','')[:100]}")

        detail = (
            f"kubectl get events -n {namespace} --context {aks_context}  (last 5m)\n"
            f"  DNS-related Warning events: "
            + ("\n" + "\n".join(found) if found else "none")
        )
        if found:
            return False, (
                detail + "\n  ✘ DNS-related Warning events still occurring post-chaos. "
                "App connection pool or retry backoff may not have cleared yet."
            )
        return True, detail + "\n  ✔ No DNS-related Warning events in last 5m"
    checks["No DNS Error Events Post-Chaos"] = _no_dns_events

    # ── 4. Pod readiness restored ─────────────────────────────────────────────
    # Rationale: DNS failures cause readiness probes that make HTTP/TCP calls to
    # downstream services to fail. After DNS recovery, readiness probes should
    # pass again within a few probe intervals.
    def _pods_ready():
        pods, err = _get_pods_json(aks_context, namespace, selector)
        if pods is None:
            return False, f"Could not query pods: {err}"
        not_ready = []
        for pod in pods:
            name = pod.get("metadata", {}).get("name", "?")
            conds = pod.get("status", {}).get("conditions", [])
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds)
            if not ready:
                not_ready.append(name)
        detail = (
            f"kubectl get pods -n {namespace} -l {selector} --context {aks_context}\n"
            f"  total={len(pods)}  not-ready={len(not_ready)}  {not_ready if not_ready else ''}"
        )
        if not_ready:
            return False, (
                detail + "\n  ✘ Pods not yet Ready after DNS chaos revert. "
                "Readiness probe may still be failing due to DNS-dependent downstream connections. "
                "Allow one probe cycle before re-checking."
            )
        return True, detail + "\n  ✔ All pods Ready after DNS chaos"
    checks["Pod Readiness Restored"] = _pods_ready

    return checks
