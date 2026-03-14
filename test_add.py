import math

import pytest

from math_utils import add


def test_positive_integers():
    assert add(1, 2) == 3


def test_negative_numbers():
    assert add(-1, -2) == -3


def test_mixed_sign():
    assert add(-1, 2) == 1


def test_zeros():
    assert add(0, 0) == 0


def test_floats():
    assert add(0.1, 0.2) == pytest.approx(0.3)


def test_large_floats_overflow_to_inf():
    assert add(1e308, 1e308) == float("inf")


def test_nan_propagation():
    assert math.isnan(add(float("nan"), 1))


def test_inf():
    assert add(float("inf"), 1) == float("inf")


def test_int_float_mix():
    assert add(1, 2.5) == 3.5


def test_incompatible_types_raise_type_error():
    with pytest.raises(TypeError, match="add\\(\\) arguments must support addition"):
        add(1, object())
