"use client";

import { useState, useTransition } from "react";

import { EvidenceBadge } from "@/components/ui";
import { channelLabel, money, pct, ratio } from "@/lib/format";
import type { OptimizationResult } from "@/lib/types";

const OBJECTIVES = [
  { id: "profit_52w", label: "52-week contribution profit" },
  { id: "profit_first_order", label: "First-order contribution profit" },
  { id: "revenue", label: "New-customer revenue" },
];

export function Planner({ initial }: { initial: OptimizationResult }) {
  const [res, setRes] = useState(initial);
  const [budget, setBudget] = useState(initial.budget);
  const [objective, setObjective] = useState(initial.objective);
  const [cm, setCm] = useState(initial.economics.cm_rate);
  const [rep, setRep] = useState(initial.economics.repeat_multiplier);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const dirty =
    budget !== res.budget ||
    objective !== res.objective ||
    cm !== res.economics.cm_rate ||
    rep !== res.economics.repeat_multiplier;

  function run() {
    start(async () => {
      setError(null);
      const r = await fetch("/api/optimize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ budget, objective, cm_rate: cm, repeat_multiplier: rep }),
      });
      const body = await r.json();
      if (!r.ok) {
        setError(typeof body.detail === "string" ? body.detail : (body.detail?.[0]?.msg ?? "Request rejected"));
        return;
      }
      setRes(body);
    });
  }

  const o = res.objective;
  const cur = res.outcome_current[o];
  const pro = res.outcome_proposed[o];
  const up = res.uplift[o];
  const outside = res.channels.filter((c) => c.outside_observed_range);
  const unit = o === "revenue" ? "revenue" : "profit";

  return (
    <div className="flex flex-col gap-5">
      <form
        className="card flex flex-wrap items-end gap-4 p-4 text-xs"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <label className="flex flex-col gap-1 text-ink-2">
          Quarterly budget
          <input
            type="number"
            min={100000}
            max={1500000}
            step={10000}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
            className="w-36 rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink tnum"
          />
        </label>
        <label className="flex flex-col gap-1 text-ink-2">
          Optimise for
          <select value={objective} onChange={(e) => setObjective(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink">
            {OBJECTIVES.map((x) => (
              <option key={x.id} value={x.id}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-ink-2">
          <span className="flex items-center gap-1">
            Contribution margin <EvidenceBadge type="Assumption" />
          </span>
          <input type="number" min={0.05} max={0.9} step="any" value={Number(cm.toFixed(3))} onChange={(e) => setCm(Number(e.target.value))} className="w-24 rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink tnum" />
        </label>
        <label className="flex flex-col gap-1 text-ink-2">
          <span className="flex items-center gap-1">
            Repeat-value multiplier <EvidenceBadge type="Assumption" />
          </span>
          <input type="number" min={0} max={5} step="any" value={Number(rep.toFixed(3))} onChange={(e) => setRep(Number(e.target.value))} className="w-24 rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink tnum" />
        </label>
        <button disabled={pending || !dirty} className="rounded bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
          {pending ? "Optimising…" : "Re-optimise"}
        </button>
        <span className="text-muted">Channel limits: 50%–150% of current spend, scaled to the budget.</span>
        {error && (
          <p role="alert" className="w-full text-bad">
            {error}
          </p>
        )}
      </form>

      <div className="grid gap-3 md:grid-cols-3" aria-live="polite">
        <Outcome label={`Expected ${unit}, current plan`} q={cur} />
        <Outcome label={`Expected ${unit}, recommended plan`} q={pro} />
        <div className="card flex flex-col gap-1 p-4">
          <span className="text-xs text-ink-2">Gain from switching</span>
          <span className="text-2xl font-semibold">{money(up.mean, { compact: true })}</span>
          <span className="text-xs text-ink-2">
            P10 {money(up.p10, { compact: true })} · P90 {money(up.p90, { compact: true })} · better in {pct(res.prob_proposed_beats_current, 0)} of posterior draws
          </span>
        </div>
      </div>

      {outside.length > 0 && (
        <p className="text-xs text-bad">
          ⚠ {outside.map((c) => channelLabel(c.channel)).join(", ")}: recommended weekly spend is outside anything observed in the history.
          The response curve there is an extrapolation.
        </p>
      )}

      <div className="card overflow-x-auto p-4">
        <table className="data">
          <thead>
            <tr>
              <th>Channel</th>
              <th className="num">Current</th>
              <th className="num">Recommended</th>
              <th className="num">Change</th>
              <th className="num">Limits</th>
              <th className="num">Marginal ROI now (P10–P90)</th>
              <th className="num">Marginal ROI after</th>
            </tr>
          </thead>
          <tbody>
            {res.channels.map((c) => {
              const d = c.proposed - c.current;
              return (
                <tr key={c.channel}>
                  <td>
                    {channelLabel(c.channel)}
                    {c.outside_observed_range && <span className="ml-1 text-bad" title="Outside observed spend range">⚠</span>}
                  </td>
                  <td className="num">{money(c.current, { compact: true })}</td>
                  <td className="num font-medium">
                    {money(c.proposed, { compact: true })}
                    {Math.abs(c.proposed - c.max) < 1 && <span className="ml-1 text-[10px] font-normal text-muted">at max</span>}
                    {Math.abs(c.proposed - c.min) < 1 && <span className="ml-1 text-[10px] font-normal text-muted">at min</span>}
                  </td>
                  <td className="num">
                    <span aria-hidden>{d > 500 ? "▲ " : d < -500 ? "▼ " : ""}</span>
                    {money(d, { compact: true })}
                  </td>
                  <td className="num text-muted">
                    {money(c.min, { compact: true })}–{money(c.max, { compact: true })}
                  </td>
                  <td className="num">
                    {ratio(c.mroi_current.mean, 2)} <span className="text-muted">({ratio(c.mroi_current.p10, 2)}–{ratio(c.mroi_current.p90, 2)})</span>
                  </td>
                  <td className="num">{ratio(c.mroi_proposed.mean, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {res.break_even_mroi != null && Number.isFinite(res.break_even_mroi) && (
          <p className="mt-3 text-xs text-ink-2">
            Break-even marginal ROI for this objective: {ratio(res.break_even_mroi, 2)} revenue per extra dollar. Below it, the next dollar in that channel loses money.
          </p>
        )}
        <details className="mt-3 text-xs text-ink-2">
          <summary className="cursor-pointer">How was this calculated?</summary>
          <p className="mt-2 leading-relaxed">{res.explanation}</p>
          {res.assumptions_overridden && res.assumptions_overridden.length > 0 && (
            <p className="mt-1">Assumptions you changed: {res.assumptions_overridden.join(", ").replaceAll("_", " ")}.</p>
          )}
        </details>
      </div>
    </div>
  );
}

function Outcome({ label, q }: { label: string; q: { mean: number; p10: number; p90: number } }) {
  return (
    <div className="card flex flex-col gap-1 p-4">
      <span className="flex items-center justify-between text-xs text-ink-2">
        {label} <EvidenceBadge type="Modeled" />
      </span>
      <span className="text-2xl font-semibold">{money(q.mean, { compact: true })}</span>
      <span className="text-xs text-ink-2">
        Conservative (P10) {money(q.p10, { compact: true })} · optimistic (P90) {money(q.p90, { compact: true })}
      </span>
    </div>
  );
}
