"""ATLAS serving API: `uvicorn atlas.api.app:app` (or `make api`).

Read-only. Every number comes either from the metric layer over the serving DuckDB or from a
stored model run under model_runs/; nothing is computed from raw tables at request time except
the optimizer, which re-solves over stored posterior draws. Every response carries a
`provenance` block: evidence type plus the run id or source tables it came from.

The three workspaces are never joined: each endpoint belongs to exactly one of them.
"""

import json
import os
from datetime import date
from functools import cache
from pathlib import Path
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from atlas.analyst import SUGGESTIONS
from atlas.analyst import answer as analyst_answer
from atlas.metrics import Filters, MetricNotApplicable, metric_catalog, query_metric
from atlas.optimizer import OBJECTIVES, Constraints, Economics, optimize
from atlas.runs import RUNS_DIR, clean, latest_run, read_manifest

ROOT = Path(__file__).resolve().parents[3]

WORKSPACES = [
    {"id": "halden", "name": "Halden Coffee Works", "evidence_type": "Simulated",
     "description": "Fictional company with known causal truth; used for decisions and to "
                    "grade measurement methods."},
    {"id": "ga4", "name": "Google Merchandise Store", "evidence_type": "Observed",
     "description": "GA4 public obfuscated sample, 2020-11-01 to 2021-01-31."},
    {"id": "criteo", "name": "Criteo Incrementality Tests", "evidence_type": "Experimental",
     "description": "Criteo Uplift v2.1 randomized test, ~14M users (aggregates only)."},
]

GA4_MARTS = {"daily": "mart_ga4_daily", "funnel": "mart_ga4_funnel",
             "category": "mart_ga4_category_daily", "cohorts": "mart_ga4_cohorts",
             "rfm": "mart_ga4_rfm", "data_quality": "mart_ga4_data_quality"}


class Settings:
    def __init__(self, db_path: Path | None = None, runs_dir: Path | None = None):
        self.db_path = Path(db_path or os.environ.get(
            "ATLAS_DUCKDB", ROOT / "data/serving/atlas.duckdb"))
        self.runs_dir = Path(runs_dir or RUNS_DIR)

    def run(self, kind: str) -> tuple[str, Path]:
        rid = latest_run(kind, root=self.runs_dir)
        if rid is None:
            raise HTTPException(503, f"no '{kind}' model run found; run `make models`")
        return rid, self.runs_dir / rid

    def run_json(self, kind: str, name: str) -> tuple[str, dict]:
        rid, d = self.run(kind)
        return rid, _read_json(d / name)


@cache
def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


@cache
def _posterior(runs_dir: Path, run_id: str):
    from atlas.mmm.fit import load_posterior

    return load_posterior(run_id, root=runs_dir)[0]


def provenance(evidence_type: str, run_id: str | None = None,
               source_tables: list[str] | None = None, note: str | None = None) -> dict:
    p: dict[str, Any] = {"evidence_type": evidence_type}
    if run_id:
        p["run_id"] = run_id
    if source_tables:
        p["source_tables"] = source_tables
    if note:
        p["note"] = note
    return p


class AskRequest(BaseModel):
    question: str = Field(..., max_length=500)


class OptimizeRequest(BaseModel):
    budget: float = Field(500_000.0, gt=0)
    objective: str = "profit_52w"
    mins: dict[str, float] | None = None
    maxs: dict[str, float] | None = None
    spend_all: bool = True
    cm_rate: float | None = Field(None, gt=0, lt=1, description="Assumption override")
    repeat_multiplier: float | None = Field(None, ge=0, description="Assumption override")

    @model_validator(mode="after")
    def _check(self) -> "OptimizeRequest":
        if self.objective not in OBJECTIVES:
            raise ValueError(f"objective must be one of {OBJECTIVES}")
        for c, lo in (self.mins or {}).items():
            if lo < 0:
                raise ValueError(f"{c}: min must be ≥ 0")
            if self.maxs and c in self.maxs and self.maxs[c] < lo:
                raise ValueError(f"{c}: max below min")
        if sum((self.mins or {}).values()) > self.budget:
            raise ValueError("channel minimums exceed the budget")
        return self


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    app = FastAPI(title="ATLAS API", version="0.1.0",
                  description="Marketing measurement and decision engine. Read-only.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                       allow_headers=["*"])

    def con():
        if not s.db_path.exists():
            raise HTTPException(503, "serving database missing; run `make build`")
        c = duckdb.connect(str(s.db_path), read_only=True)
        try:
            yield c
        finally:
            c.close()

    Con = Annotated[duckdb.DuckDBPyConnection, Depends(con)]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "db": s.db_path.exists(), "runs_dir": s.runs_dir.exists()}

    @app.get("/workspaces")
    def workspaces() -> list[dict]:
        return WORKSPACES

    # ------------------------------------------------------------------ Halden metrics

    @app.get("/halden/metrics")
    def catalog() -> dict:
        return {"metrics": metric_catalog("halden"), "provenance": provenance("Simulated")}

    @app.get("/halden/metrics/{name}")
    def metric(name: str, c: Con, start: date | None = None, end: date | None = None,
               geo: Annotated[list[str] | None, Query()] = None,
               channel: Annotated[list[str] | None, Query()] = None,
               group_by: Annotated[list[str] | None, Query()] = None) -> dict:
        f = Filters(start=start, end=end, geos=tuple(geo) if geo else None,
                    channels=tuple(channel) if channel else None)
        try:
            r = query_metric(c, name, f, tuple(group_by or ()))
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        except (MetricNotApplicable, ValueError) as e:
            raise HTTPException(422, str(e)) from e
        m = r.metric
        return clean({
            "metric": {"name": m.name, "label": m.label, "format": m.format,
                       "definition": m.definition.strip(), "caveats": list(m.caveats)},
            "filters": {"start": start, "end": end, "geo": geo, "channel": channel,
                        "group_by": group_by or []},
            "window": r.data.attrs.get("window"),
            "rows": r.data.astype(object).where(r.data.notna(), None).to_dict("records"),
            "provenance": provenance(m.evidence_type, source_tables=r.source_tables),
        })

    # ------------------------------------------------------------------ Halden measurement

    @app.get("/halden/measurement")
    def measurement(reveal_truth: bool = False) -> dict:
        rid, sm = s.run_json("halden", "summary.json")
        est = [e if reveal_truth else {k: v for k, v in e.items()
                                       if k not in ("true_roi", "abs_error", "covered90")}
               for e in sm["estimates"]]
        geo = (sm["geolift"] if reveal_truth else
               {k: v for k, v in sm["geolift"].items() if not k.startswith("true")})
        out = {"estimates": est, "diagnostics": sm["diagnostics"], "holdout": sm["holdout"],
               "attribution": sm["attribution"], "geolift": geo,
               "recommended_variant": sm["recommended_variant"], "mmm_runs": sm["mmm_runs"],
               "provenance": provenance("Modeled", rid, note=sm["label"])}
        if reveal_truth:
            out["truth"] = sm["truth"]
            out["graded"] = sm["graded"]
        return out

    @app.get("/halden/scorecard")
    def scorecard() -> dict:
        rid, sc = s.run_json("scorecard", "scorecard.json")
        m = read_manifest(rid, s.runs_dir)
        return {k: v for k, v in sc.items() if k != "regret_rows"} | {
            "config": m["config"],
            "provenance": provenance("Simulated", rid,
                                     note="Methods graded against known truth across worlds")}

    # ------------------------------------------------------------------ Halden decision

    @app.get("/halden/plan")
    def plan() -> dict:
        rid, sm = s.run_json("halden", "summary.json")
        return {"budget": sm["budget"], "objective": sm["objective"],
                "economics": sm["economics"], "current": sm["current"],
                "constraints": sm["constraints"], "observed_ranges": sm["observed_ranges"],
                "optimizer": sm["optimizer"], "tornado": sm["tornado"],
                "provenance": provenance("Modeled", sm["mmm_runs"][sm["recommended_variant"]],
                                         note=f"summary run {rid}")}

    @app.post("/halden/optimize")
    def run_optimizer(req: OptimizeRequest) -> dict:
        rid, sm = s.run_json("halden", "summary.json")
        mmm = sm["mmm_runs"][sm["recommended_variant"]]
        post = _posterior(s.runs_dir, mmm)
        base = sm["constraints"]
        scale = req.budget / base["budget"]
        mins = req.mins or {c: v * scale for c, v in base["mins"].items()}
        maxs = req.maxs or {c: v * scale for c, v in base["maxs"].items()}
        unknown = (set(mins) | set(maxs)) - set(post.channels)
        if unknown:
            raise HTTPException(422, f"unknown channels: {sorted(unknown)}")
        if sum(mins.get(c, 0) for c in post.channels) > req.budget:
            raise HTTPException(422, "channel minimums exceed the budget")
        if req.spend_all and sum(maxs.get(c, req.budget) for c in post.channels) < req.budget:
            raise HTTPException(422, "channel maximums are below the budget")
        econ = Economics(cm_rate=req.cm_rate or sm["economics"]["cm_rate"],
                         repeat_multiplier=(req.repeat_multiplier
                                            if req.repeat_multiplier is not None
                                            else sm["economics"]["repeat_multiplier"]))
        cons = Constraints(budget=req.budget, mins=mins, maxs=maxs, spend_all=req.spend_all,
                           step=base["step"])
        current = {c: v * scale for c, v in sm["current"].items()}
        try:
            r = optimize(post, cons, req.objective, econ, current, sm["observed_ranges"],
                         run_id=mmm)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        overridden = [k for k in ("cm_rate", "repeat_multiplier")
                      if getattr(req, k) is not None]
        return clean(r.to_dict() | {"assumptions_overridden": overridden,
                                    "provenance": provenance("Modeled", mmm)})

    @app.get("/halden/experiments")
    def experiments() -> dict:
        rid, sm = s.run_json("halden", "summary.json")
        return {"next_experiments": sm["next_experiments"][:10], "evpi": sm["evpi"],
                "design_power": sm["design_power"], "first_test": sm["voi_first"],
                "provenance": provenance("Modeled", rid,
                                         note="Expected value of information over the "
                                              "calibrated MMM posterior")}

    @app.get("/halden/anomalies")
    def halden_anomalies() -> dict:
        rid, a = s.run_json("anomaly", "anomaly.json")
        return {"thresholds": a["thresholds"], "fpr_target": a["fpr_target"],
                "evaluation": {k: v for k, v in a["evaluation"].items() if k != "worlds"},
                "weeks": a["halden"]["weeks"], "alerts": a["halden"]["alerts"],
                "national_series": a["halden"]["national_series"],
                "provenance": provenance("Simulated", rid)}

    # ------------------------------------------------------------------ GA4

    @app.get("/ga4/{mart}")
    def ga4_mart(mart: str, c: Con, start: date | None = None,
                 end: date | None = None) -> dict:
        if mart not in GA4_MARTS:
            raise HTTPException(404, f"unknown GA4 mart; choose from {sorted(GA4_MARTS)}")
        table = GA4_MARTS[mart]
        cols = {r[0] for r in c.execute(
            "select column_name from information_schema.columns where table_schema = 'ga4' "
            "and table_name = ?", [table]).fetchall()}
        if not cols:
            raise HTTPException(503, "GA4 marts not built; run `make build` with extracts")
        where, params = [], []
        if "date" in cols:
            if start:
                where.append("date >= ?")
                params.append(start)
            if end:
                where.append("date <= ?")
                params.append(end)
        sql = f"select * from ga4.{table}" + (f" where {' and '.join(where)}" if where else "")
        df = c.execute(sql, params).df()
        return clean({"rows": df.astype(object).where(df.notna(), None).to_dict("records"),
                      "provenance": provenance("Observed", source_tables=[f"ga4.{table}"])})

    @app.get("/ga4-anomalies")
    def ga4_anomalies() -> dict:
        rid, a = s.run_json("anomaly", "anomaly.json")
        if not a.get("ga4"):
            raise HTTPException(503, "anomaly run has no GA4 section")
        g = a["ga4"]
        return {"threshold": g["threshold"], "alerts": g["alerts"],
                "late_january": g["late_january"], "provenance": provenance("Observed", rid)}

    # ------------------------------------------------------------------ Criteo

    @app.get("/criteo/readout")
    def criteo() -> dict:
        rid, r = s.run_json("criteo", "readout.json")
        return r | {"provenance": provenance("Experimental", rid)}

    # ------------------------------------------------------------------ Analyst

    class Tools:
        """The analyst's only window on the data: the same stored runs and metric layer the
        pages use."""

        def summary(self):
            return s.run_json("halden", "summary.json")

        def anomalies(self):
            return s.run_json("anomaly", "anomaly.json")

        def scorecard(self):
            try:
                return s.run_json("scorecard", "scorecard.json")
            except HTTPException:
                return None

        def criteo(self):
            return s.run_json("criteo", "readout.json")

        def experiments(self):
            rid, sm = s.run_json("halden", "summary.json")
            return rid, {"next_experiments": sm["next_experiments"], "evpi": sm["evpi"]}

        def optimize(self, budget, spend_all):
            return run_optimizer(OptimizeRequest(budget=budget, spend_all=spend_all))

        def metric(self, name, start, end, geo):
            with duckdb.connect(str(s.db_path), read_only=True) as c:
                return metric(name, c, start=date.fromisoformat(start),
                              end=date.fromisoformat(end), geo=[geo] if geo else None,
                              channel=None, group_by=None)

        def last_week(self):
            with duckdb.connect(str(s.db_path), read_only=True) as c:
                r = query_metric(c, "revenue", Filters(), ("week_start",))
            return str(r.data.week_start.max())[:10]

    @app.get("/analyst/suggestions")
    def suggestions() -> list[str]:
        return SUGGESTIONS

    @app.post("/analyst")
    def ask(req: AskRequest) -> dict:
        return clean(analyst_answer(req.question, Tools()))

    return app


app = create_app()
