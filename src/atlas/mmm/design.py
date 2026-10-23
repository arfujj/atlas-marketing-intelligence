"""National weekly design matrix for the MMM, built only from OBSERVED tables.

Target: national weekly first-order (new-customer) revenue. Media: billed spend per channel.
Controls: linear trend, yearly Fourier terms (K=3), promotion / BFCM / gifting-week flags.
Nothing from truth/ is used here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

L_MAX = 8
FOURIER_K = 3
CONTROL_FLAGS = ("promo_week", "bfcm_week", "gifting_week")


@dataclass(frozen=True)
class Design:
    weeks: pd.DatetimeIndex
    channels: tuple[str, ...]
    spend: np.ndarray  # [T, C] billed USD per week, national
    y: np.ndarray  # [T] national first-order revenue, USD
    controls: np.ndarray  # [T, K] trend + Fourier + flags
    control_names: tuple[str, ...]
    x_scale: np.ndarray  # [C] mean weekly spend over weeks with spend > 0
    y_scale: float  # mean of y over the training weeks

    @property
    def x(self) -> np.ndarray:
        return self.spend / self.x_scale

    def lagged(self) -> np.ndarray:
        """[C, T, L_MAX] scaled spend lags: x[c, t-l]. Pre-history weeks are filled with the
        first observed week (steady-state assumption); channels with no spend yet stay 0."""
        x = self.x
        out = np.zeros((x.shape[1], x.shape[0], L_MAX))
        for lag in range(L_MAX):
            shifted = np.roll(x, lag, axis=0)
            shifted[:lag] = x[0]
            out[:, :, lag] = shifted.T
        return out


def fourier(weeks: pd.DatetimeIndex, k: int = FOURIER_K) -> tuple[np.ndarray, list[str]]:
    doy = weeks.dayofyear.to_numpy()
    cols, names = [], []
    for i in range(1, k + 1):
        ang = 2 * np.pi * i * doy / 365.25
        cols += [np.sin(ang), np.cos(ang)]
        names += [f"sin{i}", f"cos{i}"]
    return np.column_stack(cols), names


def national_weekly(media: pd.DataFrame, outcomes: pd.DataFrame, calendar: pd.DataFrame,
                    channels: tuple[str, ...] | None = None,
                    n_train: int | None = None) -> Design:
    m = media.assign(week_start=pd.to_datetime(media.week_start))
    o = outcomes.assign(week_start=pd.to_datetime(outcomes.week_start))
    cal = calendar.assign(week_start=pd.to_datetime(calendar.week_start)).set_index("week_start")
    sp = m.pivot_table(index="week_start", columns="channel", values="spend", aggfunc="sum")
    if channels is None:
        channels = tuple(sp.columns)
    sp = sp[list(channels)].sort_index()
    y = o.groupby("week_start").first_order_revenue.sum().reindex(sp.index).to_numpy()
    weeks = pd.DatetimeIndex(sp.index)
    t = np.arange(len(weeks)) / (len(weeks) - 1)
    f, fn = fourier(weeks)
    flags = cal.reindex(weeks)[list(CONTROL_FLAGS)].to_numpy(dtype=float)
    controls = np.column_stack([t, f, flags])
    names = ("trend", *fn, *CONTROL_FLAGS)
    spend = sp.to_numpy(dtype=float)
    x_scale = np.array([spend[spend[:, c] > 0, c].mean() for c in range(spend.shape[1])])
    n_train = n_train or len(weeks)
    return Design(weeks=weeks, channels=tuple(channels), spend=spend, y=y, controls=controls,
                  control_names=names, x_scale=x_scale, y_scale=float(y[:n_train].mean()))


def adstock_weights(alpha: np.ndarray, l_max: int = L_MAX) -> np.ndarray:
    """Normalised geometric weights, [..., L]: alpha**l / sum(alpha**l)."""
    a = np.asarray(alpha)[..., None]
    w = a ** np.arange(l_max)
    return w / w.sum(axis=-1, keepdims=True)


def hill(a: np.ndarray, kappa: np.ndarray, slope: np.ndarray) -> np.ndarray:
    a = np.maximum(a, 0.0)
    return a**slope / (a**slope + kappa**slope)
