const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function money(v: number | null | undefined, opts: { compact?: boolean; digits?: number } = {}): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (opts.compact) {
    const a = Math.abs(v);
    return `${v < 0 ? "−" : ""}$${a < 1000 ? Math.round(a).toLocaleString("en-US") : compact.format(a)}`;
  }
  const s = Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: opts.digits ?? 0 });
  return `${v < 0 ? "−" : ""}$${s}`;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(v: number | null | undefined, digits = 1, signed = false): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = `${(Math.abs(v) * 100).toFixed(digits)}%`;
  if (!signed) return v < 0 ? `−${s}` : s;
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
}

/** ROI-style ratios are shown to one decimal: two decimals would claim precision the
 *  intervals do not support. */
export function ratio(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}`;
}

export function formatMetric(v: number | null | undefined, format: string): string {
  if (format === "currency") return money(v, { compact: Math.abs(v ?? 0) >= 100_000 });
  if (format === "percent") return pct(v);
  if (format === "ratio") return ratio(v, 2);
  return num(v, Math.abs(v ?? 0) < 10 ? 2 : 0);
}

export const CHANNEL_LABELS: Record<string, string> = {
  search_nonbrand: "Search · Non-brand",
  search_brand: "Search · Brand",
  meta_prospecting: "Meta · Prospecting",
  meta_retargeting: "Meta · Retargeting",
  tiktok: "TikTok",
  youtube: "YouTube",
  direct: "Direct",
  organic_search: "Organic search",
};

export const METHOD_LABELS: Record<string, string> = {
  last_click: "Last-click",
  markov: "Markov attribution",
  ols_naive: "Naive regression",
  bayes_default: "MMM, default priors",
  bayes_dag: "MMM, DAG-informed",
  bayes_dag_calibrated: "MMM, calibrated with geo-lift",
  current: "Current plan",
};

export const channelLabel = (c: string) => CHANNEL_LABELS[c] ?? c;
export const methodLabel = (m: string) => METHOD_LABELS[m] ?? m;
