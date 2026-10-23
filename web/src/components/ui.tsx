import type { ReactNode } from "react";

import type { Provenance } from "@/lib/types";

const EVIDENCE: Record<string, { color: string; help: string }> = {
  Observed: { color: "var(--series-1)", help: "Recorded in real data" },
  Attributed: { color: "var(--series-2)", help: "Credit assigned by a rule; not causal" },
  Modeled: { color: "var(--series-7)", help: "Estimated by a statistical model, with uncertainty" },
  Experimental: { color: "var(--series-6)", help: "Measured by a randomized experiment" },
  Simulated: { color: "var(--series-5)", help: "From the simulated company; truth is known" },
  Assumption: { color: "var(--series-4)", help: "An input chosen by the analyst" },
};

/** Evidence type is always text plus a swatch, never colour alone. */
export function EvidenceBadge({ type }: { type: string }) {
  const e = EVIDENCE[type] ?? { color: "var(--muted)", help: "" };
  return (
    <span
      title={e.help}
      className="inline-flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-2"
    >
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: e.color }} />
      {type}
    </span>
  );
}

export function ProvenanceLine({ p }: { p: Provenance }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
      <EvidenceBadge type={p.evidence_type} />
      {p.run_id && <span className="font-mono">run {p.run_id}</span>}
      {p.source_tables && <span className="font-mono">{p.source_tables.join(", ")}</span>}
      {p.note && <span>{p.note}</span>}
    </div>
  );
}

export function PageHeader({ title, lede, children }: { title: string; lede?: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {lede && <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{lede}</p>}
      </div>
      {children}
    </header>
  );
}

export function Card({
  title,
  subtitle,
  provenance,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: ReactNode;
  provenance?: Provenance;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card p-5 ${className}`}>
      {(title || provenance) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-2">{subtitle}</p>}
          </div>
          {provenance && <ProvenanceLine p={provenance} />}
        </div>
      )}
      {children}
    </section>
  );
}

export function StatTile({
  label,
  value,
  sub,
  evidence,
  definition,
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  evidence: string;
  definition?: string;
}) {
  return (
    <div className="card flex flex-col gap-1 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-ink-2" title={definition}>
          {label}
        </span>
        <EvidenceBadge type={evidence} />
      </div>
      <span className="text-2xl font-semibold tracking-tight">{value}</span>
      {sub && <span className="text-xs text-ink-2">{sub}</span>}
    </div>
  );
}

const STATUS: Record<string, { color: string; icon: string }> = {
  Confirmed: { color: "var(--status-good)", icon: "✓" },
  "Supported hypothesis": { color: "var(--status-warning)", icon: "◐" },
  Unverified: { color: "var(--muted)", icon: "?" },
};

export function StatusTag({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.Unverified;
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px] font-medium text-ink-2">
      <span aria-hidden style={{ color: s.color }}>
        {s.icon}
      </span>
      {status}
    </span>
  );
}

export function Callout({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  return (
    <div
      className="rounded-md border-l-2 bg-surface-2 px-3 py-2 text-xs leading-relaxed text-ink-2"
      style={{ borderColor: tone === "warn" ? "var(--status-serious)" : "var(--accent)" }}
    >
      {children}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="card p-6 text-sm text-ink-2">
      <p className="font-medium text-ink">Data unavailable</p>
      <p className="mt-1">{message}</p>
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="flex animate-pulse flex-col gap-4" aria-busy="true" aria-label="Loading">
      <div className="h-7 w-64 rounded bg-surface-2" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="card h-24" />
        ))}
      </div>
      <div className="card h-72" />
    </div>
  );
}
