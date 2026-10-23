"""Rule-based and Markov attribution over customer journeys.

EVIDENCE TYPE: Attributed. Every output of this module is *credit allocation* over observed
touch paths. None of it is a causal effect: a channel can collect credit for conversions that
would have happened without it (brand search and retargeting do exactly that in the Halden
world). The Evidence page grades these numbers against the simulator's truth to show how far
credit allocation is from incrementality.

Input: journeys with columns `path` ("a>b>c"), `converted`, `weight` (sampling weight; the
simulator samples non-converting paths) and `first_order_revenue`.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

METHODS = ("last_click", "first_click", "linear", "position_based", "markov")
METHOD_LABELS = {
    "last_click": "Last click",
    "first_click": "First click",
    "linear": "Linear",
    "position_based": "Position-based 40/20/40",
    "markov": "Markov removal effect",
}
START, CONV, NULL = "(start)", "(conversion)", "(null)"


def _aggregate(journeys: pd.DataFrame) -> pd.DataFrame:
    """Collapse to unique (path, converted) with summed weight and revenue."""
    j = journeys[["path", "converted", "weight", "first_order_revenue"]]
    return (j.groupby(["path", "converted"], as_index=False, sort=False)
            .agg(weight=("weight", "sum"), revenue=("first_order_revenue", "sum")))


def _position_weights(n: int, scheme: str) -> np.ndarray:
    if scheme == "last_click":
        w = np.zeros(n)
        w[-1] = 1.0
    elif scheme == "first_click":
        w = np.zeros(n)
        w[0] = 1.0
    elif scheme == "linear":
        w = np.full(n, 1.0 / n)
    elif scheme == "position_based":
        if n == 1:
            w = np.ones(1)
        elif n == 2:
            w = np.array([0.5, 0.5])
        else:
            w = np.full(n, 0.2 / (n - 2))
            w[0] = w[-1] = 0.4
    else:
        raise ValueError(scheme)
    return w


def rule_based(journeys: pd.DataFrame, scheme: str) -> pd.DataFrame:
    """Conversions and revenue credited to each touch channel under a positional rule."""
    agg = _aggregate(journeys)
    conv = agg[agg.converted]
    credit_n: dict[str, float] = defaultdict(float)
    credit_r: dict[str, float] = defaultdict(float)
    for path, wt, rev in zip(conv.path, conv.weight, conv.revenue, strict=True):
        touches = path.split(">")
        pw = _position_weights(len(touches), scheme)
        for ch, p in zip(touches, pw, strict=True):
            credit_n[ch] += wt * p
            credit_r[ch] += rev * p
    return pd.DataFrame({"channel": list(credit_n), "conversions": list(credit_n.values()),
                         "revenue": [credit_r[c] for c in credit_n]})


def _transition_matrix(agg: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    states: dict[str, int] = {START: 0}
    counts: dict[tuple[int, int], float] = defaultdict(float)

    def sid(s: str) -> int:
        if s not in states:
            states[s] = len(states)
        return states[s]

    for path, conv, wt in zip(agg.path, agg.converted, agg.weight, strict=True):
        seq = [START, *path.split(">"), CONV if conv else NULL]
        ids = [sid(s) for s in seq]
        for a, b in zip(ids[:-1], ids[1:], strict=False):
            counts[(a, b)] += wt
    sid(CONV)
    sid(NULL)
    names = list(states)
    m = np.zeros((len(names), len(names)))
    for (a, b), v in counts.items():
        m[a, b] += v
    m[states[CONV], states[CONV]] = 1.0
    m[states[NULL], states[NULL]] = 1.0
    m /= m.sum(axis=1, keepdims=True)
    return names, m


def _p_conversion(names: list[str], m: np.ndarray, removed: str | None = None) -> float:
    """Absorption probability into (conversion) from (start); a removed state sends to (null)."""
    p = m.copy()
    idx = {s: i for i, s in enumerate(names)}
    c, n = idx[CONV], idx[NULL]
    if removed is not None:
        r = idx[removed]
        p[:, n] += p[:, r]
        p[:, r] = 0.0
        p[r, :] = 0.0
        p[r, n] = 1.0
    transient = [i for i in range(len(names)) if i not in (c, n)]
    q = p[np.ix_(transient, transient)]
    b = p[transient, c]
    x = np.linalg.solve(np.eye(len(transient)) - q, b)
    return float(x[transient.index(idx[START])])


def markov(journeys: pd.DataFrame) -> pd.DataFrame:
    """First-order Markov removal-effect attribution (weighted non-converting paths included).

    Removal effect of channel c = 1 − P(conv | c removed) / P(conv). Total conversions and
    revenue are split in proportion to the removal effects.
    """
    agg = _aggregate(journeys)
    names, m = _transition_matrix(agg)
    base = _p_conversion(names, m)
    chans = [s for s in names if s not in (START, CONV, NULL)]
    effect = np.array([1.0 - _p_conversion(names, m, c) / base for c in chans])
    share = effect / effect.sum()
    conv = agg[agg.converted]
    total_n, total_r = float(conv.weight.sum()), float(conv.revenue.sum())
    return pd.DataFrame({"channel": chans, "conversions": share * total_n,
                         "revenue": share * total_r, "removal_effect": effect})


def attribute(journeys: pd.DataFrame, method: str) -> pd.DataFrame:
    if method not in METHODS:
        raise ValueError(f"unknown method {method}")
    out = markov(journeys) if method == "markov" else rule_based(journeys, method)
    out.insert(0, "method", method)
    return out.sort_values("channel").reset_index(drop=True)


def attribution_table(journeys: pd.DataFrame, media: pd.DataFrame,
                      methods: tuple[str, ...] = METHODS) -> pd.DataFrame:
    """All methods side by side with attributed ROAS = credited first-order revenue / billed spend.

    `media` needs `channel` and `spend` over the same window as the journeys.
    """
    spend = media.groupby("channel").spend.sum()
    parts = [attribute(journeys, m) for m in methods]
    df = pd.concat(parts, ignore_index=True)
    df["spend"] = df.channel.map(spend)
    df["roas"] = df.revenue / df.spend
    df["evidence_type"] = "Attributed"
    return df
