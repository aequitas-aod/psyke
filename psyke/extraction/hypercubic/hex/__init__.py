from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from psyke import get_default_random_seed, Target
from psyke.extraction.hypercubic import Grid, HyperCube, GenericCube, ClassificationCube, RegressionCube
from psyke.extraction.hypercubic.gridex import GridEx


class HEx(GridEx):
    """
    Explanator implementing HEx algorithm.
    """

    class Node:
        def __init__(self, cube: GenericCube, parent: HEx.Node = None, gain: bool = True, threshold: float = None):
            self.cube = cube
            self.parent = parent
            self.children: Iterable[HEx.Node] = []
            self.gain = gain if not threshold else self.check(threshold)

        def check(self, threshold: float) -> bool:
            other = self.parent
            while not other.gain:
                other = other.parent
            if isinstance(other.cube, ClassificationCube):
                return other.cube.output != self.cube.output
            return other.cube.error - self.cube.error > threshold * .6

        def indices(self, dataframe: pd.DataFrame):
            return self.cube.filter_indices(dataframe.iloc[:, :-1])

        def eligible_children(self, dataframe) -> Iterable[HEx.Node]:
            return [c for c in self.children if c.cube.count(dataframe) > 0]

        def permanent_children(self, dataframe) -> Iterable[HEx.Node]:
            return [c for c in self.eligible_children(dataframe) if c.gain]

        def permanent_indices(self, dataframe):
            return np.any([c.cube.filter_indices(dataframe.iloc[:, :-1])
                           for c in self.eligible_children(dataframe) if c.gain], axis=0)

        def update(self, dataframe: pd.DataFrame, predictor, recursive=False):
            if recursive:
                for node in self.children:
                    node.update(dataframe, predictor, recursive)
            cleaned = [(c.cube, c.gain) for c in self.eligible_children(dataframe)]
            idx = self.permanent_indices(dataframe)

            if sum(g for _, g in cleaned) > 0 and sum(self.indices(dataframe)) > sum(idx) and self.gain:
                self.cube.update(dataframe[self.indices(dataframe) & ~idx], predictor)
            return cleaned

        def linearize(self, dataframe):
            children = [c.linearize(dataframe) for c in self.permanent_children(dataframe)]
            return [cc for c in children for cc in c if c != []] + list(self.permanent_children(dataframe))

    def __init__(self, predictor, grid: Grid, min_examples: int, threshold: float, output: Target = Target.CONSTANT,
                 discretization=None, normalization=None, seed: int = get_default_random_seed()):
        super().__init__(predictor, grid, min_examples, threshold, output, discretization, normalization, seed)
        self._default_surrounding_cube = True

    def _gain(self, parent_cube: GenericCube, new_cube: GenericCube) -> float:
        if isinstance(parent_cube, ClassificationCube):
            return parent_cube.output != new_cube.output
        return parent_cube.error - new_cube.error > self.threshold * .6

    def _iterate(self, surrounding: HyperCube, dataframe: pd.DataFrame):
        fake = dataframe.copy()
        surrounding.update(dataframe, self.predictor)
        root = HEx.Node(surrounding)
        current = [root]

        for iteration in self.grid.iterate():
            next_iteration = []
            for node in current:
                children, fake = self._cubes_to_split(node.cube, surrounding, iteration, dataframe, fake, True)
                node.children = [HEx.Node(c, node, threshold=self.threshold) for c in children]
                cleaned = node.update(fake, self.predictor, False)
                node.children = [HEx.Node(c, node, threshold=self.threshold) for c in self._merge(
                    [c for c, _ in cleaned], fake)]
                next_iteration += [n for n in node.permanent_children(fake)]

            current = next_iteration.copy()
        _ = root.update(fake, self.predictor, True)
        self._hypercubes = [c.cube for c in root.linearize(fake)]

        if len(self._hypercubes) == 0:
            self._hypercubes = [surrounding]
        elif not min(np.any([c.filter_indices(dataframe.iloc[:, :-1]) for c in self._hypercubes], axis=0)):
            self._hypercubes = self._hypercubes + [surrounding]
