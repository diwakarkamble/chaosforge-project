# AWS and AWS FIS

ChaosForge supports AWS configuration experiments through Chaos Toolkit and
fault injection through AWS Fault Injection Service.

## Authentication

AWS operations use the boto3 credential chain. Confirm the active account and
region before building a campaign. FIS execution additionally requires a role
that AWS FIS can assume and permission for ChaosForge to pass that role.

## Permission Plans

Use the read-only campaign permission command before applying CI/CD access:

```bash
chaosforge permissions campaign.yaml --format json
```

ChaosForge aggregates each selected experiment's catalog IAM actions into a
copyable policy document. The first version uses `Resource: "*"` when existing
catalog metadata does not contain a safe resource-scoping rule and emits a
warning for that statement. Review and narrow wildcard statements against AWS IAM
action-level resource support before applying them to a production role.

The Web permission review separates AWS FIS responsibilities: the AWS identity
running ChaosForge receives FIS control-plane permissions and a scoped
`iam:PassRole` requirement for the configured FIS execution role; the FIS
execution role card lists the modeled action permissions that AWS FIS uses to
inject the selected fault. Cards show every selected experiment that requires
the assignment. Action-specific prerequisite notes, such as Lambda FIS S3
configuration access, are shown alongside the affected execution-role card.

## FIS Execution

The FIS catalog is stored in `chaosforge/providers/aws/fis/catalog.json`.
ChaosForge builds an experiment template, starts it, waits for a terminal FIS
state, checks action status, and optionally deletes the template. API acceptance
or an `initiating` state is not treated as successful execution.

The standalone **AWS FIS** component is for operating on existing account
templates: **Start FIS Experiment Template**, **Stop Running FIS Experiment**,
and **Delete FIS Template**. Start and delete forms load the experiment-template
dropdown dynamically from the selected AWS region, showing the template ID and
description. The former standalone create/list entries are intentionally absent:
component-bound FIS actions create and start their own templates through the
normal component experiment flow, and template listing is part of the selector.

`fis-create-experiment` remains an internal catalog wrapper for those
component-bound workflows. It must not be shown as a standalone AWS FIS catalog
option, but it must remain resolvable for existing component links, campaigns,
and execution paths.

Duration fields use ISO 8601 syntax, for example `PT30S`, `PT1M`, or `PT1H`.
AWS FIS receives this value directly. For legacy Chaos Toolkit actions that
consume numeric wait seconds, ChaosForge converts the ISO value immediately
before execution while preserving ISO-8601 in campaign YAML.

### Lambda FIS Prerequisites

For Web **Lambda** FIS actions, select the target Lambda function and an S3
configuration bucket in the same region. At execution time,
ChaosForge uses the AWS SDK to create the `FisConfigs/` prefix only when it is
absent, query the AWS Systems Manager public parameter for and attach the latest
AWS-managed FIS extension release for the function's architecture, replacing
only an existing FIS extension layer while preserving all unrelated layers. The
extension is published by AWS and does not require a user-provided layer ARN.
The active AWS identity requires `ssm:GetParameter` on the public FIS extension
parameter to resolve the latest release. ChaosForge then configures the Lambda
FIS environment variables. It adds the
required S3 read policy to the Lambda execution role and S3 write/delete policy
to the selected FIS role. The form previews both bucket-scoped policies before
execution, using `your_s3_bucket` until a bucket is selected.

When **Delete Template After Completion** is `Y`, ChaosForge deletes the FIS
template and restores only the three Lambda FIS environment variables it
changed. It does not delete the selected S3 bucket, the `FisConfigs/` prefix,
the extension layer, or the inline IAM policies, so review and remove those
long-lived prerequisites separately when they are no longer required.

All native Lambda FIS actions are owned by the Lambda component at
`providers/aws/components/lambda/experiments/fis/`. They execute directly with
the AWS SDK and AWS FIS APIs; they are not Chaos Toolkit experiments. Lambda FIS
lifecycle checks verify the target function and roles, the bucket region and
`FisConfigs/` prefix, the FIS extension/environment state after execution, and
environment restoration for auto-delete runs.

### Component FIS Targets

When an FIS action is opened from an AWS component, ChaosForge already knows the
service and action. Web and CLI therefore collect only the action parameters,
FIS role, and the required target resource. The target selector is populated
dynamically for supported EC2/EBS, RDS, DynamoDB, ElastiCache, ECS, S3, Kinesis,
and IAM-role FIS targets. Native AWS FIS templates are created, started, polled,
and optionally deleted through boto3, not through Chaos Toolkit.

For S3 **Pause Bucket Replication**, **Destination Bucket(s)** is optional. Leave
it blank to use the AWS FIS default destination selection; ChaosForge omits the
`destinationBuckets` action parameter.

### Amazon RDS

The native RDS **Provisioned IOPS Modification** experiment applies and restores
`AllocatedStorage` together with `Iops`, as required by RDS instances using
provisioned IOPS storage. The experiment requires `io1`, `io2`, or `gp3` storage
and an IOPS value above the configured minimum; it cannot reduce an instance
already at the minimum. **Target IOPS (% of current, decrease only)** sets the
target to `current IOPS * percentage / 100`; for example, `2000` with `50`
targets `1000`. It never increases IOPS, and an instance already at `1000`
cannot run this experiment.

The component-bound AWS FIS **Failover DB Cluster** action targets an Aurora/RDS
cluster ARN with the AWS FIS contract `resourceType: aws:rds:cluster` and action
target key `Clusters`. It has no action parameters. In contrast, **Reboot DB
Instances** targets `aws:rds:db`; its optional `forceFailover` parameter applies
only to Multi-AZ DB instance reboot behavior.

Instance-class modification asks RDS for valid replacements using
`DescribeValidDBInstanceModifications`. If AWS returns no alternate class for the
specific engine, version, deployment, and region, ChaosForge stops before making
a change; choose a compatible disposable fixture rather than guessing a class.
Web and CLI present these AWS-approved full class names as a selector after the
RDS instance is chosen. An empty selector means AWS has no valid replacement for
that instance.

## Amazon API Gateway

The **Stage Variables Modification** experiment uses API Gateway's `replace`
patch operation for both creating and updating a stage variable. This is required
when a stage has no existing variables: API Gateway rejects `add` at
`/variables/<name>` in that case. Rollback uses the same compatible operation to
restore an original variable and removes variables introduced by the experiment.

## Amazon ElastiCache

ElastiCache experiments select the resource type supported by their corresponding
AWS API. CLI and Web expose the same selector for each experiment:

| Experiment | Target type | API |
|---|---|---|
| Security Group Modification | Redis replication group | `ModifyReplicationGroup` |
| Snapshot Retention Modification | Redis replication group | `ModifyReplicationGroup` |
| Daily Snapshot Configuration | Redis replication group | `ModifyReplicationGroup` |
| Reboot Cache Cluster | Cache cluster | `RebootCacheCluster` |
| Usage Limit Modification | Serverless cache | `ModifyServerlessCache` |

Usage limits are an ElastiCache Serverless-only capability; provisioned Redis
replication groups do not expose an equivalent setting. Snapshot retention on a
replication group automatically uses its configured snapshotting cluster, or its
first member cache cluster when none is configured. A reboot waits for the cache
cluster to return to `available` before lifecycle post-validation begins.

## Validation

Lifecycle support depends on the experiment. Lambda FIS actions include target,
prerequisite, post-execution, and recovery validation. EC2 stop, reboot, and
terminate operations include target-state checks. For other transient faults,
use AWS FIS execution details and workload telemetry as the primary effect
evidence.

## Amazon S3

S3 configuration experiments cover bucket versioning, default encryption,
public-access block settings, lifecycle configuration, and bucket policies. The
selected bucket is supplied as `bucket_name` in CLI, Web, and YAML campaigns.
Before injection, ChaosForge verifies that the bucket is reachable and captures
its relevant configuration for post-execution recovery validation. The active
AWS identity needs permission for `s3:HeadBucket` as well as the experiment's
listed read and mutation actions.

The **Public Access Block** experiment is deliberately an access-control fault:
it temporarily sets all four bucket-level controls to `false`
(`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, and
`RestrictPublicBuckets`) and then restores the exact captured configuration.
It is rejected before injection when none of those controls is enabled, because
the experiment would otherwise have no observable effect. This does not change
account-level S3 Block Public Access settings.

## Amazon EKS and Chaos Mesh

ChaosForge executes Kubernetes-native faults against Amazon EKS through Chaos
Mesh. It resolves Kubernetes targets, validates prerequisites, builds custom
resources, creates them through the Kubernetes API, monitors execution, and
collects lifecycle evidence.

The Amazon EKS catalog also includes direct Kubernetes experiments executed by
Chaos Toolkit: Node Drain, Node Cordon, Replica Reduction, and Container
Restart. Node Drain and Node Cordon automatically uncordon the selected node
during rollback. Replica Reduction restores the captured replica count.
Container Restart deletes the selected pod and relies on its owning Kubernetes
controller to recreate it, so choose a pod managed by a Deployment, ReplicaSet,
StatefulSet, or equivalent controller.

Equivalent AKS and EKS faults reuse shared validation profiles for pre-checks,
during-fault observation, and post-cleanup validation across pod, network,
stress, DNS, HTTP, I/O, and time faults. EKS-only experiments remain unmapped
until an equivalent validation profile exists.

For direct workload faults, CLI and Web use the same target flow: EKS cluster,
namespace, target mode, then a Deployment or exact Pod. **Container Kill** then
loads its required Container selector from the selected Pod, or from the matching
Pods of the selected Deployment. In the Web form, changing target mode,
Deployment, or Pod reloads that Container selector. Exact-Pod targeting forces
Chaos Mesh mode to `one`.

Shared Kubernetes post-validation distinguishes blocking recovery failures from
advisory observations. For example, a recent probe-failure event can be retained
as an advisory warning when the fault is cleaned up and the required recovery
checks pass. Such a run is reported as `SUCCESS_WITH_WARNINGS`, not `FAILED`.
Residual fault configuration, unavailable service endpoints, or other blocking
recovery failures still fail the experiment. Review named warnings in the
lifecycle report and `runtime/evidence/`.

### Prerequisites

- A reachable EKS cluster and valid kubeconfig context
- Chaos Mesh compatible with the bundled schemas
- Kubernetes RBAC for the selected Chaos Mesh resources and namespaces
- Helm only when Chaos Mesh installation is requested

### Chaos Mesh Version Policy

ChaosForge is validated against and installs Chaos Mesh `2.8.7`. Before the
first direct Chaos Mesh experiment for each EKS cluster in a campaign, it reads
the installed Helm chart version:

- If Chaos Mesh is absent, interactive CLI and Web users can install `2.8.7` or
  cancel execution.
- If the installed version is an older `2.8.x` release, users can upgrade to
  `2.8.7`, continue with the installed release, or cancel.
- If `2.8.7` is installed, execution continues without a choice.
- If a newer `2.8.x` release is installed, ChaosForge shows a compatibility
  warning and continues without downgrading it.
- A different major or minor release is blocked because the bundled CRD schemas
  may not match it.

Install/continue/upgrade decisions are remembered per campaign, AWS region, and
EKS cluster. A saved decision is reused only while the detected installed version
and ChaosForge target version remain unchanged. Clearing or creating another
campaign requires a new decision. Decisions are local draft state and are not
included in portable campaign YAML.

Upgrades use Helm `--reuse-values`, pin `2.8.7`, wait for completion, and rerun
Chaos Mesh preflight before fault injection. Existing newer releases are never
downgraded.

Kubernetes operations use the Python client. `kubectl` is optional and is used
only as a compatibility fallback for an unsupported command shape or for manual
troubleshooting.

### Node Drain Safety

Node Drain evicts controller-managed workloads and does not force eviction of
unmanaged pods. If the selected node hosts a pod without owner references, the
experiment stops with an actionable error and rolls back the cordon. Remove the
pod or assign it an owning controller before retrying. Review PodDisruptionBudget
constraints and local-storage workloads before enabling **Delete Pods With Local
Storage**.

RBAC is cluster- and namespace-specific. Grant only the required Chaos Mesh CRD
verbs and target-resource access. Use explicit namespaces and selectors, and
confirm cleanup because schedules and workflows can outlive the initiating
process.

## Safety

- Select explicit resources and verify generated ARNs.
- Keep FIS blast radius percentages conservative.
- Configure stop conditions where organizational policy requires them.
- Confirm provider-side action status and the application-level effect.
- Verify resolved EKS pods, nodes, volumes, and Chaos Mesh cleanup.
