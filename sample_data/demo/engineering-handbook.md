# Engineering Handbook

## Code review

Every change to the main branch needs at least one approving review. Keep pull requests under 400 changed lines so reviewers can concentrate, and describe what changed and how you tested it. Reviewers respond within one working day.

## Branching and releases

We use short-lived feature branches merged into main after review. Releases are cut from main every Tuesday and Thursday, and each release is tagged with a semantic version number and an automatically generated changelog.

## Testing standards

New code ships with unit tests, and anything touching the database also needs an integration test against a real PostgreSQL instance. The continuous integration pipeline blocks merging when tests fail or when coverage drops below 80 percent.

## On-call rotation

Engineers join the on-call rotation after six months. Each shift lasts one week, and the primary responder acknowledges pages within fifteen minutes. On-call engineers receive compensatory time off the week after their shift.

## Incident postmortems

After every customer-facing outage we hold a blameless postmortem within five working days. The write-up covers the timeline, root cause, and concrete follow-up actions with owners. The goal is to fix systems, not to find someone to blame.

## Database migrations

Schema changes are made with reviewed migration scripts, never by hand in production. Every migration must be reversible and safe to run while the old version of the application is still serving traffic.

## Monitoring and alerts

Services expose latency, error rate, and saturation metrics. Alerts must be actionable and link to a runbook. An alert that fires without requiring action is treated as a bug and is tuned or deleted.

## Dependency updates

Automated tooling opens weekly pull requests for dependency updates. Security patches are merged within two working days, and major version upgrades are scheduled deliberately instead of being merged automatically.
