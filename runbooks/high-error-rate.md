# High 5xx error rate

## Symptoms
HighErrorRate alert, upstream_errors_total rising, ERROR lines in service logs.

## Diagnosis
1. Check which service the errors originate in vs which service only propagates them (gateway usually propagates).
2. Look for a deploy or config change shortly before the alert start.
3. Check downstream dependencies for timeouts.

## Remediation
- If a recent deploy correlates: roll back to the previous sha.
- If a dependency is failing: fix or restart the dependency, not the caller.
