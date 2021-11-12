from parameterized import parameterized_class
from tuprolog.core import real, var, struct
from tuprolog.solve.prolog import prolog_solver
from tuprolog.theory.parsing import parse_theory
from psyke.predictor import Predictor
from test.psyke import get_extractor, get_in_rule, get_precision
from test.resources import CLASSPATH
from tuprolog.theory import Theory
import ast
import csv
import numpy as np
import pandas as pd
import unittest

TEST_FILE = 'iter_test_conf.csv'
RESOURCE_DIR = str(CLASSPATH) + '/'


def _initialize(file: str) -> list[dict[str:Theory]]:
    result = []
    with open(file) as f:
        rows = csv.DictReader(f, delimiter=';', quotechar='"')
        for row in rows:
            params = dict() if row['extractor_params'] == '' else ast.literal_eval(row['extractor_params'])
            params['predictor'] = Predictor.load_from_onnx(RESOURCE_DIR + row['predictor'])
            extractor = get_extractor(row['extractor_type'], params)
            theory = extractor.extract(pd.read_csv(RESOURCE_DIR + row['training_set']))
            result.append({
                'extractor': extractor,
                'extracted_theory': theory,
                'test_set': pd.read_csv(RESOURCE_DIR + row['test_set']),
                'expected_theory': parse_theory(row['theory'] + '.')
            })
    return result


def _data_to_struct(data: pd.Series):
    head = data.keys()[-1]
    terms = [real(item) for item in data.values[:-1]]
    terms.append(var('X'))
    return struct(head, terms)


@parameterized_class(_initialize(RESOURCE_DIR + TEST_FILE))
class TestIter(unittest.TestCase):

    def test_extract(self):
        print(self.expected_theory)
        print(self.extracted_theory)
        self.assertTrue(self.expected_theory.equals(self.extracted_theory, False))

    def test_predict(self):
        predictions = np.array(self.extractor.predict(self.test_set.iloc[:, :-1]))
        solver = prolog_solver(static_kb=self.extracted_theory.assertZ(get_in_rule()))
        substitutions = [solver.solveOnce(_data_to_struct(data)) for _, data in self.test_set.iterrows()]
        index = self.test_set.shape[1]-1
        expected = np.array([query.solved_query.get_arg_at(index).decimal_value.toDouble() for query in substitutions])
        '''
        ITER is not exhaustive so all entry's predictions that are not inside an hypercube are nan.
        All nan value are substituted with the expected one.
        '''
        predictions[np.isnan(predictions)] = expected[np.isnan(predictions)]
        results = abs(predictions - expected) <= get_precision()
        print(sum(results)/len(results))
        self.assertTrue(all(results))


if __name__ == '__main__':
    unittest.main()
