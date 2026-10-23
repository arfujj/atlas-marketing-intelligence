import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from atlas.sim.transforms import geometric_adstock, hill


def test_adstock_impulse_response():
    x = np.zeros(10)
    x[0] = 1.0
    np.testing.assert_allclose(geometric_adstock(x, 0.5), 0.5 ** np.arange(10))


def test_adstock_zero_decay_is_identity():
    x = np.random.default_rng(0).random((3, 20))
    np.testing.assert_allclose(geometric_adstock(x, 0.0), x)


@given(st.floats(0.0, 0.95))
def test_adstock_long_run_mass(decay):
    x = np.zeros(2000)
    x[0] = 1.0
    assert geometric_adstock(x, decay).sum() == pytest.approx(1 / (1 - decay), rel=1e-6)


def test_adstock_rejects_invalid_decay():
    with pytest.raises(ValueError):
        geometric_adstock(np.ones(3), 1.0)


@given(st.floats(0.1, 1e6), st.floats(0.3, 3.0))
def test_hill_half_saturation_point(k, s):
    assert hill(np.array([k]), k, s)[0] == pytest.approx(0.5)


def test_hill_monotone_and_bounded():
    x = np.linspace(0, 1e5, 500)
    y = hill(x, 1e4, 1.4)
    assert np.all(np.diff(y) >= 0)
    assert y[0] == 0 and y.max() < 1
