"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const WORKSPACES = [
  { href: "/halden", name: "Halden Coffee Works", evidence: "Simulated" },
  { href: "/ga4", name: "Google Merchandise Store", evidence: "Observed" },
  { href: "/criteo", name: "Criteo Incrementality Tests", evidence: "Observed RCT" },
];

export function WorkspaceSwitcher() {
  const path = usePathname();
  return (
    <nav aria-label="Workspace" className="flex flex-wrap gap-1">
      {WORKSPACES.map((w) => {
        const active = path.startsWith(w.href);
        return (
          <Link
            key={w.href}
            href={w.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
              active ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2"
            }`}
          >
            {w.name}
            <span className="ml-1.5 text-[11px] text-muted">· {w.evidence}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function SubNav({ items }: { items: { href: string; label: string }[] }) {
  const path = usePathname();
  return (
    <nav aria-label="Section" className="flex gap-5 overflow-x-auto border-b border-line text-sm">
      {items.map((it, i) => {
        const active = path === it.href;
        return (
          <Link
            key={it.href}
            href={it.href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px whitespace-nowrap border-b-2 py-2.5 ${
              active ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            <span className="mr-1 text-muted">{i + 1}</span>
            {it.label}
          </Link>
        );
      })}
    </nav>
  );
}
