"""Metric layer: YAML definitions compiled to SQL over the serving DuckDB.

Each metric has one definition (formula, grain, evidence type, caveats). Ratios are always
computed as a ratio of sums over the filtered rows. A filter or grouping that a metric's
model cannot support (e.g. MER by channel) raises `MetricNotApplicable` instead of
returning a misleading number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import duckdb
import pandas as pd
import yaml

DEFINITIONS = Path(__file__).parent / "definitions"
ALLOWED_DIMS = ("week_start", "geo", "channel")
EVIDENCE_TYPES = ("Observed", "Attributed", "Modeled", "Experimental", "Simulated", "Assumption")


class MetricNotApplicable(ValueError):
    """The requested filter/grouping is not defined for this metric."""


@dataclass(frozen=True)
class MetricDef:
    name: str
    label: str
    type: str
    format: str
    evidence_type: str
    definition: str
    caveats: tuple[str, ...] = ()
    model: str | None = None
    expression: str | None = None
    dimensions: tuple[str, ...] = ()
    grain: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    window_weeks: int | None = None
    numerator_expression: str | None = None
    denominator_expression: str | None = None


@dataclass(frozen=True)
class Filters:
    start: date | None = None
    end: date | None = None
    geos: tuple[str, ...] | None = None
    channels: tuple[str, ...] | None = None

    def date_range(self) -> tuple[str | None, str | None]:
        return (str(self.start) if self.start else None, str(self.end) if self.end else None)


@dataclass
class MetricResult:
    metric: MetricDef
    data: pd.DataFrame  # group_by columns + value (+ numerator/denominator for ratios)
    source_tables: list[str] = field(default_factory=list)


@cache
def load_metrics(workspace: str = "halden") -> dict[str, MetricDef]:
    spec = yaml.safe_load((DEFINITIONS / f"{workspace}.yml").read_text())
    out: dict[str, MetricDef] = {}
    for m in spec["metrics"]:
        m = dict(m)
        m["caveats"] = tuple(m.get("caveats") or ())
        m["dimensions"] = tuple(m.get("dimensions") or ())
        md = MetricDef(**m)
        if md.evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"{md.name}: unknown evidence type {md.evidence_type}")
        out[md.name] = md
    for md in out.values():
        if md.type == "ratio":
            for ref in (md.numerator, md.denominator):
                if ref not in out:
                    raise ValueError(f"{md.name}: unknown component metric {ref}")
    return out


def dimensions_of(m: MetricDef, metrics: dict[str, MetricDef]) -> set[str]:
    if m.type == "ratio":
        return dimensions_of(metrics[m.numerator], metrics) & dimensions_of(
            metrics[m.denominator], metrics)
    return set(m.dimensions)


def _where(m: MetricDef, f: Filters) -> tuple[str, list]:
    clauses, params = ["1=1"], []
    if f.start:
        clauses.append("week_start >= ?")
        params.append(f.start)
    if f.end:
        clauses.append("week_start <= ?")
        params.append(f.end)
    if f.geos:
        clauses.append(f"geo in ({', '.join('?' * len(f.geos))})")
        params.extend(f.geos)
    if f.channels:
        if "channel" not in m.dimensions:
            raise MetricNotApplicable(f"{m.name} is not defined by channel")
        clauses.append(f"channel in ({', '.join('?' * len(f.channels))})")
        params.extend(f.channels)
    return " and ".join(clauses), params


def _simple(con: duckdb.DuckDBPyConnection, m: MetricDef, f: Filters,
            group_by: tuple[str, ...]) -> pd.DataFrame:
    for d in group_by:
        if d not in ALLOWED_DIMS:
            raise ValueError(f"unknown dimension {d}")
        if d not in m.dimensions:
            raise MetricNotApplicable(f"{m.name} cannot be grouped by {d}")
    where, params = _where(m, f)
    cols = ", ".join(group_by)
    sel = f"{cols}, " if group_by else ""
    grp = f" group by {cols} order by {cols}" if group_by else ""
    sql = f"select {sel}{m.expression} as value from {m.model} where {where}{grp}"
    return con.execute(sql, params).df()


def query_metric(con: duckdb.DuckDBPyConnection, name: str, filters: Filters | None = None,
                 group_by: tuple[str, ...] = (), workspace: str = "halden") -> MetricResult:
    metrics = load_metrics(workspace)
    if name not in metrics:
        raise KeyError(f"unknown metric {name}")
    m = metrics[name]
    f = filters or Filters()
    group_by = tuple(group_by)
    if m.type == "simple":
        return MetricResult(m, _simple(con, m, f, group_by), [m.model])
    if m.type == "ratio":
        num = query_metric(con, m.numerator, f, group_by, workspace)
        den = query_metric(con, m.denominator, f, group_by, workspace)
        n = num.data.rename(columns={"value": "numerator"})
        d = den.data.rename(columns={"value": "denominator"})
        df = n.merge(d, on=list(group_by), how="outer") if group_by else pd.concat([n, d], axis=1)
        den_v = df["denominator"].astype(float)
        df["value"] = df["numerator"].astype(float) / den_v.where(den_v != 0)
        tables = sorted(set(num.source_tables) | set(den.source_tables))
        return MetricResult(m, df, tables)
    if m.type == "trailing":
        if set(group_by) - {"geo"}:
            raise MetricNotApplicable(f"{m.name} can only be grouped by geo")
        end = f.end or con.execute(f"select max(week_start) from {m.model}").fetchone()[0]
        start = end - timedelta(weeks=m.window_weeks - 1)
        f2 = Filters(start=start, end=end, geos=f.geos, channels=f.channels)
        where, params = _where(m, f2)
        cols = ", ".join(group_by)
        sel = f"{cols}, " if group_by else ""
        grp = f" group by {cols} order by {cols}" if group_by else ""
        sql = (f"select {sel}{m.numerator_expression} as numerator, "
               f"{m.denominator_expression} as denominator from {m.model} where {where}{grp}")
        df = con.execute(sql, params).df()
        df["value"] = df.numerator / df.denominator.where(df.denominator != 0)
        df.attrs["window"] = (str(start), str(end))
        return MetricResult(m, df, [m.model])
    raise ValueError(f"unknown metric type {m.type}")


def metric_catalog(workspace: str = "halden") -> list[dict]:
    metrics = load_metrics(workspace)
    return [{
        "name": m.name, "label": m.label, "type": m.type, "format": m.format,
        "evidence_type": m.evidence_type, "definition": m.definition.strip(),
        "caveats": list(m.caveats), "dimensions": sorted(dimensions_of(m, metrics)),
        "formula": (m.expression if m.type == "simple" else
                    f"{m.numerator} / {m.denominator}" if m.type == "ratio" else
                    f"{m.numerator_expression} / {m.denominator_expression} "
                    f"(trailing {m.window_weeks} weeks)"),
        "source_model": m.model,
    } for m in metrics.values()]
