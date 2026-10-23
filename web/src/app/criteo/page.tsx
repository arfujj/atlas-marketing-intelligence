import { connection } from "next/server";
import { Suspense } from "react";

import { XYLines } from "@/components/charts";
import { Callout, Card, ErrorState, EvidenceBadge, PageHeader, PageSkeleton, ProvenanceLine } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { num, pct } from "@/lib/format";
import type { Provenance } from "@/lib/types";

interface Lift {
  rate_treatment: number;
  rate_control: number;
  abs_lift: number;
  abs_lift_ci95: [number, number];
  rel_lift: number;
  rel_lift_ci95: [number, number];
  p_value: number;
}
interface Learner {
  qini_coefficient: number;
  qini_coefficient_ci95: [number, number];
  uplift_top10: number;
  uplift_top20: number;
  uplift_top30: number;
  curve: { fraction: number[]; qini: number[] };
}
interface Readout {
  n_rows: number;
  license: string;
  srm: { n_treatment: number; n_control: number; observed_ratio: number; expected_ratio: number; p_value: number; srm_detected: boolean };
  itt: Record<string, Lift>;
  cace: Record<string, { first_stage_exposure_rate_treatment: number; cace: number; cace_ci95: [number, number]; naive_exposed_vs_control: number }>;
  power: Record<string, { mde_rel_80pct: number; n_required_for_5pct_rel_lift: number }>;
  uplift: {
    train_rows: number;
    eval_rows: number;
    n_bootstrap: number;
    model: string;
    outcomes: Record<string, Record<string, Learner | number>>;
  };
  provenance: Provenance;
}

const LEARNERS = [
  ["s_learner", "S-learner"],
  ["t_learner", "T-learner"],
  ["x_learner", "X-learner"],
  ["random", "Random targeting"],
] as const;

export default function Criteo() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content />
    </Suspense>
  );
}

async function Content() {
  await connection();
  let r: Readout;
  try {
    r = await api<Readout>("/criteo/readout");
  } catch (e) {
    return <ErrorState message={e instanceof ApiError ? e.message : "The ATLAS API is not reachable."} />;
  }
  const visit = r.uplift.outcomes.visit;
  const curve = (visit.s_learner as Learner).curve.fraction.map((f, i) => {
    const row: Record<string, number> = { fraction: f };
    for (const [k] of LEARNERS) row[k] = (visit[k] as Learner).curve.qini[i];
    return row;
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Criteo incrementality test"
        lede={`A real randomized test: ${num(r.n_rows)} users, 85% assigned to see ads, 15% held out. Randomization makes the difference between groups causal; no model is needed for the headline.`}
      >
        <ProvenanceLine p={r.provenance} />
      </PageHeader>

      <Callout>
        Observed RCT data (Criteo Uplift v2.1, {r.license}). Features are anonymised and there is no spend or revenue, so this workspace
        answers &ldquo;did ads cause visits and conversions, and for whom?&rdquo;, not &ldquo;was it profitable?&rdquo;. Raw rows are never stored in
        this repository.
      </Callout>

      <Card title="Randomization check" subtitle="Sample-ratio mismatch test: does the observed split match the designed 85/15?">
        <p className="text-sm">
          {r.srm.srm_detected ? "⚠ Mismatch detected" : "✓ No mismatch"}: {num(r.srm.n_treatment)} treated, {num(r.srm.n_control)} control,
          observed treated share {pct(r.srm.observed_ratio, 4)} (χ² p = {r.srm.p_value.toFixed(3)}).
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(r.itt).map(([outcome, l]) => (
          <Card key={outcome} title={`Effect of ad assignment on ${outcome}s`} subtitle="Intent-to-treat: everyone as randomized, exposed or not.">
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-semibold">{pct(l.rel_lift, 1, true)}</span>
              <EvidenceBadge type="Experimental" />
            </div>
            <p className="mt-1 text-xs text-ink-2">
              95% CI {pct(l.rel_lift_ci95[0], 1, true)} to {pct(l.rel_lift_ci95[1], 1, true)} relative; {pct(l.abs_lift, 3, true)} absolute (
              {pct(l.abs_lift_ci95[0], 3)} to {pct(l.abs_lift_ci95[1], 3)}).
            </p>
            <table className="data mt-3">
              <tbody>
                <tr>
                  <td>{outcome} rate, treated</td>
                  <td className="num">{pct(l.rate_treatment, 3)}</td>
                </tr>
                <tr>
                  <td>{outcome} rate, control</td>
                  <td className="num">{pct(l.rate_control, 3)}</td>
                </tr>
                <tr>
                  <td>Effect on users actually exposed (CACE)</td>
                  <td className="num">
                    {pct(r.cace[outcome].cace, 2, true)}{" "}
                    <span className="text-muted">
                      ({pct(r.cace[outcome].cace_ci95[0], 2)} to {pct(r.cace[outcome].cace_ci95[1], 2)})
                    </span>
                  </td>
                </tr>
                <tr>
                  <td>Naive &ldquo;exposed vs control&rdquo; (biased)</td>
                  <td className="num text-muted">{pct(r.cace[outcome].naive_exposed_vs_control, 2, true)}</td>
                </tr>
                <tr>
                  <td>Smallest detectable lift (80% power)</td>
                  <td className="num">{pct(r.power[outcome].mde_rel_80pct, 1)} relative</td>
                </tr>
              </tbody>
            </table>
          </Card>
        ))}
      </div>
      <p className="-mt-2 text-xs text-ink-2">
        CACE uses random assignment as an instrument for exposure (only {pct(r.cace.visit.first_stage_exposure_rate_treatment, 1)} of the treated group
        was exposed). It assumes ads affect people only through exposure and that no control user was exposed. Comparing exposed users with the
        control group directly overstates the effect, because who gets exposed is not random.
      </p>

      <Card
        title="Who should see ads? Uplift targeting on held-out users"
        subtitle={`Models trained on ${num(r.uplift.train_rows)} users, scored on ${num(r.uplift.eval_rows)} unseen users. Qini curve: extra visits caused, per user, when targeting the top share ranked by each model.`}
      >
        <XYLines
          data={curve}
          x="fraction"
          xFormat="pct"
          yFormat="pct2"
          series={LEARNERS.map(([k, name]) => ({ key: k, name, dashed: k === "random", color: k === "random" ? "var(--muted)" : undefined }))}
        />
        <table className="data mt-4">
          <thead>
            <tr>
              <th>Targeting</th>
              <th className="num">Qini coefficient (95% CI)</th>
              <th className="num">Visit uplift, top 10%</th>
              <th className="num">Top 30%</th>
            </tr>
          </thead>
          <tbody>
            {LEARNERS.map(([k, name]) => {
              const l = visit[k] as Learner;
              return (
                <tr key={k}>
                  <td>{name}</td>
                  <td className="num">
                    {l.qini_coefficient.toFixed(4)}{" "}
                    <span className="text-muted">
                      ({l.qini_coefficient_ci95[0].toFixed(4)} to {l.qini_coefficient_ci95[1].toFixed(4)})
                    </span>
                  </td>
                  <td className="num">{pct(l.uplift_top10, 2, true)}</td>
                  <td className="num">{pct(l.uplift_top30, 2, true)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-ink-2">
          Showing ads only to the top 10% ranked by the S-learner yields a visit uplift of {pct((visit.s_learner as Learner).uplift_top10, 1)}, about{" "}
          {((visit.s_learner as Learner).uplift_top10 / (visit.itt_eval_set as number)).toFixed(1)}× the average effect of{" "}
          {pct(visit.itt_eval_set as number, 2)}. Model: {r.uplift.model}. CIs from {r.uplift.n_bootstrap} bootstrap resamples of the evaluation set.
        </p>
      </Card>
    </div>
  );
}
