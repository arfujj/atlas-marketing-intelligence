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
        return self

    @property
    def n_geos(self) -> int:
        return len(self.geo_weights)

    def fingerprint(self) -> str:
        """Stable hash of the full spec, recorded in every output manifest."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]


def default_world() -> WorldConfig:
    """The pre-registered Halden world. See docs/data-generating-process.md."""
    ch = ChannelSpec
    return WorldConfig(
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
