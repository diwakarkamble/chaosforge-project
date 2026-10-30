# Campaign Management

A campaign is an ordered collection of experiments. Each experiment records its
service, definition, execution engine, target service, and input variables.

## Interactive Workflow

Run `chaosforge`, select a cloud platform, add experiments, review the campaign,
and execute all or selected entries. Campaign execution is sequential.

The interactive main menu includes **Edit Campaign Experiment**. Select the
campaign item to edit, update its metadata-driven inputs, and confirm the
prompts. ChaosForge validates the rebuilt experiment and replaces the existing
item in place; it does not add a duplicate entry. Enter `0` at the selection
prompt or `M` during input collection to cancel without changing the campaign.

The `continue_on_failure` setting controls whether later experiments run after
a failure. When disabled, remaining experiments are marked as skipped.

## Reversibility Labels

Every experiment is labelled **Reversible** or **Irreversible** in the CLI and
Web catalog, campaign, and execution views. The label is determined by the
installed ChaosForge catalog, not by the operator.

Reversible experiments restore a captured baseline or use a provider/controller
that removes the temporary fault. Irreversible experiments cannot reliably
restore original data, resource identity, topology, or external side effects.
Interactive execution lists selected irreversible experiments and requires an
explicit typed acknowledgement before it starts.

## Configuration Inputs

Each experiment catalog defines its configuration defaults, validation type,
allowed values, and numeric range. The CLI displays the default and accepts it
when Enter is pressed. The Web UI prepopulates the same default and displays
type/range hints next to configuration inputs. A blank optional configuration
value with a catalog default resolves to that default.

Targets such as cloud resources, Kubernetes workloads, and explicitly named
replacement resources remain required. Values are validated at form entry and
again before execution, so manually edited, saved, or imported campaigns cannot
send invalid configuration values to a provider action.

## Persistence

Saved campaigns are stored under `runtime/campaigns/`. Generated execution data
uses the remaining runtime directories:

```text
runtime/
├── campaigns/
├── evidence/
├── executions/
├── logs/
├── reports/
└── rollback/
```

Do not place runtime files in the repository root or commit them.

### Draft Campaigns And History

Campaign drafts are named, cloud-scoped, and retained locally after ChaosForge
exits. AWS and Azure may use the same display name, but a duplicate name is not
allowed within the same cloud. Draft changes made through the CLI or Web UI are
saved automatically, so a draft created in one interface is available in the
other after restart.

The Web **Campaign Library** is available at `/campaigns?cloud=aws` or
`/campaigns?cloud=azure`. The interactive CLI provides **Campaign Library** and
**Campaign History** from its main menu. Both show the draft creation timestamp.

A draft does not move out of **Draft Campaigns** when it is run. A run creates a
separate immutable execution snapshot, so the same draft can be edited and run
again. Deleting a draft also does not delete its prior execution-history records.
In the interactive CLI, campaign summary, editing, removal, clearing, YAML
export, and execution always use the draft for the currently selected cloud.

Every execution creates an immutable local history record before lifecycle work
starts. History records retain the campaign snapshot, final status, output when
available, report path, and the execution source: `web`, `interactive-cli`, or
`yaml-cli`. History is retained indefinitely by default and remains available
after a draft is deleted. YAML imports always create a new draft after YAML
validation and target preflight; they do not replace an existing draft.

## YAML Import And Export

The campaign summary in the interactive CLI can export the current campaign as
YAML. The CLI load screen can load a YAML file even when no saved JSON campaigns
exist. In the Web UI, **Export Campaign YAML** downloads the same portable
format, and the provider page accepts it through drag and drop.

Import is atomic: validation and review occur against a detached campaign, and
the active campaign is replaced only after confirmation. Exported YAML can be
used with `chaosforge validate`, `chaosforge plan`, and `chaosforge run`.

When browsing through the Web UI, the campaign cart remains visible at the top
of provider, service, and experiment pages. Its count represents the current
cloud-specific portion of the current local campaign. AWS pages count and show
only AWS experiments; Azure pages count and show only Azure experiments. The
campaign table preserves the original experiment indexes so edits, removal, and
selected execution still operate on the correct entries.

In the Web UI, selected experiments form an execution run. Live Web run state
remains in memory for progress polling, while the completed run record is stored
durably in `runtime/executions/`. The campaign page exposes **View Results** for
an experiment that participated in a matching run. The link opens that exact run
and focuses the experiment's log section while it remains available. Experiments
not selected for a subset run do not receive a result link for it.

The Web Campaign Library's **Execution History** provides **View Logs** for each
run. It opens the exact execution ID and reads the durable log snapshot, so it
continues to work after another campaign runs or the Web application restarts.
The execution console's log and report downloads are also bound to that run ID.

## Evidence

Each lifecycle execution records its resolved target, pre-check, injection
result, validation result, recovery information, logs, warnings, and errors.
Evidence is written as structured files and a ZIP bundle under
`runtime/evidence/`.

### Execution Outcomes

An experiment can finish with one of these outcomes:

| Outcome | Meaning | Campaign behavior |
|---|---|---|
| `SUCCESS` | Injection and all blocking lifecycle validations passed. | Continues. |
| `SUCCESS_WITH_WARNINGS` | Injection and blocking validations passed, but one or more advisory observations need review. | Continues; it is not eligible for failed-experiment retry. |
| `FAILED` | Injection, cleanup, or a blocking lifecycle validation failed. | Follows the campaign's `continue_on_failure` policy. |
| `SKIPPED` | The experiment was not run because the campaign stopped after a failure. | Not treated as a successful execution. |

`SUCCESS_WITH_WARNINGS` is still a successful execution. The lifecycle report,
Web execution log, campaign summary, and evidence identify the named advisory
checks and their details. Review those observations before reusing the same
target or broadening the experiment's blast radius.

### Report Timezone

ChaosForge stores execution and evidence timestamps in UTC. CLI and Web reports
convert those timestamps to the timezone selected in **Settings**. The default is
`Europe/Berlin`, which automatically changes between CET and CEST when daylight
saving time applies. The setting is local to the ChaosForge installation under
`runtime/settings.json`; it is not included in campaign YAML and does not alter
experiment timing.

YAML execution can set `settings.timezone` for one campaign run. That override
formats that run's report without changing `runtime/settings.json`.

When an experiment fails, ChaosForge prints a **Failure details** section before
the evidence locations. The same actionable error is included in the campaign
report and Web execution log. Use the evidence bundle for the complete captured
engine transcript and lifecycle context.

## Re-running Experiments

Run an experiment again only after its prior evidence confirms rollback or
recovery completed. S3 configuration experiments use bucket-scoped rollback
state and can be re-run after a successful restore. Other legacy provider
actions may retain operation-specific rollback state while a restore is pending
or has failed; inspect `runtime/evidence/`, provider status, and applicable
rollback artifacts before retrying those targets. Do not run overlapping
experiments against the same resource.

## Interrupting Execution

Do not close the CLI or Web process while an experiment is running. When an
operator presses Ctrl-C in the CLI, stops the local Web server with Ctrl-C, or
sends the Web process `SIGTERM`, ChaosForge waits for the active experiment to
finish its configured rollback or provider cleanup before the interface exits.
The interrupted experiment is marked failed and its cleanup outcome is recorded
in lifecycle evidence.

This only applies to graceful process termination. `SIGKILL`, a host crash, or
power loss cannot run Python cleanup code. If one occurs, use the experiment's
provider-specific rollback guidance and inspect `runtime/rollback/` and
`runtime/evidence/` before running another experiment against the target.
