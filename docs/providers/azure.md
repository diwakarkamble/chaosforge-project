# Microsoft Azure

ChaosForge supports Microsoft Azure experiments through Azure Chaos Studio
Experiments (classic),
Azure SDK management clients, and Kubernetes operations. Azure components use
`DefaultAzureCredential`, allowing local Azure CLI authentication, managed
identity, workload identity, or environment-based service principal credentials.

## Authentication and Discovery

Select and authenticate with Azure before creating or importing a campaign.
ChaosForge detects the active subscription and uses subscription-scoped resource
discovery in both CLI and Web interfaces. Resource groups and component resources
are presented dynamically rather than requiring manually entered resource IDs.
Subscription display names are resolved to the canonical Azure subscription UUID
before AKS or Redis operations construct Azure Resource Manager requests.

Required access depends on the experiment and can include:

- Read access for subscription and resource discovery
- Write access to the target Azure resource
- `Microsoft.Chaos` provider, target, capability, and experiment permissions
- Kubernetes and Chaos Mesh RBAC for applicable AKS experiments

## Key Vault Certificate Faults

Key Vault certificate faults run under the selected `chaosforge-managed-identity`,
not the identity that launches ChaosForge. The identity requires **Key Vault
Certificates Officer** on the vault, resource group, or subscription. This
data-plane role grants the `Microsoft.KeyVault/vaults/certificates/read` and
certificate update permissions used by Azure Chaos Studio; **Key Vault
Contributor** only manages the vault resource and is insufficient. This role is
used only for certificate faults; it does not grant secret permissions.

CLI and Web identity setup can bootstrap this role for a new identity. For an
existing identity, operators may add an experiment to a campaign and have a
separate administrator assign the role before execution:

```bash
az role assignment create \
  --assignee-object-id <chaos-identity-principal-id> \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Certificates Officer" \
  --scope <key-vault-resource-id>
```

Replace the object ID and scope with the selected Chaos identity and target
vault. Azure RBAC assignment propagation can take several minutes.

`Disable Key Vault Secret` is a separate Azure SDK custom action. It uses the
`DefaultAzureCredential` identity that runs ChaosForge, rather than the Chaos
Studio identity, and requires **Key Vault Secrets Officer** on the target vault.
Do not substitute the certificate role for the secret role, or the secret role
for the certificate role.

## Azure SDK Custom Experiments

Azure SDK custom experiments use the identity running ChaosForge through
`DefaultAzureCredential`. They do not use `chaosforge-managed-identity`, which is
reserved for Azure Chaos Studio classic fault execution. In CI/CD, use a
least-privilege workload identity or service principal with write access only to
the selected target resource and any explicitly selected child resource.

### Enterprise TLS Inspection

Azure SDK connections keep TLS certificate verification enabled. If a corporate
proxy presents a certificate signed by an internal CA, install or export that CA
bundle and set one of these variables before starting ChaosForge:

```bash
export REQUESTS_CA_BUNDLE=/path/to/enterprise-ca.pem
# Or, when your environment standardizes on it:
export SSL_CERT_FILE=/path/to/enterprise-ca.pem
```

The Key Vault secret action validates that the configured bundle exists and uses
it for its HTTPS transport. Do not disable TLS verification to bypass a
certificate error.

Fault durations use ISO-8601 in both Web and CLI, such as `PT5M`. ChaosForge
converts the value to seconds internally for local Azure SDK hold actions before
running the configured rollback.

Generate a read-only RBAC plan for a campaign with:

```bash
chaosforge permissions campaign.yaml --format markdown
```

The report separates the runtime identity from `chaosforge-managed-identity`.
It also shows setup-only bootstrap authority: `Managed Identity Contributor` on
the UAMI resource group and `Owner or User Access Administrator` at the selected
target scope. The generated Azure CLI commands contain principal-ID placeholders,
are never executed automatically, and do not prove that current assignments are
already sufficient.

Both Web and interactive CLI select the same Azure resource group and ARM target
resource. The selected `resource_id` is stored in campaign YAML and passed to the
same provider action, lifecycle check, rollback, evidence, and report path.

Azure YAML may use `resource_name` with `subscription_id` and `resource_group`
for supported root component targets. Authenticated preflight resolves the name
to its canonical ARM `resource_id` using the selected component's expected Azure
resource type. `resource_name` and `resource_id` are mutually exclusive, and
exports always retain the canonical ARM ID. See [YAML Campaign
Execution](../user-guide/yaml-execution.md#azure-resource-names) for the
accepted form and exclusions.

For the VM reboot experiment backed by Chaos Toolkit, ChaosForge keeps the
selected ARM resource ID as the campaign target and builds the required Azure
Resource Graph filter internally. Operators do not enter Resource Graph syntax in
the Web or CLI interfaces.

| Component | Custom experiment | Rollback behavior |
|---|---|---|
| PostgreSQL Flexible Server | Restart Server | Waits for the server to return; no persistent setting is changed. |
| PostgreSQL Flexible Server | Remove Firewall Rule | Recreates only the selected rule with its captured start/end address range. |
| Container Apps | Restart Revision | Waits for the selected revision operation; no persistent setting is changed. |
| Container Apps | Shift Revision Traffic | Restores the complete captured revision traffic allocation. |
| Container Apps | Deactivate Revision | Restores the revision only when it was active before the experiment. |
| App Service | Deployment Slot Swap | Swaps the captured source and target slots back. |
| Function App | Deployment Slot Swap | Swaps the captured source and target slots back. |
| Key Vault | Disable Secret | Restores the selected secret version's prior enabled state. |
| Cosmos DB | Disable Public Access | Restores the captured `publicNetworkAccess` value. |
| Event Hubs | Disable Namespace Public Access | Holds public access disabled for the configured duration, then restores the captured namespace setting. |
| Virtual Machine | Disable Boot Diagnostics | Restores the complete captured boot diagnostics configuration. |
| VM Scale Set | Disable Overprovision | Restores the captured `overprovision` value. |
| VM Scale Set | Reboot Virtual Machine Scale Set | Restarts selected instances, or one randomly chosen instance when none are selected. |
| Event Hubs | Change Event Hub State | Captures each selected entity state, applies the requested state for the configured duration, then restores each captured state. |
| App Service | Stop App Service | Captures the selected app's running state and starts it only when it was originally running. |
| PostgreSQL Flexible Server | Stop Server | Captures the selected server's running state and starts it only when it was originally running. |

Custom experiments are implemented below the owning component rather than in an
interface-specific directory:

```text
providers/azure/components/<component>/experiments/custom/
├── actions/
└── definitions/
```

The lifecycle runner captures an ARM baseline before execution, validates the
target after execution, runs any provider-defined rollback for reversible
experiments, validates recovery against the baseline, and records all phases in
the normal evidence bundle and execution report.

The Event Hubs, App Service, and PostgreSQL stop actions use exact selected ARM
resource IDs rather than Azure Resource Graph filters. This prevents rollback
from starting a different target or a resource that was already stopped before
the experiment. Event Hubs `*` expands to concrete entities before capture; the
rollback restores each entity's own captured state.

### Safety Boundaries

- Use non-production targets first.
- Select only a dedicated PostgreSQL firewall rule; ChaosForge never creates,
  deletes, or restores unrelated rules.
- Slot swap requires two existing slots. Review the source and target names
  before execution.
- Key Vault secret disruption requires a selected secret and affects its latest
  version. Use a dedicated test secret.
- Network-access disruptions can isolate workloads and pipeline runners. Verify
  a safe recovery path before execution.
- Container Apps traffic and scale actions restore only the exact state captured
  at the beginning of that execution.

### Virtual Machines and VM Scale Sets

The Web form loads Virtual Machines and VM scale sets from the selected resource
group. Selecting **Reboot Virtual Machine** targets the selected VM through the
Chaos Toolkit Azure action. Selecting **Reboot Virtual Machine Scale Set** uses a
direct Azure Compute SDK action and supports an optional checkbox list of VMSS
instances. When one or more instances are selected, ChaosForge restarts each
selected instance. When none are selected, ChaosForge selects one available
instance at random.

For YAML or CLI execution, optional VMSS reboot targeting uses instance criteria,
for example:

```yaml
instance_criteria:
  - instanceId: "0"
  - instanceId: "2"
```

**Shutdown Scale Set Instance** is a separate Azure Chaos Studio classic fault.
It requires one or more explicit VMSS instance IDs. In the Web form, the IDs are
loaded as checkboxes after selecting the scale set and are serialized as the JSON
array required by Azure Chaos Studio. YAML and CLI users provide the same array,
for example:

```yaml
instances: ["0", "1"]
```

Azure Chaos Studio target and capability setup is performed before classic fault
execution. The experiment identity requires **Virtual Machine Contributor** on
the selected VMSS or an inherited scope. If Azure Chaos Studio rejects a started
classic experiment, ChaosForge includes Azure's action-level failure detail in
the lifecycle output and evidence bundle.

## Azure Kubernetes Service

AKS experiments are cataloged as Azure Chaos Studio experiments. Supported AKS
Chaos Mesh faults are submitted through Azure Chaos Studio's native AKS Chaos
Mesh target and capabilities; selected node-level operations use direct
Kubernetes or VMSS operations. The implementation is under
`chaosforge/providers/azure/components/aks/`.

The selected subscription is read-only in the Web form. Both CLI and Web then
load resource groups dynamically. AKS cluster context and location come from the
selected AKS setup context; operators do not enter an Azure location per
experiment.

### Prerequisites

- Access to the target subscription, resource group, and AKS cluster
- A valid Kubernetes context
- Azure Chaos Studio target and capability permissions
- Chaos Mesh and RBAC for experiments that use Chaos Mesh resources

Kubernetes operations use the Python client. `kubectl` is optional and is used
only as a compatibility fallback for an unsupported command shape or for manual
troubleshooting.

### Chaos Mesh Version Policy

ChaosForge applies the same campaign-scoped version policy to AKS and EKS. AKS
Chaos Mesh experiments use the Helm release `chaos-mesh-studio` in namespace
`chaos-testing`; ChaosForge is validated against and installs version `2.8.7`.

Before the first applicable AKS Chaos Mesh experiment for a selected cluster:

- An absent release offers Install `2.8.7` or Cancel.
- An older `2.8.x` release offers Upgrade, Continue, or Cancel.
- Exact `2.8.7` continues without prompting.
- A newer `2.8.x` release shows a warning and continues without downgrade.
- A different major/minor release is blocked because bundled CRD schemas may not
  match.

The decision is remembered per campaign and AKS context while the detected
installed version remains unchanged. Clearing or creating another campaign asks
again. Decisions are local draft state and are not exported to portable YAML.
CLI and Web present the same choices before execution; the Web binds them to its
one-time permission-review token.

AKS node drain, node taint, direct node stress, and node shutdown/zone
paths do not depend on the managed Chaos Mesh Helm release and therefore do not
trigger this review. Pod, container, crashloop, network, workload stress, DNS,
HTTP, I/O, time, and control-plane Chaos Mesh experiments do. Crashloop is a
special case: it repeatedly creates `PodChaos` resources directly rather than
starting an Azure Chaos Studio experiment, but still requires the same installed
Chaos Mesh release.

Upgrades pin `2.8.7`, use Helm `--reuse-values`, wait for completion, and never
downgrade a newer release. Execution checks that the installed version still
matches the reviewed version before changing the cluster.

### Execution Lifecycle

AKS execution performs target discovery, safety checks, baseline capture, fault
injection, rollback, post-checks, and evidence logging. Kubernetes and Chaos Mesh
validation for equivalent faults is shared with EKS. Azure subscription,
identity, VM scale set, resource-group, and Chaos Studio checks remain specific
to AKS.

The AKS catalog contains no user-visible Chaos Toolkit experiments. ChaosForge's
current implementation uses a JSON workflow definition and the shared definition
runner to sequence AKS setup, Azure Chaos Studio start, validation, and cleanup.
That is an internal orchestration detail: the campaign engine remains **Azure
Chaos Studio**, and the fault is executed by Azure Chaos Studio or by the
explicitly documented direct Kubernetes/VMSS exception.

Shared Kubernetes post-validation distinguishes blocking recovery failures from
advisory observations. A warning-only result, such as recent probe events that
remain in the observation window after network-delay cleanup, is reported as
`SUCCESS_WITH_WARNINGS`. It remains visible with its check name and detail in
the lifecycle report, Web log, and evidence bundle. Cleanup failures and failed
blocking recovery checks continue to report `FAILED`.

Use a dedicated non-production cluster, review namespace/workload/node blast
radius, and verify both Kubernetes cleanup and Azure Chaos Studio execution
state.

## Azure Cache for Redis

Redis reboot is an Azure Chaos Studio Experiments (classic) service-direct fault. Cache flush and
access disruption are custom Azure Resource Manager operations because Azure
Chaos Studio does not provide those Redis faults.

Redis Reboot dispatches directly to Azure Chaos Studio; it does not run through
the Chaos Toolkit definition runner. ChaosForge polls the Azure experiment
execution resource and treats both Azure terminal success values, `Success` and
`Succeeded`, as successful completion. It includes Azure action-level execution
details when the execution fails.

The authenticated subscription is selected automatically. CLI and Web users
then choose a dynamically discovered resource group and Redis cache. Redis does
not require an AKS cluster or kubeconfig context.

Redis Reboot uses the reusable user-assigned identity named
`chaosforge-managed-identity`. The identity must have **Redis Cache Contributor**
on the selected Redis cache or an inherited resource-group/subscription scope.
CLI and Web validate this before execution and can explicitly bootstrap the
identity and target role when the operator has the required Azure RBAC authority.

The reboot action requires the Azure Identity, Chaos Management, Redis Management,
and Resource Management SDK packages declared in `requirements.txt`. It registers
the `Microsoft.Chaos` resource provider, creates the Redis target and reboot
capability, then creates and starts the Chaos Studio experiment. If the local
environment has a missing or incompatible SDK package, the error identifies the
specific module and directs the operator to reinstall requirements:

```bash
python -m pip install --upgrade -r requirements.txt
```

For non-clustered caches, ChaosForge sends only the `RebootType` parameter.
`ShardId` is sent only when Azure reports a clustered cache, because Azure Chaos
Studio rejects `ShardId` for non-clustered caches.

| Experiment | Engine | Azure operation |
|---|---|---|
| Reboot Redis | Azure Chaos Studio | `urn:csci:microsoft:azureClusteredCacheForRedis:reboot/1.0` |
| Flush Cache | Custom Azure SDK action | `RedisManagementClient.redis.begin_flush_cache` |
| Cache Access Disruption | Custom Azure SDK action | `RedisManagementClient.redis.begin_update` public-network-access setting |

Redis experiments are organized by their actual execution mechanism:

```text
azure_redis/experiments/
├── chaos_studio/
│   ├── actions/
│   └── definitions/
└── custom/
    ├── actions/
    └── definitions/
```

### Lifecycle Evidence

All Redis experiments use the shared lifecycle runner and generate pre-check,
chaos-execution, post-validation, and evidence artifacts. The pre-check captures
cache identity, provisioning state, SKU, and public-network-access configuration.
Reboot validates that the cache returns to `Succeeded`; access disruption
validates that rollback restores the original public-network-access setting.
Flush validates that the cache remains available but is marked non-recoverable
because deleted cache data cannot be restored.

### Safety

- Cache flush is irreversible.
- Redis reboot can cause brief unavailability and possible data loss.
- Access disruption changes public network access and relies on rollback to
  restore the captured setting.
- Validate every operation in a non-production subscription first.
