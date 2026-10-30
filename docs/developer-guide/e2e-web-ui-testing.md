# Web UI Functional E2E Tests

Live Web UI functional tests are developer tooling. They are not part of the
production dependency set or the standard CI suite because they require a
running ChaosForge Web UI and real cloud resources.

Run the portable `python scripts/run_e2e_webui.py` wrapper from an activated
virtual environment on macOS, Linux, or Windows. The legacy
`scripts/run-e2e-webui` Bash wrapper remains available on macOS/Linux only.

The portable wrapper passes pytest's `-ra` option, so every skip
reason is printed at the end of the run. This distinguishes an intentionally
inactive campaign mode from a missing tagged resource, missing Playwright, or a
missing manifest in explicit mode.

Every wrapper invocation also writes a self-contained HTML report to
`runtime/e2e-reports/webui-functional-<UTC timestamp>.html`. The report records
the selected pytest case, pass/fail/skip outcome, and assertion failure details,
including the Web UI execution-status payload returned for a failed campaign.
The report is generated even when pytest exits unsuccessfully; the wrapper
prints its exact path before returning pytest's exit code.

## Setup

```bash
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
```

Start the Web UI in a separate terminal, authenticate it to the intended AWS and
Azure environments, then run the built-in tag-mode test catalog:

```bash
chaosforge-web
```

The default E2E URL is `http://127.0.0.1:5000`. Supply
`--e2e-base-url http://host:port` when the Web UI runs elsewhere.

### Windows PowerShell

PowerShell uses the backtick (`` ` ``) rather than Bash's backslash for line
continuation. Use the same portable Python command:

```powershell
python scripts/run_e2e_webui.py `
  --e2e-mode tags `
  --e2e-cloud azure `
  --e2e-components azure_vm `
  --e2e-tag Chaosforge=E2E-Test `
  --e2e-execute
```

For Windows Command Prompt, either put the command on one line or use `^` as
the line-continuation character. Do not invoke `scripts/run-e2e-webui` directly
on Windows because it is a Bash compatibility shim.

```bash
python scripts/run_e2e_webui.py \
  --e2e-mode tags \
  --e2e-cloud azure \
  --e2e-components azure_vm \
  --e2e-tag Chaosforge=E2E-Test \
  --e2e-execute
```

Pass `--e2e-mode explicit` with a manifest such as
`e2e/manifests/example-explicit-mode.yaml` to select named resources or resource
IDs. Explicit mode requires a manifest. Pass `--e2e-execute` only for approved
non-production resources and reversible experiments.

## Selection Modes

Tag mode discovers exactly one resource per component using every supplied tag.

```bash
python scripts/run_e2e_webui.py \
  --e2e-mode tags \
  --e2e-cloud aws \
  --e2e-components lambda,dynamodb \
  --e2e-aws-region eu-central-1 \
  --e2e-tag Chaosforge=E2E-Test \
  --e2e-tag ManagedBy=ChaosForge
```

Tag mode does not use a manifest. The built-in safe E2E catalog defines the
supported components, experiments, selectors, target variables, and required
non-target input values. In tag mode, `resource_group` is derived from the
resolved Azure resource ID before loading the Web UI resource selector.

Azure VM tag mode runs all four Azure VM experiments. Redeploy and shutdown are
Azure Chaos Studio faults, so supply the name of an existing Azure Chaos Studio
user-assigned identity. The runner resolves a unique name to its ARM resource ID:

```bash
python scripts/run_e2e_webui.py \
  --e2e-mode tags \
  --e2e-cloud azure \
  --e2e-components azure_vm \
  --e2e-tag Chaosforge=E2E-Test \
  --e2e-azure-chaos-identity "<identity-name>" \
  --e2e-vm-shutdown-duration PT1M \
  --e2e-execute
```

Use `--e2e-vm-abrupt-shutdown` only when abrupt shutdown behavior is explicitly
approved. The selected Chaos identity must already have the required role on the
target VM or a parent scope.

Explicit mode reads `resources` from the selected component in the manifest. A
resource entry has either `name` or `resource_id`:

```yaml
resources:
  - name: chaosforge-e2e-bucket
  - resource_id: /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Compute/virtualMachines/<vm-name>
```

Each component must declare its Web UI `selector` and `target_variable`. The
runner uses `target_variable` to prove that the reviewed and executed campaign
contains the exact resource selected in the browser. It does not expose the
complete experiment variable set through the Web API.

Use `inputs` for required non-target form values. These values are filled after
the exact resource is selected. Do not put credentials, tokens, or secret values
in a manifest.

```yaml
elb:
  region: eu-central-1
  resource_type: elasticloadbalancing:loadbalancer
  selector: "#load_balancer"
  target_variable: load_balancer
  inputs:
    attribute_key: idle_timeout.timeout_seconds
    attribute_value: "30"
  experiments:
    - elb-load-balancer
```

For tag mode, use the optional inputs-only file without supplying resource IDs
or names:

```bash
python scripts/run_e2e_webui.py \
  --e2e-mode tags \
  --e2e-cloud azure \
  --e2e-components azure_key_vault,azure_postgres_flexible \
  --e2e-tag Chaosforge=E2E-Test \
  --e2e-inputs e2e/manifests/example-tag-inputs.yaml \
  --e2e-execute
```

Values are resolved in this order: inputs-file experiment override, inputs-file
default, built-in functional-test value, metadata default, then an experiment is skipped if
a required value cannot be safely derived. Use `--e2e-strict-inputs` to turn
such skipped experiments into failures.

Functional tag mode uses short timing values by default:

```text
duration:               PT1M
duration_seconds:       60
fault_duration_seconds: 60
wait_seconds:           60
```

The browser runner waits up to 3 hours for a live campaign because provider
operations can include both a fault duration and control-plane recovery time. It
returns immediately when the Web UI reports a terminal result. Override the
maximum for a particular run when needed:

```bash
--e2e-execution-timeout-seconds 2400
```

Production metadata is not changed. Override timing globally or per experiment
through the inputs file:

```yaml
version: 1
defaults:
  duration: PT30S
  wait_seconds: 30

components:
  azure_vm:
    experiments:
      azure-vm-boot-diagnostics-toggle:
        duration_seconds: 15
```

The Azure Event Hubs state experiment defaults to `desired_state: Disabled` for
functional tests. No inputs file is required for the default Event Hubs run.
Use an inputs file only to override it, for example with `Active` or
`SendDisabled`.

The state experiment also retains its metadata default `event_hubs: "*"`, so it
changes every Event Hub entity in the uniquely tagged namespace and restores
their captured prior states. It does not require a single child entity.
If the namespace contains no entities, only the state-change experiment is
skipped; public-access disruption can still run in the same combined campaign.

## Filters

`--e2e-cloud` accepts `aws`, `azure`, or `all`. `--e2e-components` accepts
`all` or a comma-separated list. The selected components are planned into
independent pytest cases, so one missing resource does not suppress other
components or clouds.

The structured AWS resolver currently supports `s3`, `lambda`, `dynamodb`,
`elb`, and ElastiCache replication groups (`elasticache`).
The Azure resolver is resource-type driven, so a manifest can describe any Azure
component whose Web UI selector and target input are known. A component without
a structured resolver is reported as a framework failure, not silently skipped.
`all` means every component in the built-in E2E catalog, not every ChaosForge
product component.

For every selected catalog component, tag mode plans all installed metadata
experiments. Reversible experiments run first; irreversible or external-effect
experiments run afterward by default. To omit them:

```bash
--e2e-skip-irreversible
```

Select individual metadata experiments with a repeatable component-qualified
filter. ChaosForge rejects an experiment ID that does not belong to its named
component, or a component excluded by `--e2e-components`:

```bash
--e2e-components azure_vm,azure_event_hub \
--e2e-experiment azure_vm:azure-vm-toolkit-reboot \
--e2e-experiment azure_event_hub:azure-event-hub-state
```

AWS FIS-backed experiments require the IAM role that AWS FIS assumes to perform
the fault. When a selected experiment declares required `role_arn`, provide it
explicitly. The planner rejects a live run before browser execution when it is
missing:

```bash
--e2e-aws-fis-role-arn arn:aws:iam::<account-id>:role/<fis-experiment-role>
```

The principal running ChaosForge also needs `iam:PassRole` for that role and the
AWS FIS create/start/read permissions. Azure Chaos Studio identities use the
separate `--e2e-azure-chaos-identity` option.

Selected component-bound AWS FIS actions are tag-resolvable. For example, this
creates one combined AWS campaign that targets exactly one tagged EC2 instance:

```bash
python scripts/run_e2e_webui.py \
  --e2e-mode tags \
  --e2e-cloud aws \
  --e2e-components ec2 \
  --e2e-experiment ec2:stop-instances \
  --e2e-experiment ec2:reboot-instances \
  --e2e-experiment ec2:terminate-instances \
  --e2e-aws-region eu-central-1 \
  --e2e-tag Chaosforge=E2E-Test \
  --e2e-aws-fis-role-arn arn:aws:iam::<account-id>:role/<fis-experiment-role> \
  --e2e-campaign-mode combined \
  --e2e-execute
```

The runner binds each selected FIS action to its component-aware Web UI form,
uses the tagged instance ARN as the FIS target, and refuses multiple matches.
`terminate-instances` is irreversible; use only a disposable instance.

For each child resource, the runner requires the same supplied tags when the
cloud provider supports child tags. Kubernetes descendants use the same key and
value as Kubernetes labels. Child types that cannot carry provider tags must
resolve to exactly one eligible child beneath the tagged parent; zero or
multiple children skip that experiment with an explicit reason.

## Outcomes

| Condition | Result |
|---|---|
| No matching resource | Skip that component/experiment case |
| Multiple matching resources | Fail before opening the Web UI |
| AWS/Azure authentication or read permission failure | Fail |
| Functional resolver does not support the component | Fail |
| Cloud resource is absent from the Web UI selector | Fail |
| Reviewed target differs from selected resource | Fail |
| Irreversible experiment with execution enabled | Skip |
| Fault execution fails or target binding is lost | Fail |
| Required Azure Chaos identity was not supplied | Fail before browser execution |

Use `--e2e-strict-missing-resource` to turn missing-resource skips into
failures for an environment that is expected to contain every selected target.

## Execution Safety

Without `--e2e-execute`, the runner validates provider discovery and exact Web
UI resource selection only. With `--e2e-execute`, it creates a uniquely named
campaign, adds one experiment through the UI, verifies the permission review,
confirms the review, starts the campaign, and waits for terminal success.

Use dedicated non-production accounts/subscriptions and resources. Run one
functional suite at a time against a shared environment. The standard GitLab CI
pipeline does not run live E2E tests.

## Campaign Modes

`--e2e-campaign-mode isolated` is the default. Each resolved
cloud/component/experiment combination gets an isolated campaign, review, and
execution. This is the recommended mode for diagnosis and routine development.

Campaign mode changes only how the same planned experiments are grouped. It
does not add, remove, or duplicate component experiments:

```text
Four Azure VM experiments + isolated mode -> four campaigns and four test cases
Four Azure VM experiments + combined mode -> one Azure campaign containing four experiments
```

Pytest can report two discovered runner functions with one deselected in either
mode. This is runner selection metadata, not a ChaosForge experiment count. The
combined test identifier includes the actual planned count, for example
`azure-combined-4-experiments`.

`--e2e-campaign-mode combined` creates one campaign per cloud containing every
available selected experiment. It requires `--e2e-execute`:

```bash
python scripts/run_e2e_webui.py \
  --e2e-mode tags \
  --e2e-cloud azure \
  --e2e-components azure_vm \
  --e2e-tag Chaosforge=E2E-Test \
  --e2e-azure-chaos-identity "<identity-name>" \
  --e2e-campaign-mode combined \
  --e2e-execute
```

When `--e2e-cloud all` is used with combined mode, the runner creates separate
AWS and Azure campaigns because ChaosForge campaigns are provider-scoped. Missing
resources are omitted from the relevant cloud campaign and reported as skipped.
Ambiguous resources, unsupported components, and cloud access failures stop the
combined run before any campaign is created. The runner verifies every reviewed
and executed experiment independently, including its selected target.
