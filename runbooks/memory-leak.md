# Memory growth / leak

## Symptoms
HighMemory alert, RSS climbing steadily under constant load, eventual OOM restarts.

## Diagnosis
1. Confirm growth is monotonic and proportional to traffic.
2. Find the first commit after which growth started.

## Remediation
- Short term: restart the service to reclaim memory.
- Real fix: roll back the offending commit.
