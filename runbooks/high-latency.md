# High latency

## Symptoms
HighLatencyP95 alert, slow requests logged with large duration_ms.

## Diagnosis
1. Compare p95 across services to find where latency is introduced, not where it is observed.
2. Check CPU saturation, slow database queries and downstream timeouts.

## Remediation
- CPU bound: scale replicas.
- Slow query: add index or roll back query change.
