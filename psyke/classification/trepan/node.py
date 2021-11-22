from __future__ import annotations
from typing import Iterable, Any
import pandas as pd


class Node:

    def __init__(self, samples: pd.DataFrame, n_examples: int, constraints: Iterable[tuple[str, float]] = None,
                 children: list[Node] = None):
        self.samples = samples
        self.n_examples = n_examples
        self.constraints = [] if constraints is None else constraints
        self.children = [] if children is None else children

    def __str__(self):
        name = ''.join(('' if c[1] > 0 else '!') + c[0] + ', ' for c in self.constraints)
        return name[:-2] + ' = ' + str(self.dominant)

    @property
    def priority(self) -> float:
        return -(self.reach * (1 - self.fidelity))

    @property
    def fidelity(self) -> float:
        return 1.0 * self.correct / self.samples.shape[0]

    @property
    def reach(self) -> float:
        return 1.0 * self.samples.shape[0] / self.n_examples

    @property
    def correct(self) -> float:
        return sum(self.samples.iloc[:, -1] == self.dominant)

    @property
    def dominant(self) -> Any:
        return self.samples.iloc[:, -1].mode()[0]

    @property
    def n_classes(self) -> int:
        return len(set(self.samples.iloc[:, -1]))

    def as_sequence(self) -> list[Node]:
        return self.__as_sequence([])

    def __as_sequence(self, result: list[Node]) -> list[Node]:
        for child in self.children:
            child.__as_sequence(result)
        result.append(self)
        return result
