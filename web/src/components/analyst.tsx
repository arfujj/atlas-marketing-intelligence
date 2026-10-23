"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useTransition } from "react";

import { EvidenceBadge } from "@/components/ui";

interface Fact {
  label: string;
  value: string;
  evidence: string;
  source: string;
}
interface Answer {
  intent: string;
  question: string;
  paragraphs: string[];
  facts: Fact[];
  follow_ups: string[];
  link: { href: string; label: string } | null;
}

/** Ask ATLAS: a deterministic analyst over the stored runs. Every number in an answer is listed
 *  with its evidence type and the run or table it came from. */
export function AnalystDrawer() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<Answer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    if (suggestions.length === 0)
      fetch("/api/analyst")
        .then((r) => (r.ok ? r.json() : []))
        .then(setSuggestions)
        .catch(() => setSuggestions([]));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, suggestions.length]);

  useEffect(() => {
    // Block body on purpose: newer browsers return a Promise from scrollIntoView, and React
    // would call an arrow function's return value as the effect's cleanup.
    end.current?.scrollIntoView({ block: "end" });
  }, [history]);

  function ask(question: string) {
    if (!question.trim()) return;
    setQ("");
    start(async () => {
      setError(null);
      const r = await fetch("/api/analyst", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!r.ok) {
        setError("The analyst is unavailable. Is the API running?");
        return;
      }
      const a: Answer = await r.json();
      setHistory((h) => [...h, a]);
    });
  }

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="analyst-panel"
        className="fixed bottom-5 right-5 z-30 rounded-full bg-accent-fill px-4 py-2.5 text-sm font-medium text-white shadow-lg"
      >
        {open ? "Close analyst" : "Ask ATLAS"}
      </button>
      {open && (
        <aside
          id="analyst-panel"
          role="dialog"
          aria-label="Ask ATLAS"
          className="fixed inset-x-0 bottom-0 z-20 flex max-h-[85vh] flex-col border-t border-line bg-surface shadow-2xl sm:inset-x-auto sm:right-5 sm:bottom-20 sm:w-[440px] sm:rounded-xl sm:border"
        >
          <header className="border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold">Ask ATLAS</h2>
            <p className="text-xs text-ink-2">
              Answers come only from ATLAS&apos;s stored analyses; every number lists its source. No AI writes the numbers.
            </p>
          </header>
          <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4 text-sm" aria-live="polite">
            {history.length === 0 && (
              <div className="flex flex-wrap gap-2">
                {suggestions.map((s) => (
                  <button key={s} onClick={() => ask(s)} className="rounded-full border border-line px-3 py-1 text-left text-xs text-ink-2 hover:bg-surface-2">
                    {s}
                  </button>
                ))}
              </div>
            )}
            {history.map((a, i) => (
              <article key={i} className="space-y-2">
                <p className="font-medium">{a.question}</p>
                {a.paragraphs.map((p, j) => (
                  <p key={j} className="leading-relaxed text-ink-2">
                    {p}
                  </p>
                ))}
                {a.facts.length > 0 && (
                  <ul className="space-y-1 rounded-md bg-surface-2 p-2.5 text-xs">
                    {a.facts.map((f, j) => (
                      <li key={j} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                        <span className="text-ink-2">{f.label}</span>
                        <span className="flex items-center gap-2">
                          <span className="font-medium tnum">{f.value}</span>
                          <EvidenceBadge type={f.evidence} />
                        </span>
                        <span className="w-full font-mono text-[10px] text-muted">{f.source}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex flex-wrap gap-2">
                  {a.link && (
                    <Link href={a.link.href} onClick={() => setOpen(false)} className="text-xs font-medium text-accent underline underline-offset-2">
                      Open {a.link.label} →
                    </Link>
                  )}
                  {a.follow_ups.map((f) => (
                    <button key={f} onClick={() => ask(f)} className="rounded-full border border-line px-2.5 py-0.5 text-xs text-ink-2 hover:bg-surface-2">
                      {f}
                    </button>
                  ))}
                </div>
              </article>
            ))}
            {pending && <p className="text-xs text-muted">Looking it up…</p>}
            {error && (
              <p role="alert" className="text-xs text-bad">
                {error}
              </p>
            )}
            <div ref={end} />
          </div>
          <form
            className="flex gap-2 border-t border-line p-3"
            onSubmit={(e) => {
              e.preventDefault();
              ask(q);
            }}
          >
            <label htmlFor="analyst-q" className="sr-only">
              Your question
            </label>
            <input
              id="analyst-q"
              ref={input}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              maxLength={500}
              placeholder="e.g. How should we spend $400K?"
              className="min-w-0 flex-1 rounded-md border border-line bg-surface px-3 py-2 text-sm"
            />
            <button disabled={pending || !q.trim()} className="rounded-md bg-accent-fill px-3 py-2 text-sm font-medium text-white disabled:opacity-40">
              Ask
            </button>
          </form>
        </aside>
      )}
    </>
  );
}
