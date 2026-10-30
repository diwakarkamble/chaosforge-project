# Adding a Cloud Provider

Adding a provider requires coordinated changes across discovery, metadata,
execution, lifecycle validation, interfaces, tests, and documentation.

## Procedure

1. Create `chaosforge/providers/<provider>/` and keep SDK-specific code there.
2. Add component discovery methods that return stable resource identities and
   display names.
3. Add experiment metadata and provider-owned definitions/actions.
4. Add or extend an execution engine under `chaosforge/engines/` only when the
   provider cannot use an existing engine.
5. Register dispatch through `ExecutionDispatcher`.
6. Add lifecycle adapters and checks for observable target state.
7. Expose equivalent target and parameter handling in CLI, YAML planning, and
   Web paths where supported.
8. Store generated state through `repository_paths()` below `runtime/`.
9. Add unit tests with mocked provider APIs and catalog-integrity tests.
10. Update the provider guide and project context.

## Required Design Properties

- No credentials or environment identifiers in source control.
- No provider mutations during import or discovery.
- Explicit timeout and terminal-state handling for asynchronous operations.
- Idempotent or guarded rollback.
- Clear distinction between API acceptance, fault application, and recovery.
- Package-relative static resources and repository-rooted runtime artifacts.
