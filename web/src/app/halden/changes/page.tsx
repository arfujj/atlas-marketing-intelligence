import { connection } from "next/server";
import { Suspense } from "react";

import { TimeSeries } from "@/components/charts";
import { Card, ErrorState, PageHeader, PageSkeleton, StatusTag } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { pct } from "@/lib/format";
import type { HaldenAnomaliesResponse } from "@/lib/types";

export default function Changes() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content />
    </Suspense>
  );
}

function seriesLabel(key: string) {
  const [level, entity, metric] = key.split(":");
  const m = (metric ?? entity).replaceAll("_", " ");
  if (level === "national") return `National ${m}`;
  if (level === "region") return `${entity} ${m}`;
  return `${entity.replaceAll("_", " ")} ${m}`;
}

async function Content() {
  await connection();
  let a: HaldenAnomaliesResponse;
  try {
    a = await api<HaldenAnomaliesResponse>("/halden/anomalies");
  } catch (e) {
    return <ErrorState message={e instanceof ApiError ? e.message : "The ATLAS API is not reachable."} />;
  }
  const flagged = new Set(a.weeks.filter((w) => Object.keys(w.flagged_series).some((k) => k === "national:revenue")).map((w) => w.week));
  const rev = a.national_series
    .filter((r) => r.metric === "revenue")
    .map((r) => {
      const week = r.period.slice(0, 10);
      return { week, actual: r.actual, expected: r.expected, flag: flagged.has(week) ? r.actual : null };
    });
  const explained = [...a.weeks].filter((w) => w.hypotheses.length > 0).reverse();
  const unexplained = a.weeks.filter((w) => w.hypotheses.length === 0 && Object.keys(w.flagged_series).length > 0);
  const ev = a.evaluation;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Changes"
        lede="What moved, where, and the most likely reason. Every week is scored against a robust seasonal baseline fitted only on earlier weeks; a decomposition says where a change sits, never by itself why."
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card p-4">
          <div className="text-xs text-ink-2">Detector recall, held-out worlds</div>
          <div className="text-2xl font-semibold">{pct(ev.recall, 0)}</div>
          <div className="text-xs text-ink-2">of {ev.incidents} injected incidents found</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-ink-2">Precision</div>
          <div className="text-2xl font-semibold">{pct(ev.precision, 0)}</div>
          <div className="text-xs text-ink-2">of {ev.alert_events} alerts matched a real incident</div>
        </div>
        <div className="card p-4">
          <div className="text-xs text-ink-2">Thresholds</div>
          <div className="text-sm">
            {Object.entries(a.thresholds)
              .map(([k, v]) => `${k} |z| ≥ ${v.toFixed(1)}`)
              .join(" · ")}
          </div>
          <div className="text-xs text-ink-2">calibrated for {pct(a.fpr_target)} false alarms per series-week on incident-free worlds</div>
        </div>
      </div>

      <Card title="National revenue: actual vs expected" subtitle="Expected = one-step-ahead robust baseline (trend, seasonality, promotions). Red dots: weeks flagged on revenue." provenance={a.provenance}>
        <TimeSeries
          data={rev}
          x="week"
          format="money"
          flagKey="flag"
          series={[
            { key: "actual", name: "Actual" },
            { key: "expected", name: "Expected", color: "var(--muted)", dashed: true },
          ]}
        />
      </Card>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Explained changes, most recent first</h2>
        {explained.map((w) => (
          <article key={w.week} className="card p-4">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-medium">Week of {w.week}</h3>
              <span className="text-xs text-muted">
                {Object.entries(w.flagged_series)
                  .slice(0, 6)
                  .map(([k, z]) => `${seriesLabel(k)} z ${z.toFixed(1)}`)
                  .join(" · ")}
                {Object.keys(w.flagged_series).length > 6 && ` · +${Object.keys(w.flagged_series).length - 6} more`}
              </span>
            </div>
            <ol className="flex flex-col gap-3">
              {w.hypotheses.map((h, i) => (
                <li key={i} className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusTag status={h.status} />
                    <span className="text-sm">{h.title}</span>
                  </div>
                  <ul className="ml-1 list-inside list-disc text-xs text-ink-2">
                    {h.evidence.map((e, j) => (
                      <li key={j}>{e}</li>
                    ))}
                  </ul>
                  <p className="text-xs text-ink-2">
                    <span className="font-medium text-ink">Next checks:</span> {h.follow_ups.join(" · ")}
                  </p>
                </li>
              ))}
            </ol>
          </article>
        ))}
        {unexplained.length > 0 && (
          <details className="card p-4 text-xs">
            <summary className="cursor-pointer text-ink-2">
              {unexplained.length} flagged week{unexplained.length > 1 ? "s" : ""} that no rule explains (at this threshold about 1 in 200 series-weeks alerts by chance; watch for recurrence)
            </summary>
            <ul className="mt-2 flex flex-col gap-1">
              {unexplained.map((w) => (
                <li key={w.week}>
                  {w.week}:{" "}
                  {Object.entries(w.flagged_series)
                    .map(([k, z]) => `${seriesLabel(k)} z ${z.toFixed(1)}`)
                    .join(" · ")}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
