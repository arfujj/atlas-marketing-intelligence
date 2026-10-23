import { connection } from "next/server";
import { Suspense } from "react";

import { TimeSeries } from "@/components/charts";
import { Callout, Card, ErrorState, PageHeader, PageSkeleton, ProvenanceLine, StatTile, StatusTag } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { money, num, pct } from "@/lib/format";
import type { Ga4AnomaliesResponse, RowsResponse } from "@/lib/types";

type Daily = {
  date: string;
  sessions: number;
  purchase_events: number;
  transactions: number;
  revenue: number;
  unidentified_purchase_events: number;
  purchase_sessions: number;
};
type Funnel = Record<string, number | string> & { device_category: string };
type Rfm = { rfm_segment: string; monetary: number };
type Dq = { check_id: string; description: string; value: number; reference_value: number | null; decision: string };

const STEPS = [
  ["sessions", "Sessions"],
  ["view_item_sessions", "Viewed an item"],
  ["add_to_cart_sessions", "Added to cart"],
  ["begin_checkout_sessions", "Began checkout"],
  ["purchase_sessions", "Purchased"],
] as const;

export default function Ga4() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <Content />
    </Suspense>
  );
}

async function Content() {
  await connection();
  let daily: RowsResponse<Daily>, funnel: RowsResponse<Funnel>, rfm: RowsResponse<Rfm>, dq: RowsResponse<Dq>, an: Ga4AnomaliesResponse;
  try {
    [daily, funnel, rfm, dq, an] = await Promise.all([
      api<RowsResponse<Daily>>("/ga4/daily"),
      api<RowsResponse<Funnel>>("/ga4/funnel"),
      api<RowsResponse<Rfm>>("/ga4/rfm"),
      api<RowsResponse<Dq>>("/ga4/data_quality"),
      api<Ga4AnomaliesResponse>("/ga4-anomalies"),
    ]);
  } catch (e) {
    return <ErrorState message={e instanceof ApiError ? e.message : "The ATLAS API is not reachable."} />;
  }
  const d = daily.rows;
  const sum = (k: keyof Daily) => d.reduce((s, r) => s + Number(r[k] ?? 0), 0);
  const series = d.map((r) => ({ date: r.date.slice(0, 10), purchase_events: r.purchase_events, transactions: r.transactions }));
  const lj = an.late_january;

  // Funnel by device: sum the mart's steps per device.
  const devices = new Map<string, Record<string, number>>();
  for (const r of funnel.rows) {
    const acc = devices.get(r.device_category) ?? {};
    for (const [k] of STEPS) acc[k] = (acc[k] ?? 0) + Number(r[k] ?? 0);
    devices.set(r.device_category, acc);
  }
  const deviceRows = [...devices.entries()].sort((a, b) => b[1].sessions - a[1].sessions);

  const segs = new Map<string, { buyers: number; revenue: number }>();
  for (const r of rfm.rows) {
    const s = segs.get(r.rfm_segment) ?? { buyers: 0, revenue: 0 };
    s.buyers += 1;
    s.revenue += r.monetary;
    segs.set(r.rfm_segment, s);
  }
  const totalRfmRev = [...segs.values()].reduce((s, x) => s + x.revenue, 0);
  const segRows = [...segs.entries()].sort((a, b) => b[1].revenue - a[1].revenue);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Google Merchandise Store"
        lede="Real (obfuscated) GA4 export, 1 Nov 2020 to 31 Jan 2021. No spend or cost data exists here, so there is no ROAS, CAC or MMM in this workspace."
      >
        <ProvenanceLine p={daily.provenance} />
      </PageHeader>

      <Callout>
        Acquisition fields in this export describe the user&apos;s <strong className="font-medium text-ink">first</strong> visit, not the session,
        so every channel column is labelled &ldquo;first-user&rdquo;. Revenue is deduplicated by transaction id; purchase events without a usable id
        are counted separately, not added in.
      </Callout>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Sessions" value={num(sum("sessions"))} evidence="Observed" />
        <StatTile label="Transactions (deduplicated)" value={num(sum("transactions"))} evidence="Observed" />
        <StatTile label="Revenue (deduplicated)" value={money(sum("revenue"))} evidence="Observed" sub="headline figure; see data quality" />
        <StatTile
          label="Session conversion rate"
          value={pct(sum("purchase_sessions") / sum("sessions"), 2)}
          evidence="Observed"
          sub="sessions with a purchase event"
        />
      </div>

      <Card
        title="Purchase events vs identified transactions"
        subtitle="Daily. The lines separate twice, 2–11 November and from 26 January: purchases keep firing, but without usable transaction ids."
        provenance={daily.provenance}
      >
        <TimeSeries
          data={series}
          x="date"
          format="num"
          marker={{ x: lj.start, label: "26 Jan" }}
          series={[
            { key: "purchase_events", name: "Purchase events" },
            { key: "transactions", name: "Identified transactions" },
          ]}
        />
      </Card>

      <Card title="Investigation: did demand fall in late January?" provenance={an.provenance}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <StatusTag status={lj.evidence_status} />
          <span className="text-sm">{lj.conclusion}</span>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Indicator</th>
              <th className="num">14 days before</th>
              <th className="num">From 26 Jan</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(lj.ratios).map(([k, v]) => (
              <tr key={k}>
                <td>{k.replaceAll("_", " ")}</td>
                <td className="num">{k.includes("share") ? pct(v.before) : num(v.before, 2)}</td>
                <td className="num">{k.includes("share") ? pct(v.after) : num(v.after, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-ink-2">{lj.status_note}</p>
        <p className="mt-1 text-xs text-ink-2">
          <span className="font-medium text-ink">Next checks:</span> {lj.follow_ups.join(" · ")}
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Funnel by device" subtitle="Share of sessions reaching each step, whole period.">
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th>Device</th>
                  {STEPS.map(([k, l]) => (
                    <th key={k} className="num">
                      {l}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {deviceRows.map(([dev, v]) => (
                  <tr key={dev}>
                    <td>{dev}</td>
                    {STEPS.map(([k]) => (
                      <td key={k} className="num">
                        {k === "sessions" ? num(v[k]) : pct(v[k] / v.sessions, 2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Buyer segments (RFM, 92-day window)" subtitle="Rule-based segments; 88% of buyers purchase once, so frequency is bucketed, not scored.">
          <table className="data">
            <thead>
              <tr>
                <th>Segment</th>
                <th className="num">Buyers</th>
                <th className="num">Revenue</th>
                <th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {segRows.map(([s, v]) => (
                <tr key={s}>
                  <td>{s}</td>
                  <td className="num">{num(v.buyers)}</td>
                  <td className="num">{money(v.revenue, { compact: true })}</td>
                  <td className="num">{pct(v.revenue / totalRfmRev, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="Data quality decisions" subtitle="Every number above depends on these checks; each one is asserted by a dbt test.">
        <div className="overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>Check</th>
                <th className="num">Value</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {dq.rows.map((r) => (
                <tr key={r.check_id}>
                  <td>{r.description}</td>
                  <td className="num">{num(r.value)}</td>
                  <td className="text-ink-2">{r.decision}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
