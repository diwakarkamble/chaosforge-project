# Testing and Validation

## Local Checks

```bash
python -m ruff check chaosforge tests scripts loadtests
python -m pytest tests
git diff --check
```

Coverage reports can be generated with:

```bash
python -m pytest tests \
  --cov=chaosforge \
  --cov-fail-under=100 \
  --cov-report=term-missing \
  --cov-report=xml:coverage/coverage.xml \
  --cov-report=html:coverage/html
```

## Test Levels

- Unit tests mock cloud SDK and Kubernetes API calls.
- Catalog tests verify metadata and definition resolution.
- Lifecycle tests verify state transitions, validation, recovery, and evidence.
- Native AWS FIS tests verify component-bound target selection, direct boto3
  execution without Chaos Toolkit, template cleanup, and component prerequisites.
- Lambda FIS tests verify S3 configuration-prefix handling, AWS SSM extension
  resolution, Lambda/FIS role validation, and environment restoration.
- Interruption tests verify that configured rollback/provider cleanup completes
  before CLI or Web shutdown, including cleanup of created Chaos Mesh resources.
- Profile-parity tests verify that equivalent AKS and EKS Chaos Mesh faults use
  the same shared validation facade.
- Kubernetes lifecycle tests verify advisory-only post-validation produces
  `SUCCESS_WITH_WARNINGS`, preserves the named warning in evidence, and does
  not prevent a campaign from continuing. Blocking validation failures must
  still produce `FAILED`.
- Timezone tests verify the shared CLI/Web settings file, Berlin daylight-saving
  conversion, China Standard Time through `Asia/Shanghai`, and UTC evidence
  preservation.
- Interface tests verify CLI and Web routing without performing live faults.
- YAML tests cover byte limits, UTF-8 decoding, duplicate keys, schema and
  semantic validation, provider compatibility, round trips, Web review tokens,
  CLI import/export, and cart rendering.
- Live tests require an explicitly authorized non-production environment.

## Experiment Acceptance

A successful provider API call is not sufficient. Validate:

1. The intended target was resolved.
2. The provider accepted and completed the action.
3. The expected fault effect was observable where practical.
4. Rollback or automatic recovery completed.
5. Target health returned to the required state.
6. Evidence contains provider status and failure reasons.

The project maintains 100% line coverage for the `chaosforge` package. Use the
strict local release check above before merging changes. GitLab CI retains a 95%
minimum floor on Python 3.14 as a safety net, but 100% is the required engineering
standard for completed work.
