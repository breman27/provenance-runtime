"""Errors carry machine-readable codes and the offending record."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    code: str
    node_id: str | None
    detail: str


class ProvenanceError(ValueError):
    def __init__(self, problem: Problem):
        self.problem = problem
        super().__init__(f"{problem.code}: {problem.detail}")


def fail(code: str, detail: str, node_id: str | None = None):
    raise ProvenanceError(Problem(code, node_id, detail))
