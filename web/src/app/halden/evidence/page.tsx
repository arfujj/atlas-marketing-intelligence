import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";

import { RoiDotPlot } from "@/components/charts";
import { Callout, Card, ErrorState, PageHeader, PageSkeleton, ProvenanceLine } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { channelLabel, methodLabel, money, num, pct, ratio } from "@/lib/format";
import type { MeasurementResponse, ScorecardResponse } from "@/lib/types";

const METHODS = ["last_click", "markov", "ols_naive", "bayes_default", "bayes_dag", "bayes_dag_calibrated"];

export default function Evidence(props: PageProps<"/halden/evidence">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content {...props} />
    </Suspense>
  );
}

async function Content({ searchParams }: PageProps<"/halden/evidence">) {
  await connection();
  const truth = (await searchParams).truth === "1";
  let meas: MeasurementResponse;
  let sc: ScorecardResponse | null = null;
  try {
    meas = await api<MeasurementResponse>("/halden/measurement", { reveal_truth: truth ? "true" : undefined });
    sc = await api<ScorecardResponse>("/halden/scorecard").catch(() => null);
  } catch (e) {
    return <ErrorState message={e instanceof ApiError ? e.message : "The ATLAS API is not reachable."} />;
  }

  const truthBy = Object.fromEntries((meas.truth ?? []).map((t) => [t.channel, t.true_roi_first_order_billed]));
  const channels = [...new Set(meas.estimates.map((e) => e.channel))];
  const rows = channels.map((c) => ({
    label: channelLabel(c),
    truth: truth ? truthBy[c] : undefined,
    points: meas.estimates
      .filter((e) => e.channel === c)
      .map((e) => ({ method: e.method, mean: e.roi_mean, lo: e.roi_p05, hi: e.roi_p95 })),
  }));
  const g = meas.geolift;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Evidence"
        lede="Six ways to estimate what a dollar of each channel returns, on the same data. Attribution assigns credit and states no uncertainty; regression and MMM estimate effects with intervals. Reveal the truth to see how far each one misses, and whether its interval admits it."
      >
        <Link
          href={truth ? "/halden/evidence" : "/halden/evidence?truth=1"}
          className={`rounded-md border px-3 py-1.5 text-sm font-medium ${
            truth ? "border-accent bg-accent text-white" : "border-line bg-surface text-ink"
          }`}
          aria-pressed={truth}
        >
          {truth ? "Hide truth" : "Reveal truth"}
        </Link>
      </PageHeader>

      <Card
        title="Incremental ROI by method and channel"
        subtitle="Incremental first-order revenue per billed dollar. Lines are 90% intervals; attribution reports a point only. Dashed line: 1.0, where a dollar returns a dollar of revenue."
        provenance={meas.provenance}
      >
        <RoiDotPlot rows={rows} methods={METHODS} methodNames={Object.fromEntries(METHODS.map((m) => [m, methodLabel(m)]))} format="ratio" reference={{ value: 1, label: "break-even revenue" }} />
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-ink-2">Table view</summary>
          <table className="data mt-2">
            <thead>
              <tr>
                <th>Channel</th>
                {METHODS.map((m) => (
                  <th key={m} className="num">
                    {methodLabel(m)}
                  </th>
                ))}
                {truth && <th className="num">True</th>}
              </tr>
            </thead>
            <tbody>
              {channels.map((c) => (
                <tr key={c}>
                  <td>{channelLabel(c)}</td>
                  {METHODS.map((m) => {
                    const e = meas.estimates.find((x) => x.channel === c && x.method === m);
                    return (
                      <td key={m} className="num">
                        {e ? ratio(e.roi_mean) : "—"}
                        {e?.roi_p05 != null && <span className="text-muted"> ({ratio(e.roi_p05)}–{ratio(e.roi_p95)})</span>}
                      </td>
                    );
                  })}
                  {truth && <td className="num font-medium">{ratio(truthBy[c])}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </Card>

      {truth && meas.graded && (
        <Card
          title="What each method's plan would really earn"
          subtitle={`Each method's estimates fed to the same optimizer, then the plan scored on the true response curves (${meas.graded.objective.replaceAll("_", " ")}, one quarter, $500K).`}
        >
          <table className="data">
            <thead>
              <tr>
                <th>Plan built from</th>
                <th className="num">True profit</th>
                <th className="num">Left on the table (regret)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(meas.graded.plans)
                .sort((a, b) => a[1].regret - b[1].regret)
                .map(([k, v]) => (
                  <tr key={k}>
                    <td>{methodLabel(k)}</td>
                    <td className="num">{money(v.true_value)}</td>
                    <td className="num">{money(v.regret)}</td>
                  </tr>
                ))}
              <tr>
                <td className="text-ink-2">True optimum</td>
                <td className="num">{money(meas.graded.true_value_optimum)}</td>
                <td className="num">$0</td>
              </tr>
            </tbody>
          </table>
          {meas.graded.plans.bayes_dag_calibrated?.regret > meas.graded.plans.bayes_dag?.regret &&
            g.true_delta_y != null && (
              <div className="mt-3">
                <Callout tone="warn">
                  In this world the calibrated model did worse than the uncalibrated one. Its geo-lift on{" "}
                  {channelLabel(g.channel)} measured {money(g.delta_y, { compact: true })} against a true{" "}
                  {money(g.true_delta_y, { compact: true })}, {ratio(Math.abs(g.delta_y - g.true_delta_y) / g.se)} standard
                  errors away, and calibration pulled the model towards it. One unlucky experiment can mislead; the
                  multi-world scorecard below shows how often that happens.
                </Callout>
              </div>
            )}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="MMM diagnostics" subtitle="Convergence on the full history; accuracy on a 13-week holdout the model never saw.">
          <table className="data">
            <thead>
              <tr>
                <th>Variant</th>
                <th className="num">R-hat max</th>
                <th className="num">ESS min</th>
                <th className="num">Divergences</th>
                <th className="num">Holdout MAPE</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(meas.diagnostics).map(([k, d]) => (
                <tr key={k}>
                  <td>{methodLabel(k)}</td>
                  <td className="num">{d.rhat_max.toFixed(3)}</td>
                  <td className="num">{num(d.ess_bulk_min)}</td>
                  <td className="num">{d.divergences}</td>
                  <td className="num">{pct(meas.holdout[k]?.holdout?.mape)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(() => {
            const h = Object.values(meas.holdout).find((x) => x.holdout)?.holdout;
            return h ? (
              <p className="mt-3 text-xs text-ink-2">
                Naive baselines on the same holdout: trailing 13-week mean {pct(h.baseline_mape_trailing13)}, seasonal naive{" "}
                {pct(h.baseline_mape_seasonal_naive)}. Fitting the holdout well does not make ROI estimates right: compare the
                plot above.
              </p>
            ) : null;
          })()}
        </Card>

        <Card title="Geo-lift experiment" subtitle={`${channelLabel(g.channel)} turned off for ${g.test_weeks} weeks in ${g.holdout.join(", ")}`}>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs text-ink-2">Measured revenue change</dt>
              <dd className="text-lg font-semibold">{money(g.delta_y)}</dd>
            </div>
            <div>
              <dt className="text-xs text-ink-2">90% confidence interval</dt>
              <dd className="text-lg font-semibold">
                {money(g.ci90[0], { compact: true })} to {money(g.ci90[1], { compact: true })}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-2">p-value</dt>
              <dd>{g.p_value.toFixed(2)}</dd>
            </div>
            {g.true_delta_y != null && (
              <div>
                <dt className="text-xs text-ink-2">True change</dt>
                <dd>{money(g.true_delta_y)}</dd>
              </div>
            )}
          </dl>
          <p className="mt-3 text-xs text-ink-2">
            Standard error from placebo windows in the pre-period. A non-significant result is not evidence of no effect: the
            interval includes losses several times the model&apos;s prediction.
          </p>
        </Card>
      </div>

      {sc && <Scorecard sc={sc} />}
    </div>
  );
}

function Scorecard({ sc }: { sc: ScorecardResponse }) {
  const methods = [...sc.roi_by_method].sort((a, b) => a.mean_abs_error - b.mean_abs_error);
  const plans = [...sc.regret_by_plan].sort((a, b) => a.mean_regret - b.mean_regret);
  return (
    <Card
      title={`Graded against the truth in ${sc.n_worlds} randomized worlds`}
      subtitle={`Each world redraws every channel's true ROI, carryover and saturation, in four regimes (${Object.entries(sc.regimes)
        .map(([k, v]) => `${v} ${k.replaceAll("_", " ")}`)
        .join(", ")}). Failures are kept.`}
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold text-ink-2">ROI error by method</h3>
          <table className="data">
            <thead>
              <tr>
                <th>Method</th>
                <th className="num">Mean |error|</th>
                <th className="num">Median</th>
                <th className="num">90% interval covers truth</th>
              </tr>
            </thead>
            <tbody>
              {methods.map((m) => (
                <tr key={m.method}>
                  <td>{methodLabel(m.method)}</td>
                  <td className="num">{ratio(m.mean_abs_error, 2)}</td>
                  <td className="num">{ratio(m.median_abs_error, 2)}</td>
                  <td className="num">{m.coverage90 == null ? "no interval" : pct(m.coverage90, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold text-ink-2">Profit left on the table by the plan each method recommends</h3>
          <table className="data">
            <thead>
              <tr>
                <th>Plan</th>
                <th className="num">Mean regret</th>
                <th className="num">P90</th>
                <th className="num">Worse than current</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p) => (
                <tr key={p.plan}>
                  <td>{methodLabel(p.plan)}</td>
                  <td className="num">{money(p.mean_regret, { compact: true })}</td>
                  <td className="num">{money(p.p90_regret, { compact: true })}</td>
                  <td className="num">{pct(p.worse_than_current, 0)} of worlds</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="mt-4 grid gap-3 text-xs text-ink-2 md:grid-cols-3">
        <p>
          Calibrating with one geo-lift cut the tested channel&apos;s ROI error from{" "}
          {ratio(sc.calibration_effect_on_tested_channel.mean_error_before, 2)} to{" "}
          {ratio(sc.calibration_effect_on_tested_channel.mean_error_after, 2)} on average, improving it in{" "}
          {pct(sc.calibration_effect_on_tested_channel.share_improved, 0)} of worlds.
        </p>
        <p>
          Geo-lift 90% intervals covered the true effect in {pct(sc.geolift.coverage90, 0)} of worlds. {sc.failures.length} world
          {sc.failures.length === 1 ? "" : "s"} where the calibrated plan was worse than doing nothing.
        </p>
        <p>
          Sampler: {sc.config.chains} chains × {sc.config.draws} draws. Converged fits (R-hat &lt; 1.01, no divergences):{" "}
          {sc.convergence.map((c) => `${methodLabel(c.variant)} ${pct(c.converged, 0)}`).join("; ")}.
        </p>
      </div>
      <div className="mt-3">
        <ProvenanceLine p={sc.provenance} />
      </div>
    </Card>
  );
}
