"""
Isolated-context Kubernetes Python client helpers.

This module is the single interception point used by every kubectl-shaped
helper across the platform (actions/aks_safety_checks.py, its own
_kubectl(); actions/aks_extended_checks.py, its own _kubectl(); and
actions/azure_aks_actions.py's raw subprocess.run(["kubectl", ...]) calls,
now routed through a shared _kubectl() there too). dispatch_kubectl() below
recognises each distinct kubectl invocation "shape" and serves it via the
Kubernetes Python client; anything unrecognised returns None so the caller can
use an optional kubectl compatibility fallback. This keeps one single
approach used everywhere it's safely possible:
  - `kubectl top pods|nodes|node` -> metrics.k8s.io via CustomObjectsApi
    (the same API kubectl top itself queries).
  - `kubectl drain` -> cordon (spec.unschedulable) + the Eviction API,
    replicating kubectl's own algorithm (skip DaemonSet/completed pods,
    retry PDB-blocked (429) evictions with backoff until --timeout,
    then wait for pods to actually terminate).
  - `kubectl config use-context/get-contexts/delete-context` -> direct
    kubeconfig YAML read/rewrite (set_current_kube_context() /
    list_kube_contexts() / delete_kube_context() below), since kubeconfig
    is just a local YAML file with no cluster API or server-side write
    endpoint involved.
The kubectl executable is optional. It remains useful for manual debugging and
as a compatibility fallback for unsupported command shapes.

Multi-context safety
---------------------
kubernetes.config.load_kube_config(context=X) mutates a *global* default
client.Configuration singleton unless you pass client_configuration=<own
instance>. This platform can hold many AKS cluster/subscription contexts
active in one session, so every call here builds (and caches) its own
private Configuration + ApiClient pair per kube-context — no shared/global
client state is ever touched, so switching between contexts cannot leak
state from one cluster into a call against another.

Kubectl-compatible output shape
--------------------------------
get_pods()/get_deployment() return plain dicts produced via
ApiClient.sanitize_for_serialization(), which follows the same OpenAPI
attribute_map the generated models use — i.e. camelCase keys identical to
`kubectl get ... -o json` (e.g. "containerStatuses", "restartCount",
"nodeName"). This means existing dict-parsing check logic written against
kubectl's raw JSON output works unchanged against these results.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.stream import stream as _ws_stream
from kubernetes.utils import parse_quantity

_lock = threading.Lock()
_client_cache: dict[str, client.ApiClient] = {}


def register_api_client(context: str, api_client: client.ApiClient) -> None:
    """Bind an externally selected cluster client to one Kubernetes context."""
    if context and api_client is not None:
        _client_cache[context] = api_client


def _get_api_client(context: str) -> client.ApiClient:
    """Return a cached, isolated ApiClient for the given kube-context."""
    cached = _client_cache.get(context)
    if cached is not None:
        return cached
    with _lock:
        cached = _client_cache.get(context)
        if cached is not None:
            return cached
        cfg = client.Configuration()
        config.load_kube_config(context=context, client_configuration=cfg)
        api_client = client.ApiClient(cfg)
        _client_cache[context] = api_client
        return api_client


def get_pods(
    context: str,
    namespace: str,
    label_selector: str = "",
    field_selector: str = "",
) -> tuple[list | None, str | None]:
    """
    List pods via the Kubernetes Python client.

    Returns (pods, error):
      - (list_of_pod_dicts, None) on success — same shape as
        `kubectl get pods -o json` .items (camelCase keys).
      - (None, error_message) on failure.
    """
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)
        result = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector or None,
            field_selector=field_selector or None,
        )
        items = api_client.sanitize_for_serialization(result).get("items", [])
        return items, None
    except ApiException as exc:
        return None, f"Kubernetes API error listing pods: {exc.reason or exc}"
    except Exception as exc:  # noqa: BLE001 - surfaced as a check failure, not a crash
        return None, f"Kubernetes client error listing pods: {exc}"


def get_deployment(
    context: str,
    namespace: str,
    name: str,
) -> tuple[dict | None, str | None]:
    """
    Read a single Deployment via the Kubernetes Python client.

    Returns (deployment_dict, error):
      - (dict, None) on success — same shape as `kubectl get deployment NAME -o json`.
      - (None, "not found") if the deployment doesn't exist.
      - (None, error_message) on any other failure.
    """
    try:
        api_client = _get_api_client(context)
        apps_v1 = client.AppsV1Api(api_client)
        result = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        return api_client.sanitize_for_serialization(result), None
    except ApiException as exc:
        if exc.status == 404:
            return None, "not found"
        return None, f"Kubernetes API error getting deployment: {exc.reason or exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"Kubernetes client error getting deployment: {exc}"


def _kubeconfig_path() -> str:
    """Resolve the kubeconfig file kubectl itself would read/write, honouring
    KUBECONFIG (first entry, mirroring kubectl's own write target when the
    variable lists multiple paths) and falling back to ~/.kube/config."""
    import os

    kubeconfig_env = os.environ.get("KUBECONFIG")
    if kubeconfig_env:
        # Accept both separators. This also handles kubeconfig values
        # produced using Unix-style ':' on Windows.
        first_entry = re.split(r"[;:]", kubeconfig_env, maxsplit=1)[0]
        return first_entry

    return os.path.expanduser("~/.kube/config")


def list_kube_contexts() -> list[str]:
    """
    List kubeconfig context names — no-kubectl equivalent of
    `kubectl config get-contexts --output name`.

    Context listing is a pure local kubeconfig file read (no cluster API
    call involved), so kubernetes.config.list_kube_config_contexts() is a
    lossless, subprocess-free replacement. Returns [] on any failure
    (missing/unreadable kubeconfig etc.), matching the original subprocess
    call's fallback behaviour.
    """
    try:
        contexts, _active = config.list_kube_config_contexts()
    except Exception:  # noqa: BLE001
        return []
    return [c["name"] for c in contexts if c.get("name")]


def delete_kube_context(name: str) -> bool:
    """
    Remove one context entry from the local kubeconfig file — no-kubectl
    equivalent of `kubectl config delete-context <name>`.

    Mirrors kubectl's own semantics: only the matching entry under
    `contexts:` is removed (associated `clusters:`/`users:` entries are left
    untouched since they may be shared by other contexts, exactly as
    kubectl leaves them), and `current-context` is cleared if it pointed at
    the deleted context. Returns True on success, False if the context
    wasn't found or the kubeconfig couldn't be safely read/rewritten (in
    which case the caller should fall back to the kubectl subprocess path).
    """
    import yaml

    path = _kubeconfig_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001
        return False

    contexts = data.get("contexts") or []
    remaining = [c for c in contexts if c.get("name") != name]
    if len(remaining) == len(contexts):
        return False  # context not present — nothing to delete

    data["contexts"] = remaining
    if data.get("current-context") == name:
        data["current-context"] = ""

    try:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
    except Exception:  # noqa: BLE001
        return False
    return True


def set_current_kube_context(name: str) -> bool:
    """
    Set kubeconfig's `current-context` field — no-kubectl equivalent of
    `kubectl config use-context <name>`.

    Matches kubectl's own validation: refuses (returns False) if `name`
    isn't an existing context entry, same as the real command erroring with
    "no context exists with the name". Returns True on success, False on
    any failure (unknown context, unreadable/unwritable kubeconfig) — the
    caller should fall back to the kubectl subprocess path in that case.
    """
    import yaml

    path = _kubeconfig_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001
        return False

    contexts = data.get("contexts") or []
    if not any(c.get("name") == name for c in contexts):
        return False  # kubectl errors the same way for an unknown context

    data["current-context"] = name
    try:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
    except Exception:  # noqa: BLE001
        return False
    return True


# Supported kubectl operations use the Kubernetes client. Unknown operations
# fall back to the subprocess implementation to preserve kubectl semantics.

_CHAOS_GROUP = "chaos-mesh.org"
_CHAOS_VERSION = "v1alpha1"
_CHAOS_KINDS = frozenset({
    "networkchaos", "podchaos", "dnschaos", "httpchaos",
    "timechaos", "iochaos", "stresschaos", "kernelchaos",
})


class KubectlResult:
    """Minimal subprocess.CompletedProcess look-alike."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ok(stdout: str = "") -> KubectlResult:
    return KubectlResult(0, stdout, "")


def _fail(stderr: str) -> KubectlResult:
    return KubectlResult(1, "", stderr)


def run_kubernetes_command(
    args,
    context=None,
    *,
    timeout=None,
    request_timeout=None,
    prefix_options=False,
):
    """Use the Python client first and kubectl only as an optional fallback."""
    dispatch_error = None
    try:
        result = dispatch_kubectl(tuple(args), context)
        if result is not None:
            return result
    except Exception as exc:  # noqa: BLE001
        dispatch_error = exc

    command = ["kubectl"]
    request_option = f"--request-timeout={request_timeout}" if request_timeout else None
    if prefix_options:
        if request_option:
            command.append(request_option)
        if context:
            command.extend(["--context", context])
        command.extend(args)
    else:
        command.extend(args)
        if request_option:
            command.append(request_option)
        if context:
            command.extend(["--context", context])
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        return KubectlResult(
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
        )
    except FileNotFoundError:
        detail = f" Python client error: {dispatch_error}" if dispatch_error else ""
        return KubectlResult(
            127,
            "",
            "Kubernetes operation is unsupported by the Python client and the optional "
            f"kubectl compatibility fallback is not installed.{detail}",
        )
    except subprocess.TimeoutExpired as exc:
        return KubectlResult(124, str(exc.stdout or ""), "Kubernetes operation timed out.")
    except OSError as exc:
        return KubectlResult(126, "", f"Could not execute kubectl fallback: {exc}")


class _JsonPathUnsupported(Exception):
    """Raised internally when a jsonpath expression uses syntax this
    resolver doesn't implement, so callers can fall back to the real
    kubectl subprocess instead of silently returning an empty/wrong
    result."""


_FILTER_RE = re.compile(
    r'^\?\(@\.([a-zA-Z0-9_-]+)==(?:"([^"]*)"|\'([^\']*)\'|([^)]+))\)$'
)


def _resolve_path_steps(expr: str):
    r"""Tokenize a bare dotted-path expression (no surrounding braces, no
    'range'/'end') into ('field', name) / ('index', spec) steps, where spec
    is '*', a bare (possibly negative) integer, or a
    '?(@.key=="value")' filter clause. Raises _JsonPathUnsupported on any
    character sequence it doesn't recognise (e.g. a `\.`-escaped literal
    dot inside a label key), rather than silently truncating the path."""
    steps = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch == ".":
            i += 1
            continue
        if ch == "[":
            j = expr.find("]", i)
            if j == -1:
                raise _JsonPathUnsupported(f"unterminated '[' in: {expr!r}")
            steps.append(("index", expr[i + 1:j]))
            i = j + 1
            continue
        field = []
        while i < n and expr[i] not in ".[":
            if expr[i] == "\\" and i + 1 < n:
                i += 1
            field.append(expr[i])
            i += 1
        steps.append(("field", "".join(field)))
    return steps


def _apply_index(values, spec: str):
    if spec == "*":
        out = []
        for v in values:
            if isinstance(v, list):
                out.extend(v)
        return out
    if re.fullmatch(r"-?\d+", spec):
        idx = int(spec)
        out = []
        for v in values:
            if isinstance(v, list) and -len(v) <= idx < len(v):
                out.append(v[idx])
        return out
    m = _FILTER_RE.match(spec)
    if m:
        key = m.group(1)
        target = next(g for g in m.groups()[1:] if g is not None)
        out = []
        for v in values:
            if isinstance(v, list):
                out.extend(
                    item for item in v
                    if isinstance(item, dict) and str(item.get(key)) == str(target)
                )
        return out
    raise _JsonPathUnsupported(f"unsupported index/filter clause: [{spec}]")


def _resolve_path(expr: str, obj):
    """Resolve a bare dotted-path expression (already stripped of any
    surrounding braces) against obj, returning a list of resolved values
    (possibly empty — a legitimately empty match, not a parse failure)."""
    values = [obj]
    for kind, val in _resolve_path_steps(expr):
        if kind == "field":
            values = [v[val] for v in values if isinstance(v, dict) and v.get(val) is not None]
        else:
            values = _apply_index(values, val)
    return values


def _decode_quoted_literal(token: str):
    """token like '"\\t"' -> an actual tab character, matching kubectl's
    own escape handling for quoted literals inside jsonpath templates.
    Returns None if token isn't a quoted literal (i.e. it's a field path)."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        inner = token[1:-1]
        return (
            inner.replace("\\n", "\n")
                 .replace("\\t", "\t")
                 .replace('\\"', '"')
                 .replace("\\\\", "\\")
        )
    return None


_RANGE_RE = re.compile(r"^\{range\s+([^}]+)\}(.*)\{end\}$", re.DOTALL)
_BRACE_TOKEN_RE = re.compile(r"\{([^{}]*)\}")


def _jsonpath_get(expr: str, obj) -> str | None:
    """
    Minimal kubectl-style jsonpath resolver.

    Supports dotted field paths, [N]/[*] indexing, [?(@.key=="val")]
    filters, and {range EXPR}...{end} iteration templates — covering every
    shape this codebase's `-o jsonpath=...` calls actually use. Returns
    None (never an empty string as a stand-in) when the expression uses
    syntax this resolver doesn't recognise, so the caller can fall back to
    the real kubectl subprocess instead of silently reporting incorrect
    "no data" results.
    """
    expr = expr.strip()
    try:
        m = _RANGE_RE.match(expr)
        if expr.startswith("{range") and m is None:
            raise _JsonPathUnsupported(f"malformed range expression: {expr!r}")
        if m:
            range_expr, body = m.group(1).strip(), m.group(2)
            items = _resolve_path(range_expr, obj)
            body_tokens = []
            pos = 0
            for tm in _BRACE_TOKEN_RE.finditer(body):
                if tm.start() != pos:
                    raise _JsonPathUnsupported(f"unexpected text in range body: {body!r}")
                token = tm.group(1)
                literal = _decode_quoted_literal(token)
                body_tokens.append(("literal", literal) if literal is not None else ("path", token))
                pos = tm.end()
            if pos != len(body):
                raise _JsonPathUnsupported(f"unterminated range body: {body!r}")
            out = []
            for item in items:
                for kind, val in body_tokens:
                    if kind == "literal":
                        out.append(val)
                    else:
                        resolved = _resolve_path(val, item)
                        out.append(" ".join(str(v) for v in resolved if v is not None))
            return "".join(out)

        if expr.startswith("{") and expr.endswith("}"):
            expr = expr[1:-1]
        values = _resolve_path(expr, obj)
        return " ".join(str(v) for v in values if v is not None)
    except _JsonPathUnsupported:
        return None


def _pod_table_line(pod: dict) -> str:
    """Approximate `kubectl get pods --no-headers` columns actually parsed
    by callers: NAME READY STATUS RESTARTS AGE."""
    meta = pod.get("metadata", {})
    status = pod.get("status", {})
    statuses = status.get("containerStatuses", []) or []
    ready = sum(1 for cs in statuses if cs.get("ready"))
    total_c = len(statuses)
    restarts = sum(cs.get("restartCount", 0) for cs in statuses)
    phase = status.get("phase", "Unknown")
    name = meta.get("name", "?")
    return f"{name}\t{ready}/{total_c}\t{phase}\t{restarts}\t<age>"


def _custom_columns_get(spec: str, rows, no_headers: bool) -> str | None:
    """
    Render kubectl-style `-o custom-columns=COL1:PATH1,COL2:PATH2,...`.

    Each PATH is a bare dotted jsonpath (no surrounding braces) resolved
    per-item via _resolve_path(); multiple resolved values for one column
    are comma-joined (matching kubectl), a column with no match renders as
    "<none>" (also matching kubectl) so column count/position never shifts
    for callers that split() each output line. Prepends a header row of
    column names unless no_headers is set, matching real kubectl.

    Returns None — never a wrong or partial rendering — if any column spec
    can't be parsed or a path uses syntax _resolve_path() doesn't support,
    so the caller falls back to the real kubectl subprocess.
    """
    columns = []
    for col in spec.split(","):
        if ":" not in col:
            return None
        name, path = col.split(":", 1)
        name, path = name.strip(), path.strip()
        if not name or not path:
            return None
        columns.append((name, path))
    try:
        lines = [] if no_headers else [" ".join(name for name, _ in columns)]
        for item in rows:
            cells = []
            for _, path in columns:
                values = _resolve_path(path, item)
                cells.append(",".join(str(v) for v in values) if values else "<none>")
            lines.append(" ".join(cells))
        return "\n".join(lines)
    except _JsonPathUnsupported:
        return None


def _apply_output(items, single: bool, parsed: dict, table_line_fn=None) -> KubectlResult | None:
    """Render a resolved object/list as kubectl would for -o json /
    jsonpath=... / custom-columns=... / --no-headers / plain (existence-only).
    Returns None if a jsonpath=... or custom-columns=... expression uses
    syntax this dispatcher can't resolve, signalling every caller to fall
    back to the real kubectl subprocess instead of reporting a false empty
    or wrongly-shaped result."""
    output = parsed.get("output")
    if output == "json":
        payload = items if single else {"items": items}
        return _ok(json.dumps(payload))
    if output and output.startswith("jsonpath="):
        expr = output[len("jsonpath="):]
        target = items if single else {"items": items}
        resolved = _jsonpath_get(expr, target)
        if resolved is None:
            return None
        return _ok(resolved)
    if output and output.startswith("custom-columns="):
        spec = output[len("custom-columns="):]
        rows = [items] if single else items
        resolved = _custom_columns_get(spec, rows, bool(parsed.get("no_headers")))
        if resolved is None:
            return None
        return _ok(resolved)
    if parsed.get("no_headers"):
        rows = [items] if single else items
        line_fn = table_line_fn or (lambda o: o.get("metadata", {}).get("name", "?"))
        return _ok("\n".join(line_fn(o) for o in rows))
    # No -o / no --no-headers: kubectl's human table output is never parsed
    # by any caller in this codebase for these bare-existence checks — only
    # returncode matters, so an empty body is sufficient.
    return _ok("")


def _parse_get_args(args) -> dict | None:
    """Parse the flag/positional portion of a `kubectl get ...` invocation.
    Returns None for any flag shape this dispatcher doesn't recognise, which
    signals the caller to fall back to the kubectl subprocess path."""
    parsed = {
        "name": None, "namespace": None, "all_namespaces": False,
        "selector": None, "field_selector": None, "output": None,
        "no_headers": False,
    }
    positional = []
    i = 0
    n = len(args)
    while i < n:
        a = args[i]
        if a in ("-n", "--namespace") and i + 1 < n:
            parsed["namespace"] = args[i + 1]; i += 2; continue
        if a == "--all-namespaces":
            parsed["all_namespaces"] = True; i += 1; continue
        if a in ("-l", "--selector") and i + 1 < n:
            parsed["selector"] = args[i + 1]; i += 2; continue
        if a == "--field-selector" and i + 1 < n:
            parsed["field_selector"] = args[i + 1]; i += 2; continue
        if a in ("-o", "--output") and i + 1 < n:
            parsed["output"] = args[i + 1]; i += 2; continue
        if a == "--no-headers":
            parsed["no_headers"] = True; i += 1; continue
        if a.startswith("-"):
            return None  # unrecognised flag -> safe fallback to subprocess
        positional.append(a)
        i += 1
    parsed["name"] = positional[0] if positional else None
    return parsed


def _dispatch_get(resource: str, rest, context: str) -> KubectlResult | None:
    parsed = _parse_get_args(rest)
    if parsed is None:
        return None
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)

        if resource in ("pods", "pod"):
            if parsed["name"] and not parsed["namespace"]:
                return None
            if parsed["name"]:
                obj = v1.read_namespaced_pod(parsed["name"], parsed["namespace"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            if parsed["all_namespaces"]:
                result = v1.list_pod_for_all_namespaces(
                    label_selector=parsed["selector"] or None,
                    field_selector=parsed["field_selector"] or None,
                )
            else:
                if not parsed["namespace"]:
                    return None
                result = v1.list_namespaced_pod(
                    namespace=parsed["namespace"],
                    label_selector=parsed["selector"] or None,
                    field_selector=parsed["field_selector"] or None,
                )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed, table_line_fn=_pod_table_line)

        if resource in ("deployment", "deployments", "deploy"):
            apps_v1 = client.AppsV1Api(api_client)
            if parsed["name"]:
                if not parsed["namespace"]:
                    return None
                obj = apps_v1.read_namespaced_deployment(parsed["name"], parsed["namespace"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            if parsed["all_namespaces"]:
                result = apps_v1.list_deployment_for_all_namespaces(
                    label_selector=parsed["selector"] or None
                )
            elif parsed["namespace"]:
                result = apps_v1.list_namespaced_deployment(
                    parsed["namespace"], label_selector=parsed["selector"] or None
                )
            else:
                return None
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in (
            "daemonset", "daemonsets", "ds", "statefulset", "statefulsets", "sts"
        ):
            apps_v1 = client.AppsV1Api(api_client)
            daemonset = resource in ("daemonset", "daemonsets", "ds")
            if parsed["name"]:
                if not parsed["namespace"]:
                    return None
                method = (
                    apps_v1.read_namespaced_daemon_set
                    if daemonset
                    else apps_v1.read_namespaced_stateful_set
                )
                obj = method(parsed["name"], parsed["namespace"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            if not parsed["namespace"]:
                return None
            method = (
                apps_v1.list_namespaced_daemon_set
                if daemonset
                else apps_v1.list_namespaced_stateful_set
            )
            result = method(
                parsed["namespace"], label_selector=parsed["selector"] or None
            )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("replicaset", "replicasets", "rs"):
            if not parsed["namespace"]:
                return None
            apps_v1 = client.AppsV1Api(api_client)
            if parsed["name"]:
                obj = apps_v1.read_namespaced_replica_set(parsed["name"], parsed["namespace"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            result = apps_v1.list_namespaced_replica_set(
                namespace=parsed["namespace"], label_selector=parsed["selector"] or None,
            )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("nodes", "node"):
            if parsed["name"]:
                obj = v1.read_node(parsed["name"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            result = v1.list_node(
                label_selector=parsed["selector"] or None,
                field_selector=parsed["field_selector"] or None,
            )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("service", "services", "svc"):
            if parsed["name"]:
                if not parsed["namespace"]:
                    return None
                obj = v1.read_namespaced_service(parsed["name"], parsed["namespace"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            if not parsed["namespace"]:
                return None
            result = v1.list_namespaced_service(
                namespace=parsed["namespace"], label_selector=parsed["selector"] or None,
            )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("endpoints", "ep"):
            if not (parsed["name"] and parsed["namespace"]):
                return None
            obj = v1.read_namespaced_endpoints(parsed["name"], parsed["namespace"])
            return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)

        if resource in ("pdb", "poddisruptionbudget", "poddisruptionbudgets"):
            policy_v1 = client.PolicyV1Api(api_client)
            if parsed["all_namespaces"]:
                result = policy_v1.list_pod_disruption_budget_for_all_namespaces()
            elif parsed["namespace"]:
                result = policy_v1.list_namespaced_pod_disruption_budget(
                    namespace=parsed["namespace"]
                )
            else:
                return None
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("pv", "persistentvolume", "persistentvolumes"):
            if parsed["name"]:
                obj = v1.read_persistent_volume(parsed["name"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            result = v1.list_persistent_volume(
                label_selector=parsed["selector"] or None,
                field_selector=parsed["field_selector"] or None,
            )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in (
            "mutatingwebhookconfiguration", "mutatingwebhookconfigurations"
        ):
            admission = client.AdmissionregistrationV1Api(api_client)
            if parsed["name"]:
                obj = admission.read_mutating_webhook_configuration(parsed["name"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            result = admission.list_mutating_webhook_configuration()
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("certificate", "certificates"):
            if not parsed["namespace"]:
                return None
            custom = client.CustomObjectsApi(api_client)
            result = custom.list_namespaced_custom_object(
                "cert-manager.io", "v1", parsed["namespace"], "certificates"
            )
            return _apply_output(result.get("items", []), False, parsed)

        if resource in ("events", "event"):
            if not parsed["namespace"]:
                return None
            result = v1.list_namespaced_event(
                namespace=parsed["namespace"], field_selector=parsed["field_selector"] or None,
            )
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("namespace", "namespaces", "ns"):
            if parsed["name"]:
                obj = v1.read_namespace(parsed["name"])
                return _apply_output(api_client.sanitize_for_serialization(obj), True, parsed)
            result = v1.list_namespace()
            items = api_client.sanitize_for_serialization(result).get("items", [])
            return _apply_output(items, False, parsed)

        if resource in ("crd", "customresourcedefinition", "customresourcedefinitions"):
            # Only ever used as a bare existence check in this codebase.
            if not parsed["name"] or parsed["output"] or parsed["no_headers"]:
                return None
            ext_v1 = client.ApiextensionsV1Api(api_client)
            try:
                ext_v1.read_custom_resource_definition(parsed["name"])
                return _ok("")
            except ApiException as exc:
                if exc.status == 404:
                    return _fail("not found")
                return _fail(exc.reason or str(exc))

        if resource in _CHAOS_KINDS:
            custom = client.CustomObjectsApi(api_client)
            plural = resource
            if parsed["name"]:
                if not parsed["namespace"]:
                    return None
                obj = custom.get_namespaced_custom_object(
                    _CHAOS_GROUP, _CHAOS_VERSION, parsed["namespace"], plural, parsed["name"],
                )
                return _apply_output(obj, True, parsed)
            if parsed["all_namespaces"]:
                result = custom.list_cluster_custom_object(_CHAOS_GROUP, _CHAOS_VERSION, plural)
            else:
                if not parsed["namespace"]:
                    return None
                result = custom.list_namespaced_custom_object(
                    _CHAOS_GROUP, _CHAOS_VERSION, parsed["namespace"], plural,
                )
            items = result.get("items", [])
            return _apply_output(items, False, parsed)

        return None  # unrecognised resource kind -> fallback
    except ApiException as exc:
        if exc.status == 404:
            return _fail("not found")
        return _fail(f"Kubernetes API error: {exc.reason or exc}")
    except Exception:  # noqa: BLE001 - let caller fall back to subprocess
        return None


def _parse_delete_args(args) -> dict | None:
    """Parse a `kubectl delete <kind> [name] [flags]` invocation. Returns
    None for any flag this dispatcher doesn't recognise (safe fallback)."""
    parsed = {
        "name": None, "namespace": None, "all": False,
        "ignore_not_found": False,
    }
    positional = []
    i = 0
    n = len(args)
    while i < n:
        a = args[i]
        if a in ("-n", "--namespace") and i + 1 < n:
            parsed["namespace"] = args[i + 1]; i += 2; continue
        if a == "--all":
            parsed["all"] = True; i += 1; continue
        if a == "--ignore-not-found":
            parsed["ignore_not_found"] = True; i += 1; continue
        if a == "--force":
            i += 1; continue  # no behavioural difference for the API delete call
        if a.startswith("--wait="):
            i += 1; continue  # collection delete here is already synchronous
        if a.startswith("--request-timeout="):
            i += 1; continue  # request timeout is set via the shared ApiClient
        if a.startswith("--grace-period="):
            i += 1; continue  # handled below via grace_period_seconds
        if a.startswith("-"):
            return None
        positional.append(a)
        i += 1
    parsed["name"] = positional[0] if positional else None
    parsed["grace_period_seconds"] = next(
        (int(a.split("=", 1)[1]) for a in args if a.startswith("--grace-period=")), None,
    )
    return parsed


def _dispatch_delete(resource: str, rest, context: str) -> KubectlResult | None:
    if resource not in _CHAOS_KINDS and resource not in ("pod", "pods"):
        return None
    parsed = _parse_delete_args(rest)
    if parsed is None or not parsed["namespace"]:
        return None
    try:
        api_client = _get_api_client(context)

        if resource in ("pod", "pods"):
            if not parsed["name"]:
                return None  # bulk pod delete never used in this codebase
            v1 = client.CoreV1Api(api_client)
            kwargs = {}
            if parsed["grace_period_seconds"] is not None:
                kwargs["grace_period_seconds"] = parsed["grace_period_seconds"]
            v1.delete_namespaced_pod(parsed["name"], parsed["namespace"], **kwargs)
            return _ok("")

        # Chaos-mesh CRD kinds
        custom = client.CustomObjectsApi(api_client)
        if parsed["name"] and not parsed["all"]:
            custom.delete_namespaced_custom_object(
                _CHAOS_GROUP, _CHAOS_VERSION, parsed["namespace"], resource, parsed["name"],
            )
            return _ok("")
        custom.delete_collection_namespaced_custom_object(
            _CHAOS_GROUP, _CHAOS_VERSION, parsed["namespace"], resource,
        )
        return _ok("")
    except ApiException as exc:
        if exc.status == 404:
            if parsed["ignore_not_found"] or parsed["all"]:
                return _ok("")  # already gone -> same as kubectl's success-on-empty
            return _fail("not found")
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_exec(rest, context: str) -> KubectlResult | None:
    # Every call site in this codebase is exactly:
    #   _kubectl("exec", <pod>, "-n", <namespace>, "--", <cmd...>, context=...)
    if len(rest) < 4 or rest[1] not in ("-n", "--namespace") or rest[3] != "--":
        return None
    pod, _, namespace, _sep, *cmd = rest
    if not cmd:
        return None
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)
        ws = _ws_stream(
            v1.connect_get_namespaced_pod_exec,
            pod, namespace,
            command=cmd,
            stderr=True, stdin=False, stdout=True, tty=False,
            _preload_content=False,
        )
        ws.run_forever(timeout=15)
        stdout = ws.read_stdout(timeout=1) or ""
        stderr = ws.read_stderr(timeout=1) or ""
        rc = ws.returncode
        ws.close()
        return KubectlResult(rc if rc is not None else 0, stdout, stderr)
    except ApiException as exc:
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001 - let caller fall back to kubectl exec
        return None


def _dispatch_patch(resource: str, rest, context: str) -> KubectlResult | None:
    """
    kubectl patch <kind> <name> -n <ns> --type=json -p=<json> [--context ctx]

    Only the JSON-Patch (RFC 6902) form is used anywhere in this codebase
    (finalizer removal, deployment securityContext restore), so that is the
    only patch-type this dispatcher recognises; anything else falls back.
    """
    if resource not in _CHAOS_KINDS and resource not in (
        "deployment", "deployments", "deploy", "node", "nodes",
    ):
        return None
    if len(rest) < 2:
        return None
    name = rest[0]
    namespace = None
    patch_type = None
    patch_body = None
    i = 1
    n = len(rest)
    while i < n:
        a = rest[i]
        if a in ("-n", "--namespace") and i + 1 < n:
            namespace = rest[i + 1]; i += 2; continue
        if a == "--type=json" or a == "--type=application/json-patch+json":
            patch_type = "json"; i += 1; continue
        if a.startswith("-p="):
            try:
                patch_body = json.loads(a[len("-p="):])
            except ValueError:
                return None
            i += 1; continue
        if a.startswith("-"):
            return None
        return None  # unexpected extra positional
    if patch_type != "json" or patch_body is None:
        return None  # only JSON-Patch is used/supported
    if resource not in ("node", "nodes") and not namespace:
        return None
    try:
        api_client = _get_api_client(context)
        if resource in _CHAOS_KINDS:
            custom = client.CustomObjectsApi(api_client)
            custom.patch_namespaced_custom_object(
                _CHAOS_GROUP, _CHAOS_VERSION, namespace, resource, name, patch_body,
                _content_type="application/json-patch+json",
            )
            return _ok("")
        if resource in ("deployment", "deployments", "deploy"):
            apps_v1 = client.AppsV1Api(api_client)
            apps_v1.patch_namespaced_deployment(
                name, namespace, patch_body, _content_type="application/json-patch+json",
            )
            return _ok("")
        if resource in ("node", "nodes"):
            v1 = client.CoreV1Api(api_client)
            v1.patch_node(name, patch_body, _content_type="application/json-patch+json")
            return _ok("")
    except ApiException as exc:
        if exc.status == 404:
            return _fail("not found")
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_label(resource: str, rest, context: str) -> KubectlResult | None:
    """
    kubectl label namespace <name> key=val [--overwrite] [--context ctx]
    kubectl label namespace <name> key-                  (removes the key)

    Only `namespace` labelling is used in this codebase.
    """
    if resource not in ("namespace", "namespaces", "ns"):
        return None
    if not rest:
        return None
    name, label_args = rest[0], rest[1:]
    label_ops = [a for a in label_args if a not in ("--overwrite",)]
    if len(label_ops) != 1:
        return None  # only single key=val / key- forms are used here
    label_expr = label_ops[0]
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)
        if label_expr.endswith("-"):
            key = label_expr[:-1]
            patch = {"metadata": {"labels": {key: None}}}
        elif "=" in label_expr:
            key, val = label_expr.split("=", 1)
            patch = {"metadata": {"labels": {key: val}}}
        else:
            return None
        v1.patch_namespace(name, patch)
        return _ok("")
    except ApiException as exc:
        if exc.status == 404:
            return _fail("not found")
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_taint(rest, context: str) -> KubectlResult | None:
    """
    kubectl taint nodes <node> key=value:Effect[-] [--overwrite] [--context ctx]

    A trailing '-' on the taint expression removes a matching taint;
    otherwise the taint is added/updated (read-modify-write on spec.taints,
    matching by key+effect the same way kubectl does).
    """
    if len(rest) < 2 or rest[0] not in ("node", "nodes"):
        return None
    node_name = rest[1]
    taint_args = [a for a in rest[2:] if a != "--overwrite"]
    if len(taint_args) != 1:
        return None
    expr = taint_args[0]
    remove = expr.endswith("-")
    if remove:
        expr = expr[:-1]
    try:
        key_value, effect = expr.rsplit(":", 1)
    except ValueError:
        return None
    if "=" in key_value:
        key, value = key_value.split("=", 1)
    else:
        key, value = key_value, None
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)
        node = v1.read_node(node_name)
        taints = list(node.spec.taints or [])
        taints = [t for t in taints if not (t.key == key and t.effect == effect)]
        if not remove:
            taints.append(client.V1Taint(key=key, value=value, effect=effect))
        v1.patch_node(node_name, {"spec": {"taints": [
            {"key": t.key, "value": t.value, "effect": t.effect} for t in taints
        ]}})
        return _ok("")
    except ApiException as exc:
        if exc.status == 404:
            return _fail("not found")
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_cordon(uncordon: bool, rest, context: str) -> KubectlResult | None:
    """kubectl cordon|uncordon <node> [--context ctx]"""
    if len(rest) != 1:
        return None
    node_name = rest[0]
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)
        v1.patch_node(node_name, {"spec": {"unschedulable": not uncordon}})
        return _ok("")
    except ApiException as exc:
        if exc.status == 404:
            return _fail("not found")
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_rollout(sub: str, rest, context: str) -> KubectlResult | None:
    """
    kubectl rollout restart deployment/<name> -n <ns> [--context ctx]
    kubectl rollout status  deployment/<name> -n <ns> [--context ctx] --timeout=Ns
    """
    if not rest or not rest[0].startswith("deployment/"):
        return None
    name = rest[0].split("/", 1)[1]
    namespace = None
    timeout_s = 60
    i = 1
    n = len(rest)
    while i < n:
        a = rest[i]
        if a in ("-n", "--namespace") and i + 1 < n:
            namespace = rest[i + 1]; i += 2; continue
        if a.startswith("--timeout="):
            raw = a[len("--timeout="):]
            try:
                timeout_s = int(raw[:-1]) if raw.endswith("s") else int(raw)
            except ValueError:
                pass
            i += 1; continue
        if a.startswith("-"):
            return None
        return None
    if not namespace:
        return None
    try:
        import time as _time
        api_client = _get_api_client(context)
        apps_v1 = client.AppsV1Api(api_client)
        if sub == "restart":
            from datetime import datetime, timezone
            patch = {"spec": {"template": {"metadata": {"annotations": {
                "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat(),
            }}}}}
            apps_v1.patch_namespaced_deployment(name, namespace, patch)
            return _ok("")
        if sub == "status":
            deadline = _time.time() + timeout_s
            while True:
                dep = apps_v1.read_namespaced_deployment(name, namespace)
                spec_replicas = dep.spec.replicas or 0
                status = dep.status
                if (
                    (status.updated_replicas or 0) >= spec_replicas
                    and (status.replicas or 0) == spec_replicas
                    and (status.available_replicas or 0) >= spec_replicas
                    and (status.observed_generation or 0) >= (dep.metadata.generation or 0)
                ):
                    return _ok(f'deployment "{name}" successfully rolled out\n')
                if _time.time() >= deadline:
                    return _fail(f"timed out waiting for rollout of deployment/{name}")
                _time.sleep(2)
        return None
    except ApiException as exc:
        if exc.status == 404:
            return _fail("not found")
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_create(resource: str, rest, context: str) -> KubectlResult | None:
    """kubectl create namespace <name> [--context ctx]"""
    if resource not in ("namespace", "namespaces", "ns") or len(rest) != 1:
        return None
    name = rest[0]
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)
        v1.create_namespace({"metadata": {"name": name}})
        return _ok("")
    except ApiException as exc:
        if exc.status == 409:
            return _fail("already exists")  # matches kubectl create's non-idempotent behaviour
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_apply(rest, context: str) -> KubectlResult | None:
    """
    kubectl apply -f <path-to-json-manifest>

    Every manifest applied in this codebase is a plain JSON file describing
    either a bare Pod or a chaos-mesh CRD (PodChaos, etc.) — never a
    multi-document YAML stream, Deployment, or other typed object. Create
    is tried first (matching the fact that every call site deletes/removes
    any pre-existing object of the same name immediately beforehand); a 409
    Conflict falls back to a replace, mirroring kubectl apply's upsert
    semantics for the narrow set of shapes actually used here.
    """
    if len(rest) != 2 or rest[0] != "-f":
        return None
    path = rest[1]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:  # noqa: BLE001 - unreadable/non-JSON file -> fallback
        return None
    kind = manifest.get("kind")
    metadata = manifest.get("metadata", {})
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    if not (kind and name and namespace):
        return None
    try:
        api_client = _get_api_client(context)
        if kind == "Pod":
            v1 = client.CoreV1Api(api_client)
            try:
                v1.create_namespaced_pod(namespace, manifest)
            except ApiException as exc:
                if exc.status != 409:
                    raise
                v1.replace_namespaced_pod(name, namespace, manifest)
            return _ok("")
        if kind.lower() in _CHAOS_KINDS:
            plural = kind.lower()
            custom = client.CustomObjectsApi(api_client)
            try:
                custom.create_namespaced_custom_object(
                    _CHAOS_GROUP, _CHAOS_VERSION, namespace, plural, manifest,
                )
            except ApiException as exc:
                if exc.status != 409:
                    raise
                custom.replace_namespaced_custom_object(
                    _CHAOS_GROUP, _CHAOS_VERSION, namespace, plural, name, manifest,
                )
            return _ok("")
        return None  # unrecognised kind -> fallback to real kubectl apply
    except ApiException as exc:
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _fmt_cpu_millicores(cores: float) -> str:
    """Render a core-count float the way kubectl top's tabular output does
    (always in millicores, e.g. 0.105 -> '105m')."""
    return f"{round(cores * 1000)}m"


def _fmt_mem_mi(bytes_val: float) -> str:
    """Render a byte count the way kubectl top's tabular output does
    (mebibytes, e.g. 134217728 -> '128Mi')."""
    return f"{round(bytes_val / (1024 ** 2))}Mi"


def _dispatch_top(rest, context: str) -> KubectlResult | None:
    """
    kubectl top pods -n <ns> [-l <selector>] [--containers] [--no-headers]
    kubectl top nodes [--no-headers]
    kubectl top node <name> [--no-headers]

    Sourced from the same metrics.k8s.io API (metrics-server) that kubectl
    top itself queries via CustomObjectsApi — not a reimplementation of
    metrics collection, just a different client for identical data. Node
    CPU/memory percentages are computed against each node's
    status.allocatable, matching kubectl's own calculation. Output is
    reconstructed as whitespace-separated text lines in kubectl's column
    order so every existing caller (which parses plain-text `kubectl top`
    output) keeps working completely unchanged.
    """
    if not rest:
        return None
    resource = rest[0]
    if resource not in ("pods", "nodes", "node"):
        return None  # unrecognised shape -> fallback to real kubectl top
    tail = rest[1:]

    namespace = None
    selector = None
    containers = False
    single_node_name = None
    i = 0
    while i < len(tail):
        a = tail[i]
        if a == "-n" and i + 1 < len(tail):
            namespace = tail[i + 1]; i += 2; continue
        if a == "-l" and i + 1 < len(tail):
            selector = tail[i + 1]; i += 2; continue
        if a == "--containers":
            containers = True; i += 1; continue
        if a == "--no-headers":
            i += 1; continue
        if resource == "node" and single_node_name is None and not a.startswith("-"):
            single_node_name = a; i += 1; continue
        return None  # unrecognised flag/arg -> fallback to real kubectl top

    try:
        api_client = _get_api_client(context)
        custom = client.CustomObjectsApi(api_client)

        if resource == "pods":
            if not namespace:
                return None
            result = custom.list_namespaced_custom_object(
                "metrics.k8s.io", "v1beta1", namespace, "pods",
                label_selector=selector or None,
            )
            lines = []
            for item in result.get("items", []):
                pod_name = item.get("metadata", {}).get("name", "")
                conts = item.get("containers", [])
                if containers:
                    for c in conts:
                        usage = c.get("usage", {})
                        cpu = _fmt_cpu_millicores(parse_quantity(usage.get("cpu", "0")))
                        mem = _fmt_mem_mi(parse_quantity(usage.get("memory", "0")))
                        lines.append(f"{pod_name}   {c.get('name', '')}   {cpu}   {mem}")
                else:
                    cpu_total = sum(parse_quantity(c.get("usage", {}).get("cpu", "0")) for c in conts)
                    mem_total = sum(parse_quantity(c.get("usage", {}).get("memory", "0")) for c in conts)
                    lines.append(
                        f"{pod_name}   {_fmt_cpu_millicores(cpu_total)}   {_fmt_mem_mi(mem_total)}"
                    )
            return _ok("\n".join(lines) + ("\n" if lines else ""))

        # resource in ("nodes", "node")
        if resource == "node" and single_node_name is None:
            return None
        v1 = client.CoreV1Api(api_client)
        if single_node_name:
            allocatable_by_name = {
                single_node_name: v1.read_node(single_node_name).status.allocatable
            }
            metrics_items = [
                custom.get_cluster_custom_object(
                    "metrics.k8s.io", "v1beta1", "nodes", single_node_name
                )
            ]
        else:
            nodes = v1.list_node()
            allocatable_by_name = {n.metadata.name: n.status.allocatable for n in nodes.items}
            metrics_items = custom.list_cluster_custom_object(
                "metrics.k8s.io", "v1beta1", "nodes"
            ).get("items", [])

        lines = []
        for item in metrics_items:
            name = item.get("metadata", {}).get("name", "")
            usage = item.get("usage", {})
            cpu_cores = parse_quantity(usage.get("cpu", "0"))
            mem_bytes = parse_quantity(usage.get("memory", "0"))
            allocatable = allocatable_by_name.get(name) or {}
            alloc_cpu = parse_quantity(allocatable.get("cpu", "0")) or None
            alloc_mem = parse_quantity(allocatable.get("memory", "0")) or None
            cpu_pct = round(cpu_cores / alloc_cpu * 100) if alloc_cpu else 0
            mem_pct = round(mem_bytes / alloc_mem * 100) if alloc_mem else 0
            lines.append(
                f"{name}   {_fmt_cpu_millicores(cpu_cores)}   {cpu_pct}%   "
                f"{_fmt_mem_mi(mem_bytes)}   {mem_pct}%"
            )
        return _ok("\n".join(lines) + ("\n" if lines else ""))
    except ApiException as exc:
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def _dispatch_config(rest, context: str) -> KubectlResult | None:
    """kubectl config use-context <name>"""
    if len(rest) != 2 or rest[0] != "use-context":
        return None  # get-contexts/delete-context are handled via
        # list_kube_contexts()/delete_kube_context() by their own callers,
        # not through this dispatcher (they aren't routed through _kubectl()).
    try:
        return _ok("") if set_current_kube_context(rest[1]) else _fail(
            f'no context exists with the name: "{rest[1]}"'
        )
    except Exception:  # noqa: BLE001
        return None


def _drain_evict_pod(core_v1, pod, grace_period_seconds) -> tuple[bool, str]:
    """Evict one pod via the Eviction API. Returns (evicted_or_already_gone, reason)."""
    from kubernetes.client import V1DeleteOptions, V1Eviction, V1ObjectMeta

    name = pod.metadata.name
    namespace = pod.metadata.namespace
    body = V1Eviction(
        metadata=V1ObjectMeta(name=name, namespace=namespace),
        delete_options=V1DeleteOptions(grace_period_seconds=grace_period_seconds),
    )
    try:
        core_v1.create_namespaced_pod_eviction(name, namespace, body)
        return True, ""
    except ApiException as exc:
        if exc.status == 404:
            return True, ""  # already gone
        if exc.status == 429:
            return False, "blocked by PodDisruptionBudget"
        return False, exc.reason or str(exc)


def _dispatch_drain(rest, context: str) -> KubectlResult | None:
    """
    kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --force
                  --timeout=<N>s

    Reimplements kubectl drain's algorithm against the same primitives
    kubectl itself uses (cordon via spec.unschedulable, then the Eviction
    API — which enforces PodDisruptionBudgets server-side exactly like a
    real `kubectl drain` would): mark the node unschedulable, list its
    pods, skip DaemonSet-owned and already-completed pods (kubectl drain
    can never evict either), evict everything else with retry-on-429
    (PDB-blocked) backoff until the timeout budget is exhausted, then wait
    for the evicted pods to actually terminate. Only the exact flag
    combination this platform ever calls with is recognised; anything else
    falls back to the real kubectl subprocess untouched.
    """
    import time

    if not rest:
        return None
    node_name = rest[0]
    ignore_daemonsets = False
    delete_emptydir_data = False
    force = False
    timeout_secs = 300  # kubectl's own default when --timeout is omitted
    for a in rest[1:]:
        if a == "--ignore-daemonsets":
            ignore_daemonsets = True
        elif a == "--delete-emptydir-data":
            delete_emptydir_data = True
        elif a == "--force":
            force = True
        elif a.startswith("--timeout="):
            raw = a[len("--timeout="):]
            try:
                timeout_secs = int(raw.rstrip("s")) if raw.rstrip("s") else 0
            except ValueError:
                return None
        else:
            return None  # unrecognised flag -> fallback to real kubectl drain

    # This platform's only caller always passes --ignore-daemonsets,
    # --delete-emptydir-data and --force together; require the same
    # combination here so behaviour stays identical rather than silently
    # draining more/less aggressively than the flags actually requested.
    if not (ignore_daemonsets and delete_emptydir_data and force):
        return None

    deadline = time.monotonic() + max(timeout_secs, 1)
    try:
        api_client = _get_api_client(context)
        v1 = client.CoreV1Api(api_client)

        # 1. Cordon (kubectl drain always cordons first).
        v1.patch_node(node_name, {"spec": {"unschedulable": True}})

        # 2. List pods scheduled on this node.
        pods = v1.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name}"
        ).items

        to_evict = []
        for pod in pods:
            phase = (pod.status.phase or "") if pod.status else ""
            if phase in ("Succeeded", "Failed"):
                continue  # kubectl drain deletes these directly, not via eviction
            owners = pod.metadata.owner_references or []
            if any(o.kind == "DaemonSet" for o in owners):
                continue  # never evicted by drain, even with --ignore-daemonsets
            to_evict.append(pod)

        pending = list(to_evict)
        while pending and time.monotonic() < deadline:
            still_pending = []
            for pod in pending:
                ok, _reason = _drain_evict_pod(v1, pod, grace_period_seconds=None)
                if not ok:
                    still_pending.append(pod)
            pending = still_pending
            if pending:
                time.sleep(2)

        if pending:
            names = ", ".join(f"{p.metadata.namespace}/{p.metadata.name}" for p in pending)
            return _fail(f"drain timed out, still pending eviction: {names}")

        # 3. Wait for evicted pods to actually terminate before returning,
        # matching kubectl drain's own wait-for-completion behaviour.
        remaining_names = {(p.metadata.namespace, p.metadata.name) for p in to_evict}
        while remaining_names and time.monotonic() < deadline:
            still_present = set()
            for ns, name in remaining_names:
                try:
                    v1.read_namespaced_pod(name, ns)
                    still_present.add((ns, name))
                except ApiException as exc:
                    if exc.status != 404:
                        still_present.add((ns, name))
            remaining_names = still_present
            if remaining_names:
                time.sleep(2)

        if remaining_names:
            names = ", ".join(f"{namespace}/{name}" for namespace, name in remaining_names)
            return _fail(f"drain timed out waiting for pod termination: {names}")

        return _ok(f'node/{node_name} drained\n')
    except ApiException as exc:
        return _fail(exc.reason or str(exc))
    except Exception:  # noqa: BLE001
        return None


def dispatch_kubectl(args, context: str) -> KubectlResult | None:
    """
    Entry point called from every _kubectl()-style helper across the
    platform (actions/aks_safety_checks.py, actions/aks_extended_checks.py,
    actions/azure_aks_actions.py).

    args is the tuple of positional arguments _kubectl() was called with
    (everything after the implicit `kubectl --request-timeout=... [--context
    ctx]` prefix, i.e. exactly what would follow `kubectl` on a real command
    line: ("get", "pods", "-n", "ns", "-o", "json"), etc.

    Returns a KubectlResult on success, or None if the invocation shape
    isn't (yet) recognised / handled, or anything raises - signalling the
    caller to fall back to the real kubectl subprocess.
    """
    if not args:
        return None
    verb, rest = args[0], list(args[1:])
    if verb == "get" and rest:
        return _dispatch_get(rest[0], rest[1:], context)
    if verb == "delete" and rest:
        return _dispatch_delete(rest[0], rest[1:], context)
    if verb == "exec" and rest:
        return _dispatch_exec(rest, context)
    if verb == "patch" and rest:
        return _dispatch_patch(rest[0], rest[1:], context)
    if verb == "label" and rest:
        return _dispatch_label(rest[0], rest[1:], context)
    if verb == "taint" and rest:
        return _dispatch_taint(rest, context)
    if verb == "cordon" and rest:
        return _dispatch_cordon(False, rest, context)
    if verb == "uncordon" and rest:
        return _dispatch_cordon(True, rest, context)
    if verb == "rollout" and rest:
        return _dispatch_rollout(rest[0], rest[1:], context)
    if verb == "create" and rest:
        return _dispatch_create(rest[0], rest[1:], context)
    if verb == "apply" and rest:
        return _dispatch_apply(rest, context)
    if verb == "top" and rest:
        return _dispatch_top(rest, context)
    if verb == "drain" and rest:
        return _dispatch_drain(rest, context)
    if verb == "config" and rest:
        return _dispatch_config(rest, context)
    return None
