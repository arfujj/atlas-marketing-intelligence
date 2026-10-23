"""Media transforms used by the *true* data-generating process.

These are deliberately simple, closed-form functions. The MMM fitted later may use
different parameterisations (e.g. normalised adstock, logistic saturation); comparisons
against truth are therefore made in contribution / ROI space, never on raw parameters.
"""

from __future__ import annotations

import numpy as np


def geometric_adstock(x: np.ndarray, decay: float) -> np.ndarray:
    """Unnormalised geometric carryover along the last axis.

    a[t] = x[t] + decay * a[t-1]. An impulse of 1 at t=0 yields decay**k at t=k, so the
    total long-run effect of one dollar is 1 / (1 - decay) adstocked dollars.
    """
    if not 0.0 <= decay < 1.0:
        raise ValueError(f"decay must be in [0, 1), got {decay}")
    x = np.asarray(x, dtype=float)
    out = np.empty_like(x)
    carry = np.zeros(x.shape[:-1])
    for t in range(x.shape[-1]):
        carry = x[..., t] + decay * carry
        out[..., t] = carry
    return out


def hill(x: np.ndarray, half_saturation: np.ndarray | float, slope: float) -> np.ndarray:
    """Hill saturation in [0, 1): x^s / (x^s + K^s). Equals 0.5 at x == K."""
    if slope <= 0:
        raise ValueError(f"slope must be positive, got {slope}")
    x = np.maximum(np.asarray(x, dtype=float), 0.0)
    k = np.asarray(half_saturation, dtype=float)
    if np.any(k <= 0):
        raise ValueError("half_saturation must be positive")
    xs = x**slope
    return xs / (xs + k**slope)
