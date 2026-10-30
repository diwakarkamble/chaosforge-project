# ChaosForge Documentation

This directory contains the maintained documentation for ChaosForge. Markdown
is the source format so changes remain searchable, reviewable, and versioned
with the implementation.

## Getting Started

- [Installation and prerequisites](getting-started/installation.md)

## User Guides

- [Campaign management](user-guide/campaigns.md)
- [YAML execution](user-guide/yaml-execution.md)
- [Web interface](user-guide/web-interface.md)

## Provider Guides

- [AWS and AWS FIS](providers/aws.md)
- [Microsoft Azure](providers/azure.md)

## Developer Guides

- [Architecture](developer-guide/architecture.md)
- [Adding a cloud provider](developer-guide/adding-a-cloud-provider.md)
- [Adding an experiment](developer-guide/adding-an-experiment.md)
- [Lifecycle validation and multi-check patterns](developer-guide/adding-an-experiment.md#lifecycle-validation)

## Validation

- [Testing and validation](validation/testing.md)

Generated reports, evidence, logs, campaign state, and rollback files belong
under `runtime/`; they are not documentation.

## Examples

Maintained portable campaign YAML files live in `examples/campaigns/`. It is the
only committed example content; empty legacy directories under `examples/` and
`chaosforge/examples/` are not version-controlled. Provider policy and RBAC
guidance is maintained in the relevant documentation instead.
