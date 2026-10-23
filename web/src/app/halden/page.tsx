import { connection } from "next/server";
import { Suspense } from "react";

import { TimeSeries } from "@/components/charts";
import { Card, ErrorState, EvidenceBadge, PageHeader, PageSkeleton, StatTile } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { channelLabel, formatMetric, methodLabel, money, pct, ratio } from "@/lib/format";
import type { MeasurementResponse, MetricResponse } from "@/lib/types";

const KPIS = ["revenue", "contribution_profit", "new_customers", "spend", "mer", "blended_cac"] as const;
const UP_IS_GOOD: Record<string, boolean> = { blended_cac: false, spend: true };

type SP = Record<string, string | string[] | undefined>;

function addWeeks(d: string, n: number) {
  const t = new Date(`${d}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + 7 * n);
  return t.toISOString().slice(0, 10);
}

function str(v: string | string[] | undefined) {
  return Array.isArray(v) ? v[0] : v;
}

export default function Performance(props: PageProps<"/halden">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content {...props} />
    </Suspense>
  );
}

async function Content({ searchParams }: PageProps<"/halden">) {
  await connection();
  const sp: SP = await searchParams;
  try {
    return await render(sp);
  } catch (e) {
    return <ErrorState message={e instanceof ApiError ? e.message : "The ATLAS API is not reachable. Run `make api`."} />;
  }
}

async function render(sp: SP) {
  const geo = str(sp.geo) || undefined;
  const allWeeks = await api<MetricResponse>("/halden/metrics/revenue", { group_by: "week_start" });
  const weeks = allWeeks.rows.map((r) => String(r.week_start).slice(0, 10));
  const last = weeks[weeks.length - 1];
  const end = str(sp.end) || last;
  const start = str(sp.start) || addWeeks(end, -12);
  const nWeeks = Math.round((Date.parse(end) - Date.parse(start)) / (7 * 864e5)) + 1;
  const prevEnd = addWeeks(start, -1);
  const prevStart = addWeeks(prevEnd, -(nWeeks - 1));
  const f = { geo };

  const [regions, kpiNow, kpiPrev, weeklyRev, weeklySpend, chSpend, chRoas, meas] = await Promise.all([
    api<MetricResponse>("/halden/metrics/revenue", { group_by: "geo" }),
    Promise.all(KPIS.map((k) => api<MetricResponse>(`/halden/metrics/${k}`, { ...f, start, end }))),
    Promise.all(KPIS.map((k) => api<MetricResponse>(`/halden/metrics/${k}`, { ...f, start: prevStart, end: prevEnd }))),
    api<MetricResponse>("/halden/metrics/revenue", { ...f, group_by: "week_start" }),
    api<MetricResponse>("/halden/metrics/spend", { ...f, group_by: "week_start" }),
    api<MetricResponse>("/halden/metrics/spend", { ...f, start, end, group_by: "channel" }),
    api<MetricResponse>("/halden/metrics/last_click_roas", { ...f, start, end, group_by: "channel" }),
    api<MeasurementResponse>("/halden/measurement"),
  ]);

  const series = weeklyRev.rows.map((r, i) => ({
    week: String(r.week_start).slice(0, 10),
    revenue: r.value,
    spend: weeklySpend.rows[i]?.value ?? null,
  }));
  const inWindow = series.filter((r) => r.week >= start && r.week <= end);

  const mmm = meas.recommended_variant;
  const roas = Object.fromEntries(chRoas.rows.map((r) => [r.channel, r.value]));
  const est = (c: string, m: string) => meas.estimates.find((e) => e.channel === c && e.method === m);
  const channels = chSpend.rows
    .filter((r) => r.channel)
    .map((r) => ({ channel: String(r.channel), spend: r.value ?? 0 }))
    .sort((a, b) => b.spend - a.spend);
  const geoLift = meas.geolift;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Performance"
        lede={
          <>
            {start} to {end} ({nWeeks} weeks){geo ? `, region ${geo}` : ", all regions"}, compared with the previous{" "}
            {nWeeks} weeks. Every tile states its definition and evidence type; hover a label for the formula.
          </>
        }
      >
        <form className="flex flex-wrap items-end gap-2 text-xs" method="get">
          <label className="flex flex-col gap-1 text-ink-2">
            From
            <input type="date" name="start" defaultValue={start} min={weeks[0]} max={last} className="rounded border border-line bg-surface px-2 py-1 text-ink" />
          </label>
          <label className="flex flex-col gap-1 text-ink-2">
            To
            <input type="date" name="end" defaultValue={end} min={weeks[0]} max={last} className="rounded border border-line bg-surface px-2 py-1 text-ink" />
          </label>
          <label className="flex flex-col gap-1 text-ink-2">
            Region
            <select name="geo" defaultValue={geo ?? ""} className="rounded border border-line bg-surface px-2 py-1 text-ink">
              <option value="">All regions</option>
              {regions.rows.map((r) => (
                <option key={String(r.geo)} value={String(r.geo)}>
                  {String(r.geo)}
                </option>
              ))}
            </select>
          </label>
          <button className="rounded bg-accent px-3 py-1.5 font-medium text-white">Apply</button>
        </form>
      </PageHeader>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {kpiNow.map((m, i) => {
          const v = m.rows[0]?.value ?? null;
          const p = kpiPrev[i].rows[0]?.value ?? null;
          const d = v != null && p ? v / p - 1 : null;
          const good = d == null ? null : (UP_IS_GOOD[m.metric.name] ?? true) ? d >= 0 : d <= 0;
          return (
            <StatTile
              key={m.metric.name}
              label={m.metric.label}
              value={formatMetric(v, m.metric.format)}
              evidence={m.provenance.evidence_type}
              definition={m.metric.definition}
              sub={
                d == null ? (
                  "no comparison"
                ) : (
                  <span>
                    <span className={m.metric.name === "spend" ? "text-ink-2" : good ? "text-good" : "text-bad"}>
                      {d >= 0 ? "▲" : "▼"} {pct(d, 1, true)}
                    </span>{" "}
                    vs previous {nWeeks} wk
                  </span>
                )
              }
            />
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Weekly revenue" subtitle="Recorded first-order plus repeat revenue" provenance={weeklyRev.provenance}>
          <TimeSeries data={series} x="week" series={[{ key: "revenue", name: "Revenue" }]} format="money" marker={{ x: start, label: "window" }} />
        </Card>
        <Card title="Weekly media spend" subtitle="Billed spend, all paid channels" provenance={weeklySpend.provenance}>
          <TimeSeries data={series} x="week" series={[{ key: "spend", name: "Spend", color: "var(--series-2)" }]} format="money" marker={{ x: start, label: "window" }} />
        </Card>
      </div>

      <Card
        title="Channels: what each method says a dollar returns"
        subtitle="The gap between these columns is why ATLAS exists. Last-click is computed for the selected window and region; model and experiment columns use the full history and all regions."
      >
        <div className="overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Channel</th>
                <th className="num">Spend (window)</th>
                <th className="num">
                  Last-click ROAS <EvidenceBadge type="Attributed" />
                </th>
                <th className="num">
                  MMM incremental ROI, 90% interval <EvidenceBadge type="Modeled" />
                </th>
                <th className="num">
                  Geo-lift <EvidenceBadge type="Experimental" />
                </th>
              </tr>
            </thead>
            <tbody>
              {channels.map((c) => {
                const e = est(c.channel, mmm);
                return (
                  <tr key={c.channel}>
                    <td>{channelLabel(c.channel)}</td>
                    <td className="num">{money(c.spend, { compact: true })}</td>
                    <td className="num">{ratio(roas[c.channel])}</td>
                    <td className="num">
                      {e ? (
                        <>
                          {ratio(e.roi_mean)} <span className="text-muted">({ratio(e.roi_p05)} – {ratio(e.roi_p95)})</span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="num text-ink-2">
                      {geoLift.channel === c.channel
                        ? `tested: Δ revenue ${money(geoLift.delta_y, { compact: true })} (90% CI ${money(geoLift.ci90[0], { compact: true })} to ${money(geoLift.ci90[1], { compact: true })})`
                        : "not tested"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-ink-2">
          ROI = incremental first-order revenue per dollar of billed spend. MMM: {methodLabel(meas.recommended_variant)}, run{" "}
          <span className="font-mono">{meas.mmm_runs[mmm]}</span>. {inWindow.length} weeks in window.
        </p>
      </Card>
    </div>
  );
}
