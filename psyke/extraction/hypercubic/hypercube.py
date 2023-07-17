from __future__ import annotations

import itertools
from statistics import mode
from functools import reduce
from typing import Iterable, Union
import pandas as pd
from numpy import ndarray

from psyke.extraction.hypercubic.utils import Dimension, Dimensions, MinUpdate, ZippedDimension, Limit, Expansion
from psyke.schema import Between
from psyke.utils import get_default_precision, get_int_precision, Target, get_default_random_seed
from psyke.utils.logic import create_term, to_rounded_real, linear_function_creator
from sklearn.linear_model import LinearRegression
from tuprolog.core import Var, Struct
from random import Random
import numpy as np


class FeatureNotFoundException(Exception):

    def __init__(self, feature: str):
        super().__init__(f'Feature {feature} not found.')


class Point:
    """
    An N-dimensional point.
    """

    EPSILON = get_default_precision()

    def __init__(self, dimensions: list[str], values: list[float | str]):
        self._dimensions = {dimension: value for (dimension, value) in zip(dimensions, values)}

    def __getitem__(self, feature: str) -> float | str:
        if feature in self._dimensions.keys():
            return self._dimensions[feature]
        else:
            raise FeatureNotFoundException(feature)

    def __setitem__(self, key: str, value: float | str) -> None:
        self._dimensions[key] = value

    def __eq__(self, other: Point) -> bool:
        return all([abs(self[dimension] - other[dimension]) < Point.EPSILON for dimension in self._dimensions])

    @property
    def dimensions(self) -> dict[str, float | str]:
        return self._dimensions

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(data=[self.dimensions.values()], columns=list(self.dimensions.keys()))

    def copy(self) -> Point:
        return Point(list(self._dimensions.keys()), list(self._dimensions.values()))


class HyperCube:
    """
    An N-dimensional cube holding a numeric value.
    """

    EPSILON = get_default_precision()  # Precision used when comparing two hypercubes
    INT_PRECISION = get_int_precision()

    def __init__(self, dimension: dict[str, tuple[float, float]] = None, limits: set[Limit] = None,
                 output: float | LinearRegression | str = 0.0):
        self._dimensions = self._fit_dimension(dimension) if dimension is not None else {}
        self._limits = limits if limits is not None else set()
        self._output = output
        self._diversity = 0.0
        self._barycenter = Point([], [])

    def __contains__(self, point: dict[str, float]) -> bool:
        """
        Note that a point (dict[str, float]) is inside a hypercube if ALL its dimensions' values satisfy:
            min_dim <= value < max_dim
        :param point: an N-dimensional point
        :return: true if the point is inside the hypercube, false otherwise
        """
        return all([(self.get_first(k) <= v < self.get_second(k)) for k, v in point.items()])

    def __eq__(self, other: HyperCube) -> bool:
        return all([(abs(dimension.this_dimension[0] - dimension.other_dimension[0]) < HyperCube.EPSILON)
                    & (abs(dimension.this_dimension[1] - dimension.other_dimension[1]) < HyperCube.EPSILON)
                    for dimension in self._zip_dimensions(other)])

    def __getitem__(self, feature: str) -> Dimension:
        if feature in self._dimensions.keys():
            return self._dimensions[feature]
        else:
            raise FeatureNotFoundException(feature)

    def __setitem__(self, key: str, value: tuple[float, float] | list[float]) -> None:
        self._dimensions[key] = value

    def __hash__(self) -> int:
        result = [hash(name + str(dimension[0]) + str(dimension[1])) for name, dimension in self.dimensions.items()]
        return sum(result)

    @property
    def dimensions(self) -> Dimensions:
        return self._dimensions

    @property
    def limit_count(self) -> int:
        return len(self._limits)

    @property
    def output(self) -> float | str | LinearRegression:
        return self._output

    @property
    def diversity(self) -> float:
        return self._diversity

    @property
    def barycenter(self) -> Point:
        return self._barycenter

    def _fit_dimension(self, dimension: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
        new_dimension: dict[str, tuple[float, float]] = {}
        for key, value in dimension.items():
            new_dimension[key] = (round(value[0], self.INT_PRECISION), round(value[1], self.INT_PRECISION))
        return new_dimension

    def _expand_one(self, update: MinUpdate, surrounding: HyperCube, ratio: float = 1.0) -> None:
        self.update_dimension(update.name, (
            max(self.get_first(update.name) - update.value / ratio, surrounding.get_first(update.name)),
            min(self.get_second(update.name) + update.value / ratio, surrounding.get_second(update.name))
        ))

    def filter_indices(self, dataset: pd.DataFrame) -> ndarray:
        v = np.array([v for _, v in self._dimensions.items()])
        ds = dataset.to_numpy(copy=True)
        return np.all((v[:, 0] <= ds) & (ds < v[:, 1]), axis=1)

    def filter_dataframe(self, dataset: pd.DataFrame) -> pd.DataFrame:
        return dataset[self.filter_indices(dataset)]

    def _zip_dimensions(self, other: HyperCube) -> list[ZippedDimension]:
        return [ZippedDimension(dimension, self[dimension], other[dimension]) for dimension in self._dimensions.keys()]

    def add_limit(self, limit_or_feature: Limit | str, direction: str = None) -> None:
        if isinstance(limit_or_feature, Limit):
            self._limits.add(limit_or_feature)
        else:
            self.add_limit(Limit(limit_or_feature, direction))

    def check_limits(self, feature: str) -> str | None:
        filtered = [limit for limit in self._limits if limit.feature == feature]
        if len(filtered) == 0:
            return None
        if len(filtered) == 1:
            return filtered[0].direction
        if len(filtered) == 2:
            return '*'
        raise Exception('Too many limits for this feature')

    def create_samples(self, n: int = 1, generator: Random = Random(get_default_random_seed())) -> pd.DataFrame:
        return pd.DataFrame([self._create_tuple(generator) for _ in range(n)])

    @staticmethod
    def check_overlap(to_check: Iterable[HyperCube], hypercubes: Iterable[HyperCube]) -> bool:
        checked = []
        to_check_copy = list(to_check).copy()
        while len(to_check_copy) > 0:
            cube = to_check_copy.pop()
            for hypercube in hypercubes:
                if hypercube not in checked and cube.overlap(hypercube):
                    return True
            checked += [cube]
        return False

    def copy(self) -> HyperCube:
        return HyperCube(self.dimensions.copy(), self._limits.copy(), self.output)

    def count(self, dataset: pd.DataFrame) -> int:
        return self.filter_dataframe(dataset.iloc[:, :-1]).shape[0]

    def body(self, variables: dict[str, Var], ignore: list[str], unscale=None, normalization=None) -> Iterable[Struct]:
        dimensions = dict(self.dimensions)
        # TODO: there is something strange in the tests here
        # print('search', [name for name in dimensions.keys()], 'in', (variables.keys()))
        for dimension in ignore:
            del dimensions[dimension]
        return [create_term(variables[name], Between(unscale(values[0], name), unscale(values[1], name)))
                for name, values in dimensions.items()]

    @staticmethod
    def create_surrounding_cube(dataset: pd.DataFrame, closed: bool = False,
                                output=None) -> GenericCube:
        output = Target.CONSTANT if output is None else output
        dimensions = {
            column: (min(dataset[column]) - HyperCube.EPSILON * 2, max(dataset[column]) + HyperCube.EPSILON * 2)
            for column in dataset.columns[:-1]
        }
        if closed:
            if output == Target.CONSTANT:
                return ClosedCube(dimensions)
            if output == Target.REGRESSION:
                return ClosedRegressionCube(dimensions)
            return ClosedClassificationCube(dimensions)
        if output == Target.CLASSIFICATION:
            return ClassificationCube(dimensions)
        if output == Target.REGRESSION:
            return RegressionCube(dimensions)
        return HyperCube(dimensions)

    def _create_tuple(self, generator: Random) -> dict:
        return {k: generator.uniform(self.get_first(k), self.get_second(k)) for k in self._dimensions.keys()}

    @staticmethod
    def cube_from_point(point: dict[str, float], output=None) -> GenericCube:
        if output is Target.CLASSIFICATION:
            return ClassificationCube({k: (v, v) for k, v in list(point.items())[:-1]})
        if output is Target.REGRESSION:
            return RegressionCube({k: (v, v) for k, v in list(point.items())[:-1]})
        return HyperCube({k: (v, v) for k, v in list(point.items())[:-1]}, output=list(point.values())[-1])

    def equal(self, hypercubes: Iterable[HyperCube] | HyperCube) -> bool:
        if isinstance(hypercubes, Iterable):
            return any([self.equal(cube) for cube in hypercubes])
        else:
            return all([(abs(dimension.this_dimension[0] - dimension.other_dimension[0]) < HyperCube.EPSILON)
                        & (abs(dimension.this_dimension[1] - dimension.other_dimension[1]) < HyperCube.EPSILON)
                        for dimension in self._zip_dimensions(hypercubes)])

    def expand(self, expansion: Expansion, hypercubes: Iterable[HyperCube]) -> None:
        feature = expansion.feature
        a, b = self[feature]
        self.update_dimension(feature, expansion.boundaries(a, b))
        other_cube = self.overlap(hypercubes)
        if isinstance(other_cube, HyperCube):
            self.update_dimension(feature, (other_cube.get_second(feature), b)
            if expansion.direction == '-' else (a, other_cube.get_first(feature)))
        if isinstance(self.overlap(hypercubes), HyperCube):
            raise Exception('Overlapping not handled')

    def expand_all(self, updates: Iterable[MinUpdate], surrounding: HyperCube, ratio: float = 1.0) -> None:
        for update in updates:
            self._expand_one(update, surrounding, ratio)

    def get_first(self, feature: str) -> float:
        return self[feature][0]

    def get_second(self, feature: str) -> float:
        return self[feature][1]

    def has_volume(self) -> bool:
        return all([dimension[1] - dimension[0] > HyperCube.EPSILON for dimension in self._dimensions.values()])

    def volume(self) -> float:
        return reduce(lambda a, b: a * b, [dimension[1] - dimension[0] for dimension in self._dimensions.values()], 1)

    def diagonal(self) -> float:
        return reduce(
            lambda a, b: a + b, [(dimension[1] - dimension[0]) ** 2 for dimension in self._dimensions.values()], 0
        ) ** 0.5

    def center(self) -> Point:
        return Point(list(self._dimensions.keys()),
                     [(interval[0] + interval[1]) / 2 for interval in self._dimensions.values()])

    def corners(self) -> Iterable[Point]:
        return [
            Point(list(self._dimensions.keys()), values) for values in itertools.product(*self._dimensions.values())
        ]

    def perimeter_samples(self, n: int = 5) -> Iterable[Point]:
        def duplicate(point: Point, feature: str) -> Iterable[Point]:
            new_point_a = point.copy()
            new_point_b = point.copy()
            new_point_a[feature] = self.get_first(feature)
            new_point_b[feature] = self.get_second(feature)
            return [new_point_a, new_point_b]

        def remove_duplicates(points: Iterable[Point]) -> Iterable[Point]:
            new_points = []
            for point in points:
                if point not in new_points:
                    new_points.append(point)
            return new_points

        def split(point: Point, feature: str, n: int):
            points = []
            a, b = self.get_first(feature), self.get_second(feature)
            for value in np.linspace(a, b, n) if n > 1 else [(a + b) / 2]:
                new_point = point.copy()
                new_point[feature] = value
                points.append(new_point)
            return points

        points = []
        for primary in self._dimensions:
            new_points = [Point([], [])]
            for secondary in self._dimensions:
                new_points = np.array([duplicate(point, secondary) if primary != secondary else
                                       split(point, primary, n) for point in new_points]).flatten()
            points = points + list(new_points)
        return remove_duplicates(points)

    def is_adjacent(self, cube: HyperCube) -> str | None:
        adjacent = None
        for (feature, [a1, b1]) in self._dimensions.items():
            if self[feature] == cube[feature]:
                continue
            [a2, b2] = cube[feature]
            if (adjacent is not None) or ((b1 != a2) and (b2 != a1)):
                return None
            adjacent = feature
        return adjacent

    def merge_along_dimension(self, cube: HyperCube, feature: str) -> HyperCube:
        new_cube = self.copy()
        (a1, b1) = self[feature]
        (a2, b2) = cube[feature]
        new_cube.update_dimension(feature, (min(a1, a2), max(b1, b2)))
        return new_cube

    def merge(self, other: HyperCube) -> HyperCube:
        new_cube = self.copy()
        for dimension in self.dimensions.keys():
            new_cube = new_cube.merge_along_dimension(other, dimension)
        return new_cube

    def merge_with_point(self, other: Point) -> HyperCube:
        return self.merge(HyperCube.cube_from_point(other.dimensions))

    # TODO: maybe two different methods are more readable and easier to debug
    def overlap(self, hypercubes: Iterable[HyperCube] | HyperCube) -> HyperCube | bool | None:
        if isinstance(hypercubes, Iterable):
            for hypercube in hypercubes:
                if (self != hypercube) & self.overlap(hypercube):
                    return hypercube
            return None
        elif self is hypercubes:
            return False
        else:
            return all([not ((dimension.other_dimension[0] >= dimension.this_dimension[1]) |
                             (dimension.this_dimension[0] >= dimension.other_dimension[1]))
                        for dimension in self._zip_dimensions(hypercubes)])

    # TODO: maybe two different methods are more readable and easier to debug
    def update_dimension(self, feature: str, lower: float | tuple[float, float], upper: float | None = None) -> None:
        if upper is None:
            self[feature] = lower
        else:
            self.update_dimension(feature, (lower, upper))

    def update(self, dataset: pd.DataFrame, predictor) -> None:
        filtered = self.filter_dataframe(dataset.iloc[:, :-1])
        predictions = predictor.predict(filtered)
        self._output = np.mean(predictions)
        self._diversity = np.std(predictions)
        means = filtered.describe().loc['mean']
        self._barycenter = Point(means.index.values, means.values)

    # TODO: why this is not a property?
    def init_diversity(self, std: float) -> None:
        self._diversity = std


class RegressionCube(HyperCube):
    def __init__(self, dimension: dict[str, tuple] = None):
        super().__init__(dimension=dimension, output=LinearRegression())

    def update(self, dataset: pd.DataFrame, predictor) -> None:
        filtered = self.filter_dataframe(dataset.iloc[:, :-1])
        if len(filtered > 0):
            predictions = predictor.predict(filtered)
            self._output.fit(filtered, predictions)
            self._diversity = (abs(self._output.predict(filtered) - predictions)).mean()
            means = filtered.describe().loc['mean']
            self._barycenter = Point(means.index.values, means.values)

    def copy(self) -> RegressionCube:
        return RegressionCube(self.dimensions.copy())

    def body(self, variables: dict[str, Var], ignore: list[str], unscale=None, normalization=None) -> Iterable[Struct]:
        intercept = self.output.intercept_ if normalization is None else unscale(sum(
            [-self.output.coef_[i] * normalization[name][0] / normalization[name][1] for i, name in
             enumerate(self.dimensions.keys())], self.output.intercept_), list(normalization.keys())[-1])
        coefs = self.output.coef_ if normalization is None else [
            self.output.coef_[i] / normalization[name][1] * normalization[list(normalization.keys())[-1]][1] for
            i, name in enumerate(self.dimensions.keys())
        ]
        return list(super().body(variables, ignore, unscale, normalization)) + [linear_function_creator(
            list(variables.values()), [to_rounded_real(v) for v in coefs], to_rounded_real(intercept)
        )]


class ClassificationCube(HyperCube):
    def __init__(self, dimension: dict[str, tuple] = None, limits: set[Limit] = None, output: str = ""):
        super().__init__(dimension=dimension, limits=limits, output=output)

    def update(self, dataset: pd.DataFrame, predictor) -> None:
        filtered = self.filter_dataframe(dataset.iloc[:, :-1])
        if len(filtered > 0):
            predictions = predictor.predict(filtered)
            self._output = mode(predictions)
            self._diversity = 1 - sum(prediction == self.output for prediction in predictions) / len(filtered)
            means = filtered.describe().loc['mean']
            self._barycenter = Point(means.index.values, means.values)

    def copy(self) -> ClassificationCube:
        return ClassificationCube(self.dimensions.copy(), self._limits.copy(), self._output)


class ClosedCube(HyperCube):
    def __init__(self, dimension: dict[str, tuple] = None):
        super().__init__(dimension=dimension)

    def __contains__(self, point: dict[str, float]) -> bool:
        return all([(self.get_first(k) <= v <= self.get_second(k)) for k, v in point.items()])

    def filter_indices(self, dataset: pd.DataFrame) -> ndarray:
        v = np.array([v for _, v in self._dimensions.items()])
        ds = dataset.to_numpy(copy=True)
        return np.all((v[:, 0] <= ds) & (ds <= v[:, 1]), axis=1)

    def copy(self) -> ClosedCube:
        return ClosedCube(self.dimensions.copy())


class ClosedRegressionCube(ClosedCube, RegressionCube):
    def __init__(self, dimension: dict[str, tuple] = None):
        super().__init__(dimension=dimension)

    def copy(self) -> ClosedRegressionCube:
        return ClosedRegressionCube(self.dimensions.copy())


class ClosedClassificationCube(ClosedCube, ClassificationCube):
    def __init__(self, dimension: dict[str, tuple] = None):
        super().__init__(dimension=dimension)

    def copy(self) -> ClosedClassificationCube:
        return ClosedClassificationCube(self.dimensions.copy())


GenericCube = Union[HyperCube, ClassificationCube, RegressionCube,
                    ClosedCube, ClosedRegressionCube, ClosedClassificationCube]
