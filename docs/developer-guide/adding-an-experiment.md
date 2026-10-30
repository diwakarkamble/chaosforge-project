# Adding an Experiment

## Provider Component Experiment

1. Add metadata to the component's `experiments/metadata.json`.
2. Add an execution definition under the engine-appropriate experiment folder,
   such as `experiments/toolkit/definitions/` or `experiments/custom/definitions/`.
3. Add provider action code under the matching engine folder. Prefer a concrete
   custom Azure SDK implementation under `experiments/custom/actions/` when an
   Azure management operation is available and avoids an unnecessary legacy
   Toolkit extension dependency.
4. Define every required input, type, default, range, hint, and resource selector.
5. Add rollback for reversible mutations.
6. Add a lifecycle adapter or check when the effect can be verified.
7. Test success, provider failure, invalid input, interruption, and rollback.

Configuration metadata is shared by CLI, Web, YAML, planning, and execution.
Provide defaults for safe, tunable configuration values such as durations,
counts, percentages, and booleans. Do not invent defaults for resource targets
or other environment-specific values. Use `integer`, `number`, `float`,
`boolean`, `choice`, `aws_region`, or `iso8601_duration` types with `min`,
`max`, `choices`, and a concise `hint` where applicable.

The names of metadata inputs are the target contract for Toolkit actions,
lifecycle adapters, preflight, and persistence. Reuse the exact metadata name
for each of those consumers; do not introduce an adapter-only alias. If a
previously persisted target requires compatibility support, prefer a documented
fallback while keeping the catalog field canonical.

### Rollback State

Reversible actions must persist rollback state below `runtime/rollback/` using
a target-scoped, operation-scoped name. State must include enough identity to
verify the rollback target, such as account or subscription, region, resource
identifier, and operation. Validate that identity before applying rollback.

Write state atomically, retain it when restoration fails or is interrupted, and
remove it only after the provider confirms successful restoration. A successful
capture -> mutate -> restore -> capture -> mutate -> restore sequence for the
same target must work. Add tests for repeated execution, two-target isolation,
and rollback rejection when state belongs to another target.

## Lifecycle Validation

Lifecycle validation is the extension point for experiment-specific pre-checks,
post-checks, and recovery checks. The lifecycle runs in this order:

```text
capture baseline and pre-checks
    -> inject the fault
    -> post-validation
    -> recovery validation, when applicable
```

The lifecycle interface is defined in `chaosforge/lifecycle/checks/base.py`:

```python
class ExperimentCheck:
    def capture(self, target: dict) -> dict:
        ...

    def validate(self, target: dict, baseline: dict) -> dict:
        ...
```

Register the check in `chaosforge/lifecycle/checks/resolver.py`. The resolver
receives the experiment and discovery service and returns either an
`ExperimentCheck` or `None` when lifecycle validation is not available.

### Multiple Pre-Checks

`capture()` is the pre-check phase. It may run one check or many checks. Return
the baseline data needed later by post-validation. Raise an exception when a
mandatory pre-check fails; the lifecycle marks the experiment `PRECHECK_FAILED`
and does not inject the fault.

```python
class ServiceFailureCheck(ExperimentCheck):
    name = "service-failure-lifecycle"

    def capture(self, target):
        checks = {
            "resource_exists": resource_exists(target),
            "replica_floor": replica_floor_is_safe(target),
            "health_endpoint": health_endpoint_is_healthy(target),
            "monitoring_ready": monitoring_is_available(target),
            "blast_radius": blast_radius_is_approved(target),
        }

        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise ValueError("Pre-checks failed: " + ", ".join(failed))

        return {
            "checks": checks,
            "resource": capture_provider_state(target),
        }
```

Use named checks rather than a single opaque boolean. The names and baseline are
persisted in lifecycle evidence and help operators identify why injection was
blocked.

### Multiple Post-Checks

`validate()` runs after fault injection. It must return a structured result with
at least `passed`. Include named check results, current state, and baseline so
reports and evidence remain actionable. A check may also return advisory
findings. Advisory findings remain failed observations in evidence but do not
make the aggregate validation fail.

```python
    def validate(self, target, baseline):
        current = capture_provider_state(target)
        checks = {
            "resource_restored": resource_is_restored(current, baseline["resource"]),
            "health_endpoint": health_endpoint_is_healthy(target),
            "replica_count": replicas_are_restored(current, baseline["resource"]),
            "error_rate": error_rate_is_acceptable(target),
            "configuration": configuration_matches(current, baseline["resource"]),
        }

        return {
            "passed": all(checks.values()),
            "checks": checks,
            "baseline": baseline,
            "current": current,
        }
```

This supports five, ten, or more post-checks. Every mandatory check contributes
to the final result through `all(checks.values())`.

### Validation Severity And Outcomes

Use blocking checks for conditions that prove the target has not recovered or
that cleanup failed. Use advisory checks for diagnostic observations that need
operator review but do not prove an unsafe final state, such as a recent event
inside a post-fault observation window.

The shared AKS/EKS Kubernetes validation facade returns per-check evidence with
`id`, `label`, `passed`, `severity`, `detail`, elapsed time, and any error. Its
aggregate result separates `blocking_failures` from `warnings`:

```python
{
    "passed": True,
    "warnings": [
        {
            "label": "Probe Failures Stopped (post)",
            "severity": "ADVISORY",
            "detail": "Recent Unhealthy probe events remain.",
        }
    ],
    "blocking_failures": [],
}
```

The lifecycle reports this as `SUCCESS_WITH_WARNINGS` while preserving
`result["success"] is True` for compatibility. Any blocking failure reports
`FAILED`. Do not use a display label as the only source of severity policy;
keep the classification stable when wording changes.

### Snapshot-Based Checks

For checks that compare a resource snapshot before and after an experiment, use
`CommonResourceCheck` from `chaosforge/lifecycle/checks/common.py`. Supply a
provider `ResourceAdapter`, preconditions, and named predicates.

```python
return CommonResourceCheck(
    adapter=MyResourceAdapter(),
    name="my-service-lifecycle",
    preconditions={
        "resource must be healthy": lambda snapshot: snapshot["state"] == "ready",
        "minimum replica count": lambda snapshot: snapshot["replicas"] >= 2,
    },
    predicates={
        "resource_exists": lambda current, baseline: current["exists"],
        "configuration_restored": lambda current, baseline: (
            current["configuration"] == baseline["configuration"]
        ),
        "replicas_restored": lambda current, baseline: (
            current["replicas"] == baseline["replicas"]
        ),
        "provider_healthy": lambda current, baseline: current["state"] == "ready",
        "custom_invariant": lambda current, baseline: custom_invariant(current),
    },
)
```

`preconditions` run during `capture()`. Failed preconditions prevent fault
injection. `predicates` run during `validate()` and are returned under
`result["checks"]` in evidence.

### Recovery Validation

By default, the lifecycle calls `validate()` once for post-validation and again
for recovery validation. Set this on a check when post-validation already
verifies the recovered state and must not run twice:

```python
recovery_supported = False
```

This is used by direct Chaos Mesh validation because its post-check runs after
the exact Chaos Mesh resource has been removed and already verifies recovery.

### Kubernetes And Chaos Mesh

Equivalent AKS and EKS Chaos Mesh faults reuse the shared validation facade in
`chaosforge/lifecycle/checks/kubernetes_chaos.py`. It provides named pre-checks,
during-fault observations, and post-cleanup checks. Before adding a Kubernetes
check, first determine whether the fault maps to an existing AKS/EKS validation
profile. Do not assign a merely similar profile to an unmatched experiment;
create a dedicated profile when its semantics differ.

For direct EKS Chaos Toolkit definitions, expose project-owned action wrappers
rather than referencing `chaosk8s` actions directly. The wrapper is responsible
for input normalization and actionable provider errors. Keep each definition's
provider argument names aligned with the wrapper signature and add a catalog
test that imports the provider and verifies that alignment. Chaos Mesh builders
receive only Chaos Mesh configuration; remove AWS Toolkit compatibility aliases
such as `aws_region` and `region` before forwarding configuration to a builder.

### Test Requirements

For every new or changed lifecycle check, add tests for:

1. Every mandatory pre-check passing.
2. Each pre-check failure blocking injection.
3. Every post-check passing.
4. Each blocking post-check failure producing `passed: false` and a named result.
5. Each advisory post-check failure producing a named warning without failing
   the experiment.
6. Provider/API failures while capturing or validating.
7. Recovery behavior and `recovery_supported` semantics.
8. Evidence containing baseline, named `checks`, current state, warnings, and
   errors.

Use mocked provider APIs. Live fault injection is not required for unit tests.

## AWS FIS Experiment

Add the operation to `chaosforge/providers/aws/fis/catalog.json` with its exact
AWS action ID, target key, resource type, and action parameter mappings. The
generic FIS wrapper transports catalog parameters as a JSON payload, waits for
the terminal experiment state, and checks individual action states.

Add target selection support before exposing a new resource type. Unsupported
resource types must fail before template creation rather than accepting an
incompatible ARN.

## Definition Integrity

Ensure package data in `pyproject.toml` includes new JSON, YAML, templates, or
static assets. Run catalog smoke tests and install the package in a clean virtual
environment before release.
