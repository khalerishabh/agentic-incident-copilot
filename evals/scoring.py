from dataclasses import dataclass


@dataclass
class Score:
    service_correct: bool
    category_correct: bool
    commit_correct: bool

    @property
    def fully_correct(self) -> bool:
        return self.service_correct and self.category_correct and self.commit_correct


def score(predicted: dict | None, truth: dict) -> Score:
    if not predicted:
        return Score(False, False, False)
    return Score(
        service_correct=predicted.get("service") == truth["service"],
        category_correct=predicted.get("category") == truth["category"],
        commit_correct=(predicted.get("culprit_commit") or None) == truth.get("culprit_commit"),
    )
