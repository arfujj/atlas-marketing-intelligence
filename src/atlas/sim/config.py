"""World specification for the simulated business.

Every number here is an ASSUMPTION of a fictional company ("Halden Coffee Works").
None of it is calibrated to, or claims to describe, any real business. The spec is
validated by Pydantic so a malformed world fails loudly before anything is generated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChannelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    annual_spend: float = Field(gt=0, description="USD/year at reference level, national")
    target_roi: float = Field(
        gt=0, description="True first-order incremental revenue per $ over the history window"
    )
    adstock_decay: float = Field(ge=0, lt=1)
    half_sat_ratio: float = Field(
        gt=0, description="Hill K as a multiple of mean adstocked weekly spend per geo"
    )
    hill_slope: float = Field(gt=0)
    first_order_aov: float = Field(gt=0)
    first_order_cm_rate: float = Field(gt=0, lt=1, description="Contribution margin / revenue")
    repeat_revenue_52w: float = Field(
        ge=0, description="Expected repeat revenue per acquired customer in 52 weeks"
    )
    spend_policy: Literal["planned", "demand_driven"]
    flighting: Literal["always_on", "pulsed"] = "always_on"
    seasonal_tilt: float = Field(
        default=0.0, ge=0, description="Exponent on demand seasonality in the spend plan"
    )
    weekly_volatility: float = Field(default=0.15, ge=0)
    demand_lag_weeks: int = Field(default=0, ge=0, le=4)
    launch_week: int = Field(default=0, ge=0, description="History week index of first spend")
    cpm: float = Field(gt=0, description="USD per 1,000 impressions")
    ctr: float = Field(gt=0, lt=1)


class BaselineSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    new_customers_weekly: float = Field(gt=0, description="Organic new customers/week at start")
    annual_growth: float = 0.12
    season_amplitude: float = Field(default=0.18, ge=0)
    season_peak_doy: int = Field(default=350, ge=1, le=366)
    gifting_lift: float = 0.25
    bfcm_lift: float = 0.60
    promos_per_year: int = Field(default=4, ge=0)
    promo_lift: float = 0.20
    promo_discount: float = Field(default=0.15, ge=0, lt=1)
    first_order_aov: float = 62.0
    first_order_cm_rate: float = 0.40
    repeat_revenue_52w: float = 64.0
    repeat_cm_rate: float = 0.46
    repeat_aov: float = 36.0
    repeat_decay_weeks: float = Field(default=18.0, gt=0)
    nb_dispersion: float = Field(default=40.0, gt=0)
    aov_noise_sd: float = Field(default=0.03, ge=0)


class IncidentSpec(BaseModel):
    """An operational or measurement incident. None of them changes true media effects."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["tracking_outage", "cpc_spike", "checkout_incident"]
    start_week: int = Field(ge=0, description="History week index (0 = first history week)")
    n_weeks: int = Field(default=1, ge=1, le=8)
    geo: str | None = Field(default=None, description="Rxx, or None for all regions")
    channel: str | None = Field(default=None, description="Only for cpc_spike")
    magnitude: float = Field(
        description="tracking_outage/checkout_incident: fractional loss (0.55 = -55%); "
        "cpc_spike: fractional billed-spend inflation (0.40 = +40%)")


class WorldConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    company: str = "Halden Coffee Works (fictional)"
    history_start: date = date(2023, 10, 2)  # a Monday
    n_weeks: int = Field(default=156, ge=52)
    burn_in_weeks: int = Field(default=52, ge=52, description="Warms up the repeat base")
    geo_weights: tuple[float, ...] = (0.17, 0.14, 0.12, 0.11, 0.10, 0.09, 0.08, 0.07, 0.07, 0.05)
    geo_share_volatility: float = Field(default=0.15, ge=0)
    baseline: BaselineSpec = BaselineSpec(new_customers_weekly=780.0)
    channels: tuple[ChannelSpec, ...]
    # Site sessions: organic/direct sessions per expected baseline new customer and per
    # repeat order. Paid sessions equal platform clicks.
    organic_sessions_per_baseline_customer: float = Field(default=80.0, gt=0)
    sessions_per_repeat_order: float = Field(default=10.0, ge=0)
    # Customer journeys (attribution input).
    path_extra_touches_mean: float = Field(default=1.6, ge=0)
    harvest_last_touch_prob: float = Field(default=0.6, ge=0, le=1)
    nonconverting_paths_per_converter: float = Field(default=2.0, ge=0)
    nonconverting_weight: float = Field(
        default=25.0, gt=0, description="Each sampled non-converting path stands for this many")
    # Incidents (operational / measurement; never change true media effects).
    incident_mode: Literal["scheduled", "random", "none"] = "scheduled"
    incidents: tuple[IncidentSpec, ...] = ()
    n_random_incidents: int = Field(default=6, ge=0)
    random_incident_window_weeks: int = Field(default=52, ge=4)

    @model_validator(mode="after")
    def _check(self) -> WorldConfig:
        if self.history_start.weekday() != 0:
            raise ValueError("history_start must be a Monday")
        if abs(sum(self.geo_weights) - 1.0) > 1e-9:
            raise ValueError("geo_weights must sum to 1")
        names = [c.name for c in self.channels]
        if len(set(names)) != len(names):
            raise ValueError("channel names must be unique")
        for c in self.channels:
            if c.launch_week >= self.n_weeks:
                raise ValueError(f"{c.name}: launch_week beyond history")
        for inc in self.incidents:
            if inc.start_week + inc.n_weeks > self.n_weeks:
                raise ValueError(f"incident {inc.kind} extends beyond history")
            if inc.kind == "cpc_spike" and inc.channel not in names:
                raise ValueError("cpc_spike needs a valid channel")
        return self

    @property
    def n_geos(self) -> int:
        return len(self.geo_weights)

    def fingerprint(self) -> str:
        """Stable hash of the full spec, recorded in every output manifest."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]


SCHEDULED_INCIDENTS = (
    # (a) one-week purchase-tag outage in one region: recorded orders/revenue -55%.
    IncidentSpec(kind="tracking_outage", start_week=140, n_weeks=1, geo="R03", magnitude=0.55),
    # (b) four-week non-brand search CPC spike: billed spend +40%, same clicks, same effect.
    IncidentSpec(kind="cpc_spike", start_week=146, n_weeks=4, channel="search_nonbrand",
                 magnitude=0.40),
    # (c) one-week site-wide checkout failure in the final history week: real loss of 20%.
    IncidentSpec(kind="checkout_incident", start_week=155, n_weeks=1, magnitude=0.20),
)


def default_world() -> WorldConfig:
    """The pre-registered Halden world. See docs/data-generating-process.md."""
    ch = ChannelSpec
    return WorldConfig(
        incidents=SCHEDULED_INCIDENTS,
        channels=(
            ch(name="search_nonbrand", label="Search · Non-brand", annual_spend=500_000,
               target_roi=2.0, adstock_decay=0.15, half_sat_ratio=1.1, hill_slope=1.2,
               first_order_aov=74, first_order_cm_rate=0.36, repeat_revenue_52w=58,
               spend_policy="planned", seasonal_tilt=0.7, weekly_volatility=0.15,
               cpm=38, ctr=0.045),
            ch(name="search_brand", label="Search · Brand", annual_spend=190_000,
               target_roi=0.5, adstock_decay=0.05, half_sat_ratio=0.5, hill_slope=1.0,
               first_order_aov=66, first_order_cm_rate=0.40, repeat_revenue_52w=72,
               spend_policy="demand_driven", weekly_volatility=0.08,
               cpm=30, ctr=0.12),
            ch(name="meta_prospecting", label="Meta · Prospecting", annual_spend=530_000,
               target_roi=2.2, adstock_decay=0.35, half_sat_ratio=1.0, hill_slope=1.3,
               first_order_aov=56, first_order_cm_rate=0.40, repeat_revenue_52w=52,
               spend_policy="planned", seasonal_tilt=0.9, weekly_volatility=0.20,
               cpm=11, ctr=0.011),
            ch(name="meta_retargeting", label="Meta · Retargeting", annual_spend=190_000,
               target_roi=0.7, adstock_decay=0.20, half_sat_ratio=0.6, hill_slope=1.0,
               first_order_aov=60, first_order_cm_rate=0.40, repeat_revenue_52w=60,
               spend_policy="demand_driven", demand_lag_weeks=1, weekly_volatility=0.10,
               cpm=16, ctr=0.018),
            ch(name="tiktok", label="TikTok", annual_spend=270_000,
               target_roi=2.8, adstock_decay=0.30, half_sat_ratio=1.8, hill_slope=1.4,
               first_order_aov=44, first_order_cm_rate=0.42, repeat_revenue_52w=30,
               spend_policy="planned", seasonal_tilt=0.5, weekly_volatility=0.30,
               launch_week=40, cpm=7, ctr=0.008),
            ch(name="youtube", label="YouTube", annual_spend=230_000,
               target_roi=1.4, adstock_decay=0.60, half_sat_ratio=1.2, hill_slope=1.5,
               first_order_aov=92, first_order_cm_rate=0.32, repeat_revenue_52w=50,
               spend_policy="planned", flighting="pulsed", seasonal_tilt=0.4,
               weekly_volatility=0.15, cpm=9, ctr=0.004),
        )
    )


# ----------------------------------------------------------------------------------------
# Randomised worlds for multi-world evaluation.

WORLD_REGIMES = ("standard", "collinear", "weak_signal", "long_carryover")
"""standard: parameters drawn from the documented ranges.
collinear: all planned channels follow the same strongly seasonal plan with little
    week-to-week independent variation (MMM should struggle to separate them).
weak_signal: low true ROIs and lower spend, so media effects are close to the noise.
long_carryover: high adstock decays (up to 0.8) on the planned channels."""


def sample_world(seed: int, regime: str | None = None) -> tuple[WorldConfig, dict]:
    """Draw a parameter-randomised world around the Halden template.

    Ranges are documented in docs/data-generating-process.md §7. Returns the config and a
    metadata dict (regime and the drawn values) that is stored with every evaluation run.
    Random incidents are injected so the anomaly detector can be evaluated across worlds.
    """
    import numpy as np  # local import keeps the module light

    rng = np.random.default_rng([seed, 9001])
    drawn = str(rng.choice(WORLD_REGIMES, p=[0.55, 0.15, 0.15, 0.15]))
    regime = regime or drawn
    if regime not in WORLD_REGIMES:
        raise ValueError(f"unknown regime {regime}")
    base = default_world()
    chans = []
    shared_tilt = rng.uniform(1.0, 1.4)
    for c in base.channels:
        harvest = c.spend_policy == "demand_driven"
        lo, hi = (0.2, 1.2) if harvest else (0.6, 3.5)
        if regime == "weak_signal":
            lo, hi = lo * 0.5, hi * 0.5
        roi = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
        decay_hi = 0.8 if (regime == "long_carryover" and not harvest) else 0.6
        upd = dict(
            target_roi=roi,
            adstock_decay=float(rng.uniform(0.0, 0.3 if harvest else decay_hi)),
            half_sat_ratio=float(rng.uniform(0.5, 2.5)),
            hill_slope=float(rng.uniform(0.8, 2.0)),
            annual_spend=float(c.annual_spend * rng.uniform(0.6, 1.5)
                               * (0.6 if regime == "weak_signal" else 1.0)),
            first_order_aov=float(c.first_order_aov * rng.uniform(0.8, 1.2)),
            first_order_cm_rate=float(np.clip(c.first_order_cm_rate * rng.uniform(0.85, 1.15),
                                              0.15, 0.6)),
            repeat_revenue_52w=float(c.repeat_revenue_52w * rng.uniform(0.7, 1.3)),
        )
        if not harvest:
            if regime == "collinear":
                upd.update(seasonal_tilt=float(shared_tilt * rng.uniform(0.95, 1.05)),
                           weekly_volatility=float(rng.uniform(0.02, 0.06)))
            else:
                upd.update(seasonal_tilt=float(rng.uniform(0.0, 1.2)),
                           weekly_volatility=float(rng.uniform(0.08, 0.35)))
        if c.name == "tiktok":
            upd["launch_week"] = int(rng.integers(0, 81))
        chans.append(c.model_copy(update=upd))
    cfg = base.model_copy(update=dict(
        channels=tuple(chans),
        baseline=base.baseline.model_copy(
            update={"new_customers_weekly": float(rng.uniform(600, 1000))}),
        geo_share_volatility=0.03 if regime == "collinear" else float(rng.uniform(0.08, 0.25)),
        incident_mode="random", incidents=(),
    ))
    cfg = WorldConfig.model_validate(cfg.model_dump())  # re-validate the drawn world
    meta = {"world_seed": seed, "regime": regime,
            "channels": {c.name: {k: getattr(c, k) for k in (
                "target_roi", "adstock_decay", "half_sat_ratio", "hill_slope",
                "annual_spend", "seasonal_tilt", "weekly_volatility", "launch_week")}
                for c in cfg.channels}}
    return cfg, meta
