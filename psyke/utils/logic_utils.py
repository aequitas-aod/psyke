import pandas as pd
from tuprolog.core import *
from psyke.schema.value import *
from psyke.schema.value import Constant
from psyke.schema.discrete_feature import DiscreteFeature


def create_functor(constraint: Value, positive: bool) -> str:
    if isinstance(constraint, LessThan):
        return '=<' if positive else '>'
    if isinstance(constraint, GreaterThan):
        return '>' if positive else '=<'
    if isinstance(constraint, Between):
        return 'in' if positive else 'not_in'
    if isinstance(constraint, Constant):
        return '=' if positive else '\\='


def create_term(v: Var, constraint: Value, positive: bool = True) -> Struct:
    if v is None:
        raise Exception('IllegalArgumentException: None variable')
    functor = create_functor(constraint, positive)
    if isinstance(constraint, LessThan):
        return struct(functor, v, real(round(constraint.value, 2)))
    if isinstance(constraint, GreaterThan):
        return struct(functor, v, real(round(constraint.value, 2)))
    if isinstance(constraint, Between):
        return struct(functor, v, real(round(constraint.lower, 2)), real(round(constraint.upper, 2)))
    if isinstance(constraint, Constant):
        return struct(functor, v, atom(str(Constant(constraint).value)))


def create_variable_list(feature: list[DiscreteFeature], dataset: pd.DataFrame = None) -> dict[str, Var]:
    values = {name: var(name) for name, _ in feature} if len(feature) > 0 else\
        {name: var(name) for name in dataset.columns[:-1]}
    return values


def create_head(functor: str, variables: list[var], output) -> Struct:
    if isinstance(output, str):
        variables.append(atom(output))
        return struct(functor, variables)
    else:
        value = round(output, 2) if isinstance(output, float) else output
        variables.append(numeric(value))
        return struct(functor, variables)
