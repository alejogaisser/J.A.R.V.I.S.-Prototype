import tempfile
import unittest
from pathlib import Path

from actions.math_engine import math_engine


class MathEngineTests(unittest.TestCase):
    def test_symbolic_calculus_and_equation(self):
        self.assertIn("2*x", math_engine({"action": "derivative", "expression": "x^2"}))
        self.assertIn("x**3/3", math_engine({"action": "integral", "expression": "x^2"}))
        solved = math_engine({"action": "solve", "expression": "x^2 - 4"})
        self.assertIn("-2", solved)
        self.assertIn("2", solved)

    def test_matrix_and_gaussian_steps(self):
        determinant = math_engine({"action": "matrix", "matrix": "[[1,2],[3,4]]", "matrix_operation": "determinant"})
        self.assertIn("-2", determinant)
        gauss = math_engine({"action": "gauss", "matrix": "[[1,2,5],[3,4,11]]"})
        self.assertIn("RREF", gauss)
        self.assertIn("[[1, 0, 1], [0, 1, 2]]", gauss)

    def test_unsafe_identifiers_are_rejected(self):
        result = math_engine({"action": "simplify", "expression": "__import__('os')"})
        self.assertIn("Math error", result)

    def test_plot_is_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plot.png"
            result = math_engine({"action": "plot2d", "expression": "x^2-1", "output_path": str(output), "min": -3, "max": 3})
            self.assertTrue(output.exists(), result)
            self.assertGreater(output.stat().st_size, 1000)
