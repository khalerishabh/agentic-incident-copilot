"""Eval loop (fill in during week 5):

for each incident x system in (baseline, multi_agent) x N repeats:
    1. reset all faults, wait for metrics to settle
    2. inject fault, wait for the alert to fire, record t_alert
    3. run the system, record t_diagnosis, tokens, tool calls, tool failures
    4. score root cause against ground truth
    5. append a row to evals/results/<run_id>.jsonl
then aggregate: accuracy, mean time to diagnosis, tokens and cost per incident,
tool-call failure rate, with mean and std across repeats.
"""
from pathlib import Path

import yaml

INCIDENTS = Path(__file__).with_name("incidents.yaml")


def load_incidents() -> list[dict]:
    return yaml.safe_load(INCIDENTS.read_text())


if __name__ == "__main__":
    for inc in load_incidents():
        print(inc["id"], inc["inject"], "->", inc["ground_truth"])
