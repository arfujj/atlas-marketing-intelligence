"""Bayesian marketing-mix modelling (own PyMC model) and a naive OLS comparator."""

from atlas.mmm.design import Design, national_weekly
from atlas.mmm.model import (
    LiftTest,
    Posterior,
    Variant,
    calibrated_variant,
    dag_variant,
    default_variant,
)

__all__ = ["Design", "LiftTest", "Posterior", "Variant", "calibrated_variant", "dag_variant",
           "default_variant", "national_weekly"]
