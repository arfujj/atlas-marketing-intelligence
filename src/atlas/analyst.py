"""Analyst: a deterministic question router over a fixed set of tools.

No language model writes numbers here. A question is matched to one intent by ordered keyword
rules; the intent's tool reads stored runs or the metric layer through the `Tools` protocol (the
API supplies the implementation), and a template turns the result into sentences. Every number
in an answer is also returned as a `Fact` with its evidence type and source (run id or table),
so the UI can show where it came from. Unmatched questions get the list of what can be asked,
not a guess.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

CHANNEL_NAMES = {
    "search_nonbrand": "Search · Non-brand",
    "search_brand": "Search · Brand",
    "meta_prospecting": "Meta · Prospecting",
    "meta_retargeting": "Meta · Retargeting",
    "tiktok": "TikTok",
    "youtube": "YouTube",
}
CHANNEL_ALIASES = {
    "non-brand": "search_nonbrand",
    "nonbrand": "search_nonbrand",
    "brand search": "search_brand",
    "brand": "search_brand",
    "prospecting": "meta_prospecting",
    "retargeting": "meta_retargeting",
    "tiktok": "tiktok",
    "youtube": "youtube",
}
METHOD_NAMES = {
    "last_click": "last-click attribution",
    "markov": "Markov attribution",
    "ols_naive": "naive regression",
    "bayes_default": "MMM with default priors",
    "bayes_dag": "DAG-informed MMM",
    "bayes_dag_calibrated": "calibrated MMM",
    "current": "the current plan",
}
SUGGESTIONS = [
    "Why did revenue fall last week?",
    "How should we spend $500K next quarter?",
    "Which channels does last-click over-credit?",
    "Which experiment should we run next?",
    "How much should we trust the MMM?",
    "What was revenue in R03 over the last 13 weeks?",
    "Did demand fall in late January on the GA4 store?",
    "Did the Criteo ads work?",
]


class Tools(Protocol):
    def summary(self) -> tuple[str, dict]: ...
    def anomalies(self) -> tuple[str, dict]: ...
    def scorecard(self) -> tuple[str, dict] | None: ...
    def criteo(self) -> tuple[str, dict]: ...
    def experiments(self) -> tuple[str, dict]: ...
    def optimize(self, budget: float, spend_all: bool) -> dict: ...
    def metric(self, name: str, start: str | None, end: str | None, geo: str | None) -> dict: ...
    def last_week(self) -> str: ...


@dataclass
class Fact:
    label: str
    value: str
    evidence: str
    source: str


@dataclass
class Answer:
    intent: str
    question: str
    paragraphs: list[str]
    facts: list[Fact] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    link: dict | None = None  # {"href", "label"}: the page that shows the full analysis

    def to_dict(self) -> dict:
        return asdict(self)


def money(v: float) -> str:
    a = abs(v)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a / 1e3:.1f}K" if a >= 1e3 else f"${a:,.0f}"
    s = s.replace(".0M", "M").replace(".0K", "K")
    return ("−" if v < 0 else "") + s


def pct(v: float, d: int = 1, signed: bool = False) -> str:
    s = f"{abs(v) * 100:.{d}f}%"
    return ("+" if v > 0 else "−" if v < 0 else "") + s if signed else ("−" if v < 0 else "") + s


def ch(c: str) -> str:
    return CHANNEL_NAMES.get(c, c.replace("_", " "))


# --------------------------------------------------------------------------- intents


def _week_minus(week: str, n: int) -> str:
    from datetime import date, timedelta

    return str(date.fromisoformat(week) - timedelta(weeks=n))


def explain_change(q: str, t: Tools) -> Answer:
    rid, a = t.anomalies()
    asked = re.search(r"\d{4}-\d{2}-\d{2}", q)
    weeks = {w["week"]: w for w in a["halden"]["weeks"]}
    week = asked.group(0) if asked else t.last_week()
    w = weeks.get(week)
    facts = [
        Fact(
            "Detector recall (held-out worlds)", pct(a["evaluation"]["recall"], 0), "Simulated", rid
        ),
        Fact("Detector precision", pct(a["evaluation"]["precision"], 0), "Simulated", rid),
    ]
    if not w or not w["flagged_series"]:
        return Answer(
            "explain_change",
            q,
            [
                f"Nothing unusual was flagged in the week of {week}: every monitored series stayed "
                "inside its expected range."
            ],
            facts,
            ["Show all flagged weeks"],
            {"href": "/halden/changes", "label": "Changes"},
        )
    paras = [
        f"Week of {week}: {len(w['flagged_series'])} series moved outside their expected range."
    ]
    for k, z in sorted(w["flagged_series"].items(), key=lambda kv: kv[1])[:3]:
        facts.append(
            Fact(k.replace(":", " · ").replace("_", " "), f"z = {z:.1f}", "Simulated", rid)
        )
    if w["hypotheses"]:
        h = w["hypotheses"][0]
        paras.append(f"Most likely explanation ({h['status']}): {h['title']}.")
        paras.append("Evidence: " + "; ".join(h["evidence"]) + ".")
        paras.append("Next checks: " + "; ".join(h["follow_ups"]) + ".")
        if len(w["hypotheses"]) > 1:
            paras.append(
                "Also considered: "
                + "; ".join(f"{x['title']} ({x['status']})" for x in w["hypotheses"][1:])
                + "."
            )
    else:
        paras.append(
            "No rule explains this pattern. At the calibrated threshold about 1 in 200 "
            "series-weeks alerts by chance, so treat it as noise unless it recurs."
        )
    return Answer(
        "explain_change",
        q,
        paras,
        facts,
        ["Which channels does last-click over-credit?", "How should we spend $500K next quarter?"],
        {"href": "/halden/changes", "label": "Changes"},
    )


def plan_budget(q: str, t: Tools) -> Answer:
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*(k|m|thousand|million)?\b", q.lower().replace(",", ""))
    budget = 500_000.0
    if m:
        v = float(m.group(1))
        unit = m.group(2) or ""
        budget = v * (1e6 if unit in ("m", "million") else 1e3 if unit in ("k", "thousand") else 1)
    if not 50_000 <= budget <= 5_000_000:
        return Answer(
            "plan_budget",
            q,
            [
                f"I can plan quarterly budgets between $50K and $5M; {money(budget)} is outside "
                "that range, which is far from any spend level in the history."
            ],
            link={"href": "/halden/decision", "label": "Decision"},
        )
    under = bool(re.search(r"less|under|profitab|optimal level|too (big|much)", q.lower()))
    r = t.optimize(budget, spend_all=not under)
    rid, o = r["run_id"], r["objective"]
    up = r["uplift"][o]
    moves = sorted(r["channels"], key=lambda c: c["proposed"] - c["current"])
    cuts = [c for c in moves if c["proposed"] - c["current"] < -1_000]
    adds = [c for c in reversed(moves) if c["proposed"] - c["current"] > 1_000]
    spent = sum(c["proposed"] for c in r["channels"])
    scaled = "" if abs(budget - 500_000) < 1 else f" (current mix scaled to {money(budget)})"
    paras = [f"For a {money(budget)} quarter, optimising 52-week contribution profit{scaled}:"]
    if cuts:
        paras.append(
            "Cut "
            + ", ".join(
                f"{ch(c['channel'])} ({money(c['current'])} → {money(c['proposed'])})" for c in cuts
            )
            + "."
        )
    if adds:
        paras.append(
            "Increase "
            + ", ".join(
                f"{ch(c['channel'])} ({money(c['current'])} → {money(c['proposed'])})" for c in adds
            )
            + "."
        )
    paras.append(
        f"Expected gain over the current mix {money(up['mean'])} (P10 {money(up['p10'])}, "
        f"P90 {money(up['p90'])}); the new plan beats the current one in "
        f"{pct(r['prob_proposed_beats_current'], 0)} of posterior draws."
    )
    if not r["spend_all"] and spent < budget - 1:
        paras.append(
            f"Allowed to spend less, the most profitable level is {money(spent)}: past "
            "that, every channel's next dollar returns less than break-even."
        )
    be = r.get("break_even_mroi")
    forced = [
        c
        for c in r["channels"]
        if r["spend_all"]
        and be
        and c["proposed"] > c["min"] + 1
        and c["mroi_proposed"]["mean"] < be
    ]
    if forced:
        paras.append(
            "Caveat: the budget is larger than the model can spend profitably ("
            + ", ".join(ch(c["channel"]) for c in forced)
            + ' end below break-even). Ask "what is the most profitable level?" to '
            "see how much to keep."
        )
    outside = [ch(c["channel"]) for c in r["channels"] if c["outside_observed_range"]]
    if outside:
        paras.append(
            "Extrapolation warning: " + ", ".join(outside) + " would run at weekly spend "
            "never seen in the history."
        )
    facts = [
        Fact("Expected gain (mean)", money(up["mean"]), "Modeled", rid),
        Fact("P10 / P90", f"{money(up['p10'])} / {money(up['p90'])}", "Modeled", rid),
        Fact("Contribution margin", f"{r['economics']['cm_rate']:.2f}", "Assumption", rid),
    ]
    return Answer(
        "plan_budget",
        q,
        paras,
        facts,
        [
            "What is the most profitable level?",
            "Which experiment should we run next?",
            "How much should we trust the MMM?",
        ],
        {"href": "/halden/decision", "label": "Decision"},
    )


def next_experiment(q: str, t: Tools) -> Answer:
    rid, e = t.experiments()
    ranked = sorted(e["next_experiments"], key=lambda x: -x["net_value"])
    b = ranked[0]
    paras = [
        f"Best next test by net value: {'an' if str(b['n_weeks']).startswith('8') else 'a'} "
        f"{b['n_weeks']}-week go-dark of {ch(b['channel'])} "
        f"({b.get('holdout_label', '')}).",
        f"Value of information {money(b['evsi'])}, expected cost "
        f"{money(b['expected_test_cost'])}, net {money(b['net_value'])}. "
        "Power at the predicted effect is "
        f"{pct(b['power_at_predicted_effect'], 0)}, so a null result would be inconclusive.",
    ]
    if b["expected_test_cost"] < 0:
        paras.append(
            "The cost is negative because pausing the channel saves more spend than the "
            "revenue it is expected to lose."
        )
    if b["net_value"] <= 0:
        paras = ["No candidate test pays for itself on this decision. " + paras[1]]
    paras.append(
        f"Perfect information about every channel would be worth at most "
        f"{money(e['evpi'])} for this decision."
    )
    facts = [
        Fact("Value of information", money(b["evsi"]), "Modeled", rid),
        Fact("Net value", money(b["net_value"]), "Modeled", rid),
    ]
    return Answer(
        "next_experiment",
        q,
        paras,
        facts,
        ["How should we spend $500K next quarter?"],
        {"href": "/halden/decision", "label": "Decision"},
    )


def model_trust(q: str, t: Tools) -> Answer:
    rid, s = t.summary()
    v = s["recommended_variant"]
    d = s["diagnostics"][v]
    paras = [
        f"The recommended model ({METHOD_NAMES[v]}) converged: max R-hat {d['rhat_max']:.3f}, "
        f"{d['divergences']} divergences, minimum effective sample size "
        f"{d['ess_bulk_min']:.0f}."
    ]
    facts = [Fact("R-hat (max)", f"{d['rhat_max']:.3f}", "Modeled", s["mmm_runs"][v])]
    ho = s["holdout"].get(v, {}).get("holdout")
    if ho:
        paras.append(
            f"On 13 held-out weeks its error is {pct(ho['mape'])} against "
            f"{pct(ho['baseline_mape_trailing13'])} for a trailing average: a narrow win, "
            "and fitting sales well does not by itself make ROI estimates right."
        )
        facts.append(Fact("Holdout error (MAPE)", pct(ho["mape"]), "Modeled", rid))
    sc = t.scorecard()
    if sc:
        sid, c = sc
        row = next(r for r in c["roi_by_method"] if r["method"] == v)
        lc = next(r for r in c["roi_by_method"] if r["method"] == "last_click")
        paras.append(
            f"Across {c['n_worlds']} simulated worlds with known truth, its ROI estimates "
            f"miss by {row['mean_abs_error']:.2f} per dollar on average (last-click: "
            f"{lc['mean_abs_error']:.2f}) and its 90% intervals contain the truth "
            f"{pct(row['coverage90'], 0)} of the time."
        )
        facts += [
            Fact("Mean ROI error, 24 worlds", f"{row['mean_abs_error']:.2f}", "Simulated", sid),
            Fact("Interval coverage", pct(row["coverage90"], 0), "Simulated", sid),
        ]
    paras.append(
        "It is generous to the model that its functional forms match the simulator's; "
        "trust it for direction and ranking, and test before large moves."
    )
    return Answer(
        "model_trust",
        q,
        paras,
        facts,
        ["Which channels does last-click over-credit?", "Which experiment should we run next?"],
        {"href": "/halden/evidence", "label": "Evidence"},
    )


def attribution_gap(q: str, t: Tools) -> Answer:
    rid, s = t.summary()
    v = s["recommended_variant"]
    est = {(e["channel"], e["method"]): e["roi_mean"] for e in s["estimates"]}
    rows = [(c, est.get((c, "last_click")), est.get((c, v))) for c in CHANNEL_NAMES]
    rows = [r for r in rows if r[1] is not None and r[2] is not None]
    rows.sort(key=lambda r: -(r[1] / max(r[2], 1e-9)))
    over = [r for r in rows if r[1] > 1.5 * r[2]]
    under = [r for r in rows if r[1] < 0.67 * r[2]]
    paras = []
    if over:
        paras.append(
            "Last-click over-credits "
            + ", ".join(f"{ch(c)} ({lc:.1f} vs {m:.1f} per dollar)" for c, lc, m in over)
            + ": these channels mostly collect demand that other channels created."
        )
    if under:
        paras.append(
            "It under-credits "
            + ", ".join(f"{ch(c)} ({lc:.1f} vs {m:.1f})" for c, lc, m in under)
            + "."
        )
    paras.append(
        f"First number: last-click revenue per dollar (Attributed). Second: incremental "
        f"revenue per dollar from the {METHOD_NAMES[v]} (Modeled)."
    )
    facts = [
        Fact(f"{ch(c)}: last-click / MMM", f"{lc:.1f} / {m:.1f}", "Attributed vs Modeled", rid)
        for c, lc, m in rows[:4]
    ]
    return Answer(
        "attribution_gap",
        q,
        paras,
        facts,
        ["How much should we trust the MMM?", "How should we spend $500K next quarter?"],
        {"href": "/halden/evidence", "label": "Evidence"},
    )


def ga4_january(q: str, t: Tools) -> Answer:
    rid, a = t.anomalies()
    g = (a.get("ga4") or {}).get("late_january")
    if not g:
        return Answer("ga4_january", q, ["The GA4 investigation has not been run in this build."])
    r = g["ratios"]
    paras = [
        g["conclusion"],
        f"Evidence status: {g['evidence_status']}. {g['status_note']}",
        "Next checks: " + "; ".join(g["follow_ups"]) + ".",
    ]
    facts = [
        Fact(
            "Purchase events per 1k sessions",
            f"{r['purchase_events_per_1k_sessions']['before']:.1f} → "
            f"{r['purchase_events_per_1k_sessions']['after']:.1f}",
            "Observed",
            rid,
        ),
        Fact(
            "Share with a transaction id",
            f"{pct(r['identified_transaction_share']['before'], 0)} → "
            f"{pct(r['identified_transaction_share']['after'], 0)}",
            "Observed",
            rid,
        ),
    ]
    return Answer("ga4_january", q, paras, facts, [], {"href": "/ga4", "label": "GA4 store"})


def criteo_lift(q: str, t: Tools) -> Answer:
    rid, r = t.criteo()
    v, c = r["itt"]["visit"], r["itt"]["conversion"]
    s = r["uplift"]["outcomes"]["visit"]["s_learner"]
    avg = r["uplift"]["outcomes"]["visit"]["itt_eval_set"]
    paras = [
        f"Yes. In a randomized test of {r['n_rows'] / 1e6:.1f}M users, assignment to ads "
        f"raised visits by {pct(v['rel_lift'], 1, True)} (95% CI {pct(v['rel_lift_ci95'][0])} to "
        f"{pct(v['rel_lift_ci95'][1])}) and conversions by {pct(c['rel_lift'], 1, True)}.",
        f"Randomization checks out (sample-ratio p = {r['srm']['p_value']:.3f}).",
        f"Targeting matters: the top 10% of users ranked by an uplift model gain "
        f"{pct(s['uplift_top10'], 1)} in visit rate on held-out users, "
        f"{s['uplift_top10'] / avg:.1f}× the average.",
        "This dataset has no spend or revenue, so it cannot say whether the ads were profitable.",
    ]
    facts = [
        Fact("Visit lift", pct(v["rel_lift"], 1, True), "Experimental", rid),
        Fact("Conversion lift", pct(c["rel_lift"], 1, True), "Experimental", rid),
    ]
    return Answer("criteo_lift", q, paras, facts, [], {"href": "/criteo", "label": "Criteo"})


METRIC_WORDS = [  # longest first so "contribution profit" wins over "profit"
    ("conversion rate", "conversion_rate"),
    ("contribution profit", "contribution_profit"),
    ("new customers", "new_customers"),
    ("blended cac", "blended_cac"),
    ("cac", "blended_cac"),
    ("mer", "mer"),
    ("revenue", "revenue"),
    ("spend", "spend"),
    ("orders", "orders"),
    ("sessions", "sessions"),
    ("aov", "aov"),
    ("profit", "contribution_profit"),
]


def metric_lookup(q: str, t: Tools, name: str) -> Answer:
    ql = q.lower()
    geo_m = re.search(r"\br(\d{2})\b", ql)
    geo = f"R{geo_m.group(1)}" if geo_m else None
    n_m = re.search(r"last (\d+) weeks?", ql)
    n = int(n_m.group(1)) if n_m else 13
    n = max(1, min(n, 52))
    end = t.last_week()
    start = _week_minus(end, n - 1)
    prev_end, prev_start = _week_minus(start, 1), _week_minus(start, n)
    cur = t.metric(name, start, end, geo)
    prev = t.metric(name, prev_start, prev_end, geo)
    v = cur["rows"][0]["value"]
    p = prev["rows"][0]["value"]
    fmt = cur["metric"]["format"]
    show = (
        money
        if fmt == "currency"
        else (lambda x: pct(x, 2))
        if fmt == "percent"
        else (lambda x: f"{x:,.2f}")
        if fmt == "ratio"
        else (lambda x: f"{x:,.0f}")
    )
    where = f" in {geo}" if geo else ""
    paras = [f"{cur['metric']['label']}{where}, {start} to {end} ({n} weeks): {show(v)}."]
    if p:
        paras.append(
            f"That is {pct(v / p - 1, 1, True)} versus the previous {n} weeks ({show(p)})."
        )
    paras.append("Definition: " + cur["metric"]["definition"])
    src = ", ".join(cur["provenance"].get("source_tables", []))
    facts = [Fact(cur["metric"]["label"] + where, show(v), cur["provenance"]["evidence_type"], src)]
    return Answer(
        "metric",
        q,
        paras,
        facts,
        ["Why did revenue fall last week?"],
        {
            "href": f"/halden?start={start}&end={end}" + (f"&geo={geo}" if geo else ""),
            "label": "Performance",
        },
    )


def help_answer(q: str) -> Answer:
    return Answer(
        "help",
        q,
        [
            "I answer a fixed set of questions from ATLAS's stored analyses, so every number "
            "can be traced to a run. I could not match this question to one of them. "
            "Try one of these:"
        ],
        follow_ups=SUGGESTIONS,
    )


def route(question: str, t: Tools) -> Answer:
    q = question.strip()
    ql = q.lower()
    if not q:
        return help_answer(q)
    if re.search(r"criteo|uplift|\brct\b|randomi[sz]ed", ql):
        return criteo_lift(q, t)
    if re.search(r"\bga4\b|merch|google|january|\bjan\b", ql):
        return ga4_january(q, t)
    if re.search(r"why|what (happened|changed)|drop|fell|fall|spike|anomal|unusual", ql):
        return explain_change(q, t)
    if re.search(r"experiment|test next|go-dark|holdout|geo.?lift|what should we test", ql):
        return next_experiment(q, t)
    if re.search(r"trust|accura|reliab|converge|r-hat|how good|mmm", ql):
        return model_trust(q, t)
    if re.search(r"last.?click|attribut|over.?credit|under.?credit|roas", ql):
        return attribution_gap(q, t)
    if re.search(
        r"budget|allocat|spend \$|\$\s*\d|how (should|much) .*spend|plan|"
        r"profitable level",
        ql,
    ):
        return plan_budget(q, t)
    for word, name in METRIC_WORDS:
        if re.search(rf"\b{word}\b", ql):
            return metric_lookup(q, t, name)
    return help_answer(q)


def answer(question: str, t: Tools) -> dict[str, Any]:
    return route(question, t).to_dict()
