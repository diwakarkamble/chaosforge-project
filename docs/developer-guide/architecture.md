# Architecture

ChaosForge is an installable Python package with four primary execution paths:

```text
interfaces -> application -> lifecycle -> engines/providers -> cloud APIs
                                      -> storage/reporting
```

## Package Boundaries

| Package | Responsibility |
|---|---|
| `chaosforge/interfaces` | CLI and Flask Web composition and presentation |
| `chaosforge/application` | Campaign construction, metadata access, planning, validation, and services |
| `chaosforge/models` | Campaign, experiment, plan, and execution data models |
| `chaosforge/catalog` | Canonical metadata and definition lookup |
| `chaosforge/lifecycle` | Checks, dispatch, execution states, validation, recovery, and evidence coordination |
| `chaosforge/engines` | Chaos Toolkit and Chaos Mesh engine mechanics |
| `chaosforge/providers` | Provider discovery, component experiments, actions, and FIS integration |
| `chaosforge/storage` | Campaign and evidence persistence |
| `chaosforge/reporting` | Human-readable reports, GitLab-compatible JUnit XML, time formatting, and notifications |
| `chaosforge/common` | Shared infrastructure such as repository and runtime paths |

## Campaign Persistence

`storage/campaign_history.py` owns the local durable contract for named draft
campaigns and immutable execution history. Drafts are cloud-scoped, have stable
generated IDs, and enforce case-insensitive unique display names per cloud.
Existing active-campaign manager operations auto-save an opened draft after add,
edit, remove, clear, or replacement; they must not alter provider/lifecycle
execution behavior.

Every Web, interactive CLI, and non-interactive YAML execution creates an
execution record before lifecycle work starts. The record stores a campaign
snapshot, source (`web`, `interactive-cli`, or `yaml-cli`), terminal status,
available logs, and report path. Later draft edits must not mutate a prior run's
snapshot. `runtime/campaigns/<cloud>/` stores drafts and `runtime/executions/`
stores run records; lifecycle evidence remains under `runtime/evidence/`. Web
execution routes must bind result, log, progress, and report retrieval to the
requested run ID, falling back from in-memory live state to the durable record;
they must not select the most recent run for the cloud.

## Execution Flow

Interfaces build `Campaign` and `Experiment` models. The campaign executor runs
experiments sequentially through `LifecycleRunner`. `ExecutionDispatcher`
selects Chaos Toolkit, direct AWS FIS SDK execution, direct Chaos Mesh, Azure
Chaos Studio, or Azure SDK execution. Provider actions own mutations and rollback behavior;
the lifecycle layer owns validation state and evidence.

Interrupt handling is part of that execution contract. Engines must clean up any
fault they have already created before returning an interrupted or failed result.
The lifecycle runner records interruption as a terminal failed execution and
persists evidence. CLI Ctrl-C and Web Ctrl-C/`SIGTERM` wait for the active
execution to finish cleanup; hard process termination cannot provide this
guarantee.

Equivalent AKS and EKS Chaos Mesh faults use the shared validation facade in
`chaosforge/lifecycle/checks/kubernetes_chaos.py`. It delegates to the existing
Kubernetes check implementation while keeping Azure-specific orchestration in
the AKS provider.

The direct EKS workload target contract is shared by CLI, Web, YAML planning,
and preflight: cluster, namespace, target mode, then Deployment or exact Pod.
Container Kill resolves its required container selector only after that target is
known. Web reloads the selector on target-mode, Deployment, and Pod changes;
CLI passes the same selected target context to Kubernetes discovery.

CLI and Web construct experiments through
`chaosforge/application/campaigns/factory.py` and execute campaigns through
`LifecycleExecutionService`. Interface adapters may render prompts, logs, and
progress, but must not implement independent engine status semantics.

Web redirects must be generated with `url_for()` from trusted route values.
Campaign edit redirects validate the stored service and experiment identity
against the installed catalog before constructing their destination; FIS edits
also validate their selected FIS service and action. Do not pass query values or
persisted request-derived strings directly to `redirect()`.

## Runtime Data

All generated state belongs under `runtime/`. Code must use
`chaosforge.common.paths.repository_paths()` instead of depending on the current
working directory.

Rollback state is a provider-action safety boundary. It must be scoped to the
operation and target, validated before restoration, and retained until a
successful restore is confirmed.

Azure SDK custom experiments follow the same boundary. Definitions and actions
live under `providers/azure/components/<component>/experiments/custom/`; provider
actions accept the selected Azure ARM `resource_id` and derive the resource name
internally. Reversible actions store only target-scoped pre-mutation state under
`runtime/<component>/`, restore it through the definition rollback action, and
remove it only after a successful restore. Web, CLI, and YAML import construct
the same catalog-backed experiment model, then use this shared dispatcher,
lifecycle, provider-action, rollback, evidence, and reporting path. Interfaces
may differ only in input collection and resource discovery; neither may invent a
separate resource-name or rollback contract.

`application/services/user_settings.py` owns local presentation preferences
shared by CLI and Web. It persists the selected IANA report timezone in
`runtime/settings.json`. Execution and evidence timestamps remain UTC; report
formatting converts each timestamp with the offset applicable at that historical
instant, including daylight-saving transitions.

`reporting/junit.py` generates a JUnit XML suite for YAML campaign runs when
`chaosforge run` receives `--junit-output PATH`. Each experiment becomes a
testcase; setup, validation, planning, and unexpected execution failures become
a synthetic failed `Campaign setup` testcase. The report generator is an output
adapter only: it must not change campaign status, lifecycle behavior, evidence,
or existing text reporting.

## Permission Reports

`application/services/permissions.py:PermissionReportService` is the read-only,
provider-neutral permission boundary. It consumes a built campaign and catalog
metadata without calling cloud APIs. AWS reports render IAM policy JSON; Azure
reports render separate runtime, Chaos Studio UAMI, and bootstrap RBAC plans with
copyable placeholder-based Azure CLI commands. CLI, Web, and YAML permission
output must consume this service rather than reconstruct permissions in an
interface.

Web execution requires a short-lived, one-time, provider/selection-bound
permission-review token issued by the read-only report endpoint and confirmed by
the browser. Do not weaken this gate by accepting direct execution URLs, reused
tokens, cross-cloud tokens, or a changed selected-experiment set. Noninteractive
`chaosforge run FILE` remains prompt-free; CI/CD should run the separate
`chaosforge permissions FILE` command as a pipeline review/artifact step.

## Dependency Direction

- Interfaces may call application and lifecycle services.
- Application services coordinate models, catalogs, providers, and storage.
- Engines contain engine-specific mechanics, not user-interface behavior.
- Providers own provider-specific discovery and mutations.
- Models must not import interfaces or provider implementations.

## Native AWS FIS

Native AWS FIS actions are component-owned under
`providers/aws/components/<component>/experiments/fis/`. Interfaces use
`application/component_fis.py` to bind the selected component/action and collect
its target and catalog parameters without exposing redundant service/action
selectors. The shared AWS FIS runner creates, starts, polls, and optionally
deletes the FIS template through boto3. Native FIS actions must not execute
through the Chaos Toolkit runner. Component packages own target preparation,
prerequisites, and lifecycle checks when their AWS resource semantics require
them. The former `providers/aws/fis/toolkit/` JSON wrappers were removed; direct
FIS experiments do not carry a runnable definition file.

ElastiCache component actions must use the AWS resource type and API that own the
setting being changed: replication groups for provisioned Redis configuration,
cache clusters for reboot, and Serverless caches for usage limits. Lifecycle
adapters must capture the same resource type selected by the form.
