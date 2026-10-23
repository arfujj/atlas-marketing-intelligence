"use client";

import { useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { money, num, pct, ratio } from "@/lib/format";

export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];

/** Formats are named, not passed as functions: these components are client components and
 *  receive props from server components, which cannot serialise functions. */
export type FmtName = "money" | "ratio" | "pct" | "pct2" | "num";
type Fmt = (v: number) => string;
const FORMATS: Record<FmtName, Fmt> = {
  money: (v) => money(v, { compact: true }),
  ratio: (v) => ratio(v),
  pct: (v) => pct(v, 0),
  pct2: (v) => pct(v, 2),
  num: (v) => num(v),
};
const axisTick = { fill: "var(--muted)", fontSize: 11 };

function dateTicks(data: Record<string, unknown>[], x: string) {
  const first = Date.parse(String(data[0]?.[x] ?? ""));
  const last = Date.parse(String(data[data.length - 1]?.[x] ?? ""));
  // Under ~7 months of data, label days ("Nov 5"); otherwise months ("Nov 24").
  const daily = last - first < 200 * 864e5;
  return (s: string) =>
    new Date(s).toLocaleDateString("en-US", daily ? { month: "short", day: "numeric", timeZone: "UTC" } : { month: "short", year: "2-digit", timeZone: "UTC" });
}

function TooltipBox({
  active,
  payload,
  label,
  fmt,
  names,
}: {
  active?: boolean;
  payload?: Array<{ dataKey: string; value: number | [number, number]; color?: string }>;
  label?: string;
  fmt: Fmt;
  names: Record<string, string>;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="card px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 font-medium">
        {new Date(label ?? "").toLocaleDateString("en-US", { dateStyle: "medium", timeZone: "UTC" })}
      </div>
      {payload
        .filter((p) => names[p.dataKey])
        .map((p) => (
          <div key={p.dataKey} className="flex items-center justify-between gap-4 tnum">
            <span className="flex items-center gap-1.5 text-ink-2">
              <span aria-hidden className="inline-block h-0.5 w-3" style={{ background: p.color }} />
              {names[p.dataKey]}
            </span>
            <span>{Array.isArray(p.value) ? `${fmt(p.value[0])} – ${fmt(p.value[1])}` : fmt(p.value)}</span>
          </div>
        ))}
    </div>
  );
}

export interface SeriesDef {
  key: string;
  name: string;
  color?: string;
  dashed?: boolean;
}

/** Time series on one y-axis. Optional `band` = [lowKey, highKey] drawn as a wash, and
 *  `flags` = x values to mark with a dot on the first series. */
export function TimeSeries({
  data,
  x,
  series,
  format,
  height = 240,
  band,
  flagKey,
  marker,
}: {
  data: Record<string, unknown>[];
  x: string;
  series: SeriesDef[];
  format: FmtName;
  height?: number;
  band?: { key: string; name: string };
  flagKey?: string;
  marker?: { x: string; label: string };
}) {
  const fmt = FORMATS[format];
  const names = Object.fromEntries(series.map((s) => [s.key, s.name]));
  if (band) names[band.key] = band.name;
  return (
    <div>
      {series.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
          {series.map((s, i) => (
            <span key={s.key} className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block w-4"
                style={{ borderTop: `2px ${s.dashed ? "dashed" : "solid"} ${s.color ?? SERIES[i]}` }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey={x}
            tickFormatter={dateTicks(data, x)}
            tick={axisTick}
            stroke="var(--axis)"
            minTickGap={40}
            tickLine={false}
          />
          <YAxis tickFormatter={fmt} tick={axisTick} stroke="none" width={64} />
          <Tooltip
            content={<TooltipBox fmt={fmt} names={names} />}
            cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
          />
          {band && (
            <Area
              dataKey={band.key}
              stroke="none"
              fill="var(--muted)"
              fillOpacity={0.14}
              isAnimationActive={false}
              activeDot={false}
            />
          )}
          {marker && (
            <ReferenceLine
              x={marker.x}
              stroke="var(--axis)"
              label={{ value: marker.label, position: "insideTopLeft", fill: "var(--ink-2)", fontSize: 11 }}
            />
          )}
          {series.map((s, i) => (
            <Line
              key={s.key}
              dataKey={s.key}
              stroke={s.color ?? SERIES[i]}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "4 3" : undefined}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          ))}
          {flagKey && (
            <Scatter dataKey={flagKey} fill="var(--status-critical)" isAnimationActive={false} shape="circle" />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface DotRow {
  label: string;
  points: Array<{ method: string; mean: number; lo?: number | null; hi?: number | null }>;
  truth?: number;
}

/** ROI estimates by method per channel: a dot per method with its 90% interval, and the
 *  true value as a vertical tick when revealed. Rows are channels. */
export function RoiDotPlot({
  rows,
  methods,
  methodNames,
  format,
  reference,
}: {
  rows: DotRow[];
  methods: string[];
  methodNames: Record<string, string>;
  format: FmtName;
  reference?: { value: number; label: string };
}) {
  const fmt = FORMATS[format];
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const all = rows.flatMap((r) => [
    ...r.points.flatMap((p) => [p.mean, p.lo ?? p.mean, p.hi ?? p.mean]),
    ...(r.truth != null ? [r.truth] : []),
  ]);
  const max = Math.max(1, ...all.filter(Number.isFinite));
  const min = Math.min(0, ...all.filter(Number.isFinite));
  const W = 720;
  const left = 150;
  const right = 24;
  const rowH = 18 + methods.length * 12;
  const top = 8;
  const H = top + rows.length * rowH + 28;
  const xs = (v: number) => left + ((v - min) / (max - min)) * (W - left - right);
  const step = niceStep((max - min) / 6);
  const ticks: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(+t.toFixed(6));

  return (
    <div className="relative">
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
        {methods.map((m, i) => (
          <span key={m} className="flex items-center gap-1.5">
            <svg width="10" height="10" aria-hidden>
              <circle cx="5" cy="5" r="4" fill={SERIES[i]} />
            </svg>
            {methodNames[m] ?? m}
          </span>
        ))}
        {rows.some((r) => r.truth != null) && (
          <span className="flex items-center gap-1.5">
            <svg width="10" height="12" aria-hidden>
              <line x1="5" x2="5" y1="0" y2="12" stroke="var(--ink)" strokeWidth="2" />
            </svg>
            True ROI
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="ROI estimates by method and channel">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={xs(t)} x2={xs(t)} y1={top} y2={H - 24} stroke="var(--grid)" />
            <text x={xs(t)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--muted)">
              {fmt(t)}
            </text>
          </g>
        ))}
        {reference && (
          <g>
            <line x1={xs(reference.value)} x2={xs(reference.value)} y1={top} y2={H - 24} stroke="var(--axis)" strokeDasharray="3 3" />
          </g>
        )}
        {rows.map((r, ri) => {
          const y0 = top + ri * rowH;
          return (
            <g key={r.label}>
              <text x={0} y={y0 + rowH / 2 + 4} fontSize="12" fill="var(--ink)">
                {r.label}
              </text>
              {ri > 0 && <line x1={0} x2={W - right} y1={y0} y2={y0} stroke="var(--grid)" />}
              {r.truth != null && (
                <line x1={xs(r.truth)} x2={xs(r.truth)} y1={y0 + 4} y2={y0 + rowH - 4} stroke="var(--ink)" strokeWidth={2} />
              )}
              {methods.map((m, mi) => {
                const p = r.points.find((q) => q.method === m);
                if (!p || !Number.isFinite(p.mean)) return null;
                const y = y0 + 12 + mi * 12;
                const text = `${r.label} · ${methodNames[m] ?? m}: ${fmt(p.mean)}${
                  p.lo != null && p.hi != null ? ` (90% interval ${fmt(p.lo)} – ${fmt(p.hi)})` : ""
                }${r.truth != null ? ` · true ${fmt(r.truth)}` : ""}`;
                return (
                  <g
                    key={m}
                    onMouseEnter={() => setHover({ x: xs(p.mean) / W, y: y / H, text })}
                    onMouseLeave={() => setHover(null)}
                  >
                    {p.lo != null && p.hi != null && (
                      <line x1={xs(p.lo)} x2={xs(p.hi)} y1={y} y2={y} stroke={SERIES[mi]} strokeWidth={2} strokeLinecap="round" opacity={0.55} />
                    )}
                    <circle cx={xs(p.mean)} cy={y} r={4.5} fill={SERIES[mi]} stroke="var(--surface)" strokeWidth={2} />
                    <circle cx={xs(p.mean)} cy={y} r={10} fill="transparent" />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div
          className="card pointer-events-none absolute z-10 max-w-xs px-2.5 py-1.5 text-xs shadow-sm"
          style={{ left: `${Math.min(hover.x * 100, 70)}%`, top: `calc(${hover.y * 100}% + 18px)` }}
        >
          {hover.text}
        </div>
      )}
    </div>
  );
}

function niceStep(raw: number) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

/** Horizontal diverging bars for a sensitivity tornado (one axis, zero baseline). */
export function Tornado({
  rows,
  format,
}: {
  rows: Array<{ label: string; low: number; high: number }>;
  format: FmtName;
}) {
  const fmt = FORMATS[format];
  const ext = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.low), Math.abs(r.high)]));
  const W = 720;
  const left = 230;
  const right = 70;
  const rowH = 30;
  const H = rows.length * rowH + 10;
  const mid = left + (W - left - right) / 2;
  const sx = (v: number) => (v / ext) * ((W - left - right) / 2);
  return (
    <div>
      <div className="mb-2 flex gap-4 text-xs text-ink-2">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[0] }} />
          Low value of assumption
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[1] }} />
          High value
        </span>
        {rows.some((r) => r.low === r.high) && (
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: SERIES[6] }} />
            Alternative model (one scenario)
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Sensitivity of expected profit to assumptions">
        <line x1={mid} x2={mid} y1={0} y2={H} stroke="var(--axis)" />
        {rows.map((r, i) => {
          const y = 6 + i * rowH;
          return (
            <g key={r.label}>
              <text x={0} y={y + 14} fontSize="12" fill="var(--ink)">
                {r.label}
              </text>
              {(r.low === r.high
                ? [{ v: r.low, c: SERIES[6], dy: 7 }]
                : [
                    { v: r.low, c: SERIES[0], dy: 2 },
                    { v: r.high, c: SERIES[1], dy: 12 },
                  ]
              ).map(({ v, c, dy }) => (
                <g key={dy}>
                  <title>{`${r.label}: ${fmt(v)}`}</title>
                  <rect
                    x={v >= 0 ? mid : mid + sx(v)}
                    y={y + dy}
                    width={Math.max(1, Math.abs(sx(v)))}
                    height={9}
                    rx={2}
                    fill={c}
                  />
                </g>
              ))}
              <text x={W - right + 6} y={y + 14} fontSize="11" fill="var(--ink-2)">
                {fmt(Math.max(Math.abs(r.low), Math.abs(r.high)))}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Lines over a numeric x-axis (e.g. a Qini curve: share of users targeted → uplift). */
export function XYLines({
  data,
  x,
  series,
  xFormat,
  yFormat,
  height = 260,
}: {
  data: Record<string, number>[];
  x: string;
  series: SeriesDef[];
  xFormat: FmtName;
  yFormat: FmtName;
  height?: number;
}) {
  const fx = FORMATS[xFormat];
  const fy = FORMATS[yFormat];
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
        {series.map((s, i) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block w-4"
              style={{ borderTop: `2px ${s.dashed ? "dashed" : "solid"} ${s.color ?? SERIES[i]}` }}
            />
            {s.name}
          </span>
        ))}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey={x} type="number" domain={[0, 1]} tickFormatter={fx} tick={axisTick} stroke="var(--axis)" tickLine={false} />
          <YAxis tickFormatter={fy} tick={axisTick} stroke="none" width={56} />
          <Tooltip
            formatter={(v, name) => [fy(Number(v)), series.find((s) => s.key === name)?.name ?? String(name)]}
            labelFormatter={(l) => `${fx(Number(l))} targeted`}
            contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          />
          {series.map((s, i) => (
            <Line
              key={s.key}
              dataKey={s.key}
              stroke={s.color ?? SERIES[i]}
              strokeWidth={2}
              strokeDasharray={s.dashed ? "4 3" : undefined}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
