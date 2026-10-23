import { connection } from "next/server";
import { Suspense } from "react";

import { Tornado } from "@/components/charts";
import { Callout, Card, ErrorState, PageHeader, PageSkeleton, ProvenanceLine } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { channelLabel, money, pct } from "@/lib/format";
import type { ExperimentsResponse, PlanResponse } from "@/lib/types";

import { Planner } from "./planner";

export default function Decision() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content />
    </Suspense>
  );
}

async function Content() {
  await connection();
  let plan: PlanResponse;
  let exp: ExperimentsResponse;
  try {
    [plan, exp] = await Promise.all([api<PlanResponse>("/halden/plan"), api<ExperimentsResponse>("/halden/experiments")]);
  } catch (e) {
    return <ErrorState message={e instanceof ApiError ? e.message : "The ATLAS API is not reachable."} />;
  }
  const initial = plan.optimizer[plan.objective];
  // Rank by net value (information value minus expected cost), not information value alone:
  // pausing an over-invested channel can have negative cost, which makes a test worth running.
  const ranked = [...exp.next_experiments].sort((a, b) => b.net_value - a.net_value);
  const best = ranked[0];
  const worthIt = exp.next_experiments.filter((x) => x.net_value > 0);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Decision: next quarter's $500K"
        lede="The allocation that maximises expected profit across the calibrated MMM's posterior, within per-channel limits. Ranges are percentiles across posterior draws, not hand-picked scenarios."
      >
        <ProvenanceLine p={plan.provenance} />
      </PageHeader>

      <Planner initial={initial} />

      <div className="grid gap-4 lg:grid-cols-5">
        <Card
          className="lg:col-span-3"
          title="Which assumptions move the answer"
          subtitle="Change in expected 52-week profit of the recommended plan when each input moves to its low or high value. Model choice is the biggest lever."
        >
          <Tornado
            format="money"
            rows={plan.tornado.map((t) => ({ label: t.assumption, low: t.low_delta, high: t.high_delta }))}
          />
          <table className="data mt-3">
            <thead>
              <tr>
                <th>Assumption</th>
                <th className="num">Budget re-allocated (low / high)</th>
              </tr>
            </thead>
            <tbody>
              {plan.tornado.map((t) => (
                <tr key={t.assumption}>
                  <td>{t.assumption}</td>
                  <td className="num">
                    {money(t.low_budget_moved, { compact: true })} / {money(t.high_budget_moved, { compact: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-ink-2">
            An assumption can swing expected profit a lot without changing which plan is best. &ldquo;Budget re-allocated&rdquo; shows whether the recommendation itself flips.
          </p>
        </Card>

        <Card
          className="lg:col-span-2"
          title="Next best experiment"
          subtitle="Ranked by net value: how much better the decision gets if we test first (expected value of sample information), minus the test's expected cost."
          provenance={exp.provenance}
        >
          {best && (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div className="col-span-2">
                <dt className="text-xs text-ink-2">Highest-value test</dt>
                <dd className="text-lg font-semibold">
                  {channelLabel(best.channel)} go-dark, {best.n_weeks} weeks
                </dd>
                <dd className="text-xs text-ink-2">{best.holdout_label}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-2">Value of information</dt>
                <dd className="font-medium">{money(best.evsi)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-2">Expected test cost</dt>
                <dd className="font-medium">{money(best.expected_test_cost)}</dd>
                {best.expected_test_cost < 0 && (
                  <dd className="text-xs text-ink-2">Negative: pausing saves more spend than the revenue it loses.</dd>
                )}
              </div>
              <div>
                <dt className="text-xs text-ink-2">Power at predicted effect</dt>
                <dd className="font-medium">{pct(best.power_at_predicted_effect, 0)}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-2">Net value</dt>
                <dd className={`font-medium ${best.net_value < 0 ? "text-bad" : "text-good"}`}>{money(best.net_value)}</dd>
              </div>
            </dl>
          )}
          <div className="mt-4">
            {worthIt.length === 0 ? (
              <Callout tone="warn">
                No candidate test pays for itself on this decision. Perfect information would be worth at most{" "}
                {money(exp.evpi, { compact: true })}, and every test&apos;s lost revenue costs more than the value it adds. The honest
                recommendation is to act on the current plan and revisit when the budget or uncertainty grows.
              </Callout>
            ) : (
              <Callout>
                {worthIt.length} of {ranked.length} candidate tests have positive net value. Their value comes mostly from the spend saved
                while the channel is paused; the information itself is worth at most {money(exp.evpi, { compact: true })} (perfect
                information), and power is low, so read a null result as &ldquo;inconclusive&rdquo;, not &ldquo;no effect&rdquo;.
              </Callout>
            )}
          </div>
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-ink-2">All candidates</summary>
            <table className="data mt-2">
              <thead>
                <tr>
                  <th>Test</th>
                  <th className="num">Value</th>
                  <th className="num">Cost</th>
                  <th className="num">Power</th>
                  <th className="num">Net</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((x, i) => (
                  <tr key={i}>
                    <td>
                      {channelLabel(x.channel)}, {x.n_weeks} wk, {x.holdout_label}
                    </td>
                    <td className="num">{money(x.evsi, { compact: true })}</td>
                    <td className="num">{money(x.expected_test_cost, { compact: true })}</td>
                    <td className="num">{pct(x.power_at_predicted_effect, 0)}</td>
                    <td className="num">{money(x.net_value, { compact: true })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </Card>
      </div>
    </div>
  );
}
