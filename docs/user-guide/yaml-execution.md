# YAML Campaign Execution

ChaosForge supports validation, planning, and execution as separate operations:

## Report Timezone

An executable YAML campaign can override the local report timezone for that run:

```yaml
settings:
  timezone: Asia/Shanghai
```

`settings.timezone` must be one of ChaosForge's supported IANA timezones, such
as `Europe/Berlin`, `Asia/Kolkata`, or `Asia/Shanghai`. The override affects the
generated report and mission summary only; evidence timestamps remain UTC and
the local CLI/Web timezone preference is not changed. Web campaign downloads
include the active local report timezone as `settings.timezone`.

```bash
chaosforge validate campaign.yaml
chaosforge plan campaign.yaml
chaosforge permissions campaign.yaml
chaosforge run campaign.yaml
```

The legacy `chaosforge --yaml campaign.yaml` form also executes a campaign.

## Required Permissions

Generate a read-only permission plan from a validated campaign before assigning
CI/CD access:

```bash
chaosforge permissions campaign.yaml
chaosforge permissions campaign.yaml --format json
chaosforge permissions campaign.yaml --format markdown --output permissions.md
```

The command does not contact AWS or Azure, inspect attached permissions, create
roles, or mutate resources. It derives requirements only from the campaign and
installed experiment catalog.

For AWS, the report is a copyable IAM policy document. When catalog metadata
does not define an action's resource-level scope, the policy uses `Resource: "*"`
and reports that limitation explicitly.

For Azure, the report is an RBAC assignment plan with separate sections for:

- The ChaosForge runtime identity used by `DefaultAzureCredential` for Azure SDK
  custom and Chaos Toolkit actions.
- `chaosforge-managed-identity`, used only by Azure Chaos Studio classic faults.
- Optional bootstrap authority required to create the UAMI or repair its target
  role assignment.

Azure report commands contain principal-ID placeholders and are suggestions, not
executed commands. A permission report is not proof that an identity already has
the required permissions.

Campaign YAML can also be imported into the interactive CLI for review, or
uploaded through the Web interface after selecting AWS or Azure. Uploading
validates the campaign, selected provider authentication, immutable environment
identity, and live targets before replacing the active campaign. It does not
execute the campaign.

YAML import is provider-scoped. Select and authenticate with AWS or Azure first;
the CLI and Web interface reject campaign YAML for a different provider and do
not offer upload/import until the selected provider is logged in.

## Workflow

1. `validate` checks document structure, experiment registration, and input
   definitions without injecting faults.
2. `plan` resolves provider targets and reports blockers, warnings, blast radius,
   and expected recovery behavior.
3. `run` builds the campaign and executes each experiment through the lifecycle
   runner without requesting confirmation or any other stdin input. Use it only
   from an approved automation or non-production workflow.

## Fault Duration

Campaign duration inputs use ISO-8601 consistently across providers and engines:

- `PT30S` means 30 seconds.
- `PT100S` means 100 seconds.
- `PT5M` means 5 minutes.
- `PT1H` means 1 hour.

Web and CLI show the same **Fault Duration (ISO 8601)** field and examples.
Campaign YAML retains the ISO value. At execution time, ChaosForge leaves the
value unchanged for Azure Chaos Studio and AWS FIS, converts it to numeric seconds
for local Toolkit/custom SDK and AKS provider actions, and converts it to Kubernetes
duration syntax for direct Chaos Mesh manifests.

## GitLab JUnit Reports

Use `--junit-output` with `run` to create a JUnit XML artifact for GitLab's
pipeline **Tests** view:

```bash
chaosforge run campaign.yaml \
  --junit-output runtime/reports/chaosforge-junit.xml
```

The option is accepted only by `run`. The normal text report, evidence bundle,
execution history, and process exit behavior remain unchanged.

Result mapping:

| ChaosForge outcome | GitLab/JUnit result |
|---|---|
| `SUCCESS` | Passed testcase |
| `SUCCESS_WITH_WARNINGS` | Passed testcase with warnings in `system-out` |
| `FAILED` | Failed testcase with failure details |
| `SKIPPED` | Skipped testcase |

Campaign validation, identity/preflight, irreversible-acknowledgement, planning,
or unexpected execution failures produce a synthetic failed testcase named
**Campaign setup** when the output option is supplied.

Example GitLab job:

```yaml
chaos_test:
  stage: test
  script:
    - chaosforge run campaigns/azure-resilience.yaml --junit-output runtime/reports/chaosforge-junit.xml
  artifacts:
    when: always
    reports:
      junit: runtime/reports/chaosforge-junit.xml
    paths:
      - runtime/reports/
      - runtime/evidence/
    expire_in: 30 days
```

`when: always` ensures GitLab uploads the JUnit report and detailed ChaosForge
artifacts even when the campaign job exits with a failure.

## Irreversible Experiments

ChaosForge classifies installed experiments as **Reversible** or
**Irreversible**. The installed catalog owns this classification; campaign YAML
does not override it. Reversible experiments restore a captured state or use a
provider/controller-managed temporary fault. Irreversible experiments cannot
reliably restore original data, resource identity, topology, or external side
effects.

Because `run` is non-interactive, executable YAML containing an irreversible
experiment must explicitly acknowledge the reviewed risk:

```yaml
campaign:
  name: approved-destructive-test
  continue_on_failure: false
  irreversible_operations_acknowledged: true
```

Without this Boolean acknowledgement, `chaosforge run` stops before planning or
provider execution and lists the irreversible selected experiments. Templates can
remain unacknowledged because they cannot execute.

## Minimal Shape

```yaml
campaign:
  name: Lambda resilience
  continue_on_failure: false

cloud:
  provider: aws

environment:
  name: engineering-dev
  account_id: "123456789012"
  account_alias: engineering-dev

experiments:
  - service: lambda
    experiment: lambda-timeout
    variables:
      lambda_name: example-function
      target_timeout: 10
      wait_seconds: PT30S
```

Use `examples/campaigns/lambda-memory.yaml` as a single-experiment template and
`examples/campaigns/lambda-resilience.yaml` for a multi-experiment template.
Replace template placeholders and remove `template: true` only after adding the
target account identity. Never skip `validate` and `plan` for a newly authored
campaign.

## Environment Binding And Templates

Executable campaigns require an `environment` identity that exactly matches the
active provider credentials: `environment.account_id` for AWS and
`environment.subscription_id` for Azure. Account aliases and subscription names
are optional display metadata. A mismatch blocks validation, import, planning,
and execution before any experiment is loaded or run.

Exported campaigns include the active account or subscription identity. To share
a reusable starting point across accounts, use a template instead:

```yaml
template: true
```

Templates may omit environment identity and use placeholder target values, but
cannot be imported, planned, or executed. Copy the template, supply the target
environment and concrete resource values, then remove `template: true`.

Before import, planning, or execution, preflight resolves every supplied catalog
resource target. This includes AWS resources such as Lambda functions, EC2/EBS,
ECS, EKS/Chaos Mesh workloads, DynamoDB, RDS, S3, SNS, ELB, API Gateway,
ElastiCache, VPC resources, and FIS templates/experiments; Azure component ARM
resources such as Redis caches, VMs, VM scale sets, App Services, Function Apps,
Key Vaults, Cosmos DB accounts, Event Hubs namespaces, PostgreSQL Flexible
Servers, and Container Apps; and AKS contexts. A nonexistent target is rejected before the campaign reaches
the campaign page or fault execution.

The CLI **Save Campaign** action asks for an output name. Web **Download YAML**
exports the active campaign using its current name. These exports are separate
from local named draft records under `runtime/campaigns/<cloud>/`. Importing a
YAML campaign after validation and target preflight creates a new cloud-scoped
draft with a new stable ID and rejects a duplicate name within that cloud.
Running `chaosforge run FILE` also records durable history with execution source
`yaml-cli` under `runtime/executions/`.

Non-interactive EKS and AKS Chaos Mesh execution never prompts. Use
`--chaos-mesh-version-policy` with `run` or legacy `--yaml` execution:

```bash
chaosforge run campaign.yaml --chaos-mesh-version-policy require-current
```

Policies are:

- `require-current` (default): require the installed `2.8.7` release.
- `allow-older`: allow an installed older compatible `2.8.x` release, but do not
  install or upgrade.
- `upgrade`: install `2.8.7` when absent or upgrade an older compatible release.
- `use-installed`: allow an older compatible installed release, but do not
  install one when absent.

Newer `2.8.x` releases are never downgraded. Different major/minor releases are
blocked for every policy because ChaosForge validates manifests against bundled
`2.8.7` CRD schemas.

## Portable Campaign Format

Only stable catalog identity, environment binding, and variables are stored:
campaign name, continue-on-failure policy, cloud provider, account/subscription
identity, service, experiment ID, and input variables. Display names, local
definition paths, engines, target services, and runtime status are reconstructed
from the installed catalog when imported.

Campaign YAML must be a single UTF-8 document no larger than 1 MiB. Duplicate
mapping keys, unknown schema keys, mixed AWS/Azure services, missing catalog
entries, and invalid experiment variables are rejected.

Metadata defaults are materialized when a campaign is built, so YAML may omit a
configuration value that has a catalog default. Resource targets and any field
without a default remain required. `validate`, `plan`, and `run` apply the same
type, choice, region, duration, and numeric-range validation used by the CLI
and Web forms before fault execution. Azure component YAML campaigns use the
same catalog-backed experiment model and shared lifecycle, dispatcher, provider
action, rollback, evidence, and reporting path as Web and interactive CLI
campaigns; only target collection differs by interface.

### Azure Resource Names

Azure component YAML normally uses the canonical ARM resource ID:

```yaml
variables:
  subscription_id: <subscription-id>
  resource_group: <resource-group>
  resource_id: /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/<provider>/<resource-type>/<resource-name>
```

For Azure root component experiments whose catalog target field is
`resource_id`, YAML may instead use a friendlier resource name with its required
scope:

```yaml
variables:
  subscription_id: <subscription-id>
  resource_group: <resource-group>
  resource_name: <resource-name>
```

Offline `chaosforge validate` accepts this alias structurally. Authenticated
Web upload, `plan`, and `run` resolve it case-insensitively against the expected
Azure component resource type and replace it with the canonical `resource_id`
before execution. Do not supply both `resource_name` and `resource_id` in one
experiment. A missing, ambiguous, or incorrectly scoped name fails preflight.

Downloaded/exported YAML always uses the canonical ARM `resource_id`. Special
target contracts, such as Redis reboot's `redis_name`, VMSS instance criteria,
and Key Vault child-resource names, do not support `resource_name` as a generic
replacement.
