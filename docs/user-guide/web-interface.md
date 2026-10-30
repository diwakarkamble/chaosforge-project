# Web Interface

Start the local interface with `chaosforge-web` and open
`http://127.0.0.1:5000`.

## Navigation

1. Select AWS or Azure on the landing page.
2. Optionally drop a campaign YAML into the upload panel or select it from disk;
   shared YAML validation, environment matching, and live target preflight begin
   automatically.
3. Select a component owned by that provider.
4. Select an experiment from the canonical catalog.
5. Configure its inputs and add it to the campaign.
6. Use the campaign cart badge to review and execute all or selected entries.

Each experiment card and campaign row displays a **Reversible** or
**Irreversible** label. When selected execution includes irreversible entries,
the permission review dialog lists them separately and requires an explicit
acknowledgement in addition to the normal permission review.

AWS exposes its component catalog, AWS Fault Injection Service, and direct
Chaos Mesh for Amazon EKS. Azure exposes AKS, Redis, compute, web, database,
messaging, Key Vault, and Container Apps component catalogs. AKS forms use the
existing Azure Kubernetes discovery service for contexts, namespaces,
deployments, containers, nodes, and zones.

Azure forms display the authenticated subscription ID and name as read-only.
They load resource groups dynamically from that subscription. Azure component
forms then load only resources of the selected component type for that resource
group. Azure SDK custom experiments use the selected ARM target directly and do
not show the Chaos Studio identity setup control. AKS uses its selected cluster
context and does not expose a manually editable Azure location field.

For VMSS experiments, select the scale set after choosing the resource group.
**Shutdown Scale Set Instance** then loads its instances as required checkboxes;
ChaosForge serializes the checked IDs for the Azure Chaos Studio fault. **Reboot
Virtual Machine Scale Set** offers optional instance checkboxes. Selecting one or
more restarts each selected instance; leaving the list empty restarts one random
instance from that scale set.

For EKS Chaos Mesh Container Kill, select the target mode and then a Deployment
or Pod before selecting a required Container. The Container list reloads after a
target mode, Deployment, or Pod change, so it always reflects the active target.

## AWS FIS Forms

Opening an AWS FIS action from a component binds that component and action; the
form does not ask for them again. Select the action target from the dynamic
resource selector, configure the action parameters and FIS execution role, then
add the experiment. `Created By` is derived from the active AWS CLI identity and
is read-only. Native AWS FIS actions execute through the AWS SDK, not Chaos
Toolkit.

Lambda FIS actions additionally require an S3 configuration bucket in the same
region. ChaosForge configures the Lambda FIS extension and environment through
AWS SDK calls, while preserving unrelated Lambda configuration.

For S3 **Pause Bucket Replication**, Destination Bucket(s) is optional. Leaving
it blank omits the FIS `destinationBuckets` parameter.

## Report Timezone

Use the gear icon on the landing or provider page to open **Settings**. The
current UTC offset appears above the cart and gear icons; hovering it reveals the
full geographic timezone. Reports and mission summaries
use the selected timezone; evidence remains UTC. The default is `Europe/Berlin`,
and daylight-saving transitions are applied automatically. China Standard Time is
available as `Asia/Shanghai`. Opening Settings from an AWS or Azure provider page
returns to that provider page when **Back** is selected.

## Execution Parity

Web and CLI use the same experiment factory, campaign executor, lifecycle
runner, check resolver, and execution dispatcher. The Web runner only adapts
progress and logs for browser display; it does not maintain a separate fault
execution algorithm.

The YAML upload is limited to 1 MiB, parsed with a safe loader, checked for
duplicate keys, validated against the existing campaign and experiment
validators, constrained to the selected provider, and passed to the same
identity and target-preflight service used by CLI YAML commands. An executable
campaign must match the active AWS account ID or Azure subscription ID. A
successful upload creates and opens a new named draft for the selected cloud;
duplicate names, invalid files, identity mismatches, templates, or unresolved
targets remain on the selected cloud page with an error. Preflight resolves every
supplied catalog resource target, including AWS service resources and Kubernetes
workloads, Azure Redis caches, AKS contexts, and applicable FIS templates or
experiments.

## Campaign Files

The campaign page provides **Download YAML**, which downloads the active campaign
using its current name. The executable YAML includes the current AWS account or
Azure subscription binding and the current report timezone under
`settings.timezone`. Downloading does not create another local draft.

**Campaign Library** lists durable cloud-scoped drafts at
`/campaigns?cloud=aws` and `/campaigns?cloud=azure`. Create a named draft there,
then open it to use the existing campaign editor. Draft names are unique within a
cloud, preserve their creation timestamp, and are shared with the interactive
CLI. To import a YAML file, use the provider-scoped upload panel; after validation
and target preflight, it creates a new named draft rather than replacing an
existing draft. The imported draft receives a new stable ID, so execution results
from an older deleted campaign with the same experiments are not shown as results
of the new import.

The campaign page includes a **Back to AWS Components** or **Back to Azure
Components** action based on the active campaign provider, so operators can
continue adding experiments without returning to the cloud-selection landing
page.

For selected EKS or AKS Chaos Mesh experiments, the permission-review dialog also
checks the installed Helm chart version before execution. Missing and older
compatible releases require an Install, Upgrade, Continue, or Cancel decision as
applicable. The accepted choice is bound to the same one-time review token and is
remembered for that campaign and cluster while the detected version remains
unchanged.

The provider return action appears once. Cart counts, campaign table rows, and
execution actions are filtered to the selected cloud provider so AWS and Azure
experiments do not appear together in the same provider-scoped workflow.

Web campaign and execution state is cloud-isolated. Use `?cloud=aws` or
`?cloud=azure` on the campaign and execution pages to view the corresponding
campaign, cloud identity, logs, and progress. AWS and Azure executions use
separate Web workers and log streams, so one AWS and one Azure campaign can run
concurrently in the local process.

Each Web execution receives a run ID. A durable execution history record is
created before execution and retained under `runtime/executions/` after the
Flask process exits. It contains the immutable campaign snapshot, source
(`web`, `interactive-cli`, or `yaml-cli`), final status, report path, and Web
output when available. **Execution History** in Campaign Library exposes
**View Logs** for every run. It opens that exact run, including after another
campaign has run or the Flask process has restarted. When an experiment row was
included in a matching run, **View Results** opens that run and jumps to the log
section where the experiment started. Log and report downloads are run-specific.
Only one execution may run at a time for one cloud; a second request for that
cloud opens the active run. AWS and Azure can run one execution each in parallel.

The interactive CLI continues to execute synchronously and does not use Web
workers or browser logs. It does use the same durable draft and execution-history
store, so campaigns and history created through either interface are visible in
both after restart.

The execution console streams the lifecycle report, including pre-check,
chaos-execution, post-validation, recovery/evidence details, and the campaign
mission summary. This keeps runtime feedback in the browser rather than only in
the Flask process output.

Azure SDK custom experiments use this same lifecycle report. Reversible custom
experiments show their captured rollback state through the normal recovery and
evidence phases; nonpersistent restart actions show readiness validation after
the Azure SDK operation completes.

## Permission Review

The campaign page includes **View Required Permissions**. It generates a
read-only report from the active provider-scoped campaign:

- AWS campaigns show the required IAM policy document.
- Azure campaigns show runtime identity, Chaos Studio managed identity, and
  bootstrap RBAC assignment requirements separately.

Selecting **Execute All** or **Execute Selected** opens the same review before
execution. Execution starts only after the operator confirms that review. The
review does not inspect current role assignments or attach permissions; it is an
acknowledgement of the campaign-derived requirement plan.

The console follows new output only while the reader is already at the bottom.
When a user scrolls up to inspect earlier output, periodic log polling preserves
that scroll position instead of forcing a return to the latest line. Chaos Toolkit
execution is integrated through its Python library and rendered from its structured
execution journal.

## Stopping The Server

Stop the local Web server with Ctrl-C or `SIGTERM`. If a campaign is executing,
ChaosForge keeps the active execution worker alive and waits for its rollback or
provider cleanup to finish before the server process exits. The browser console
records that shutdown is waiting for cleanup.

Do not force-kill the process while a fault is active. `SIGKILL`, host failure,
and power loss cannot trigger cleanup; inspect the experiment evidence and apply
the provider-specific recovery procedure before continuing.

## Security Boundary

The Flask server binds only to loopback. Live campaign and execution state is
held in process memory, scoped by cloud but not by browser user; drafts and
completed execution records are persisted locally. The application does not
provide authentication, authorization, CSRF protection, or multi-user isolation.
Do not expose it as a remote production service.

Azure, Kubernetes, and Redis logos in the Web icon directory include source and
license attribution in `chaosforge/interfaces/web/static/icons/NOTICE.md`.
