import unittest
from clamp import clamp

class ClampTests(unittest.TestCase):
    def check(self, value, lower, upper, expected):
        result = clamp(value, lower, upper)
        self.assertIs(type(result), int)
        self.assertEqual(result, expected)
    def test_above_upper(self): self.check(15, 0, 10, 10)
    def test_below_lower(self): self.check(-5, 0, 10, 0)
    def test_within_bounds(self): self.check(5, 0, 10, 5)
    def test_exact_lower(self): self.check(0, 0, 10, 0)
    def test_exact_upper(self): self.check(10, 0, 10, 10)
    def test_equal_bounds(self): self.check(7, 4, 4, 4)
    def test_negative_interval(self): self.check(-3, -10, -5, -5)
    def test_large_bounded_input(self): self.check(1000, -100, 100, 100)
