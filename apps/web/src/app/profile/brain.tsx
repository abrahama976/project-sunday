"use client";

import { useState, useTransition } from "react";
import { retireDirective, type Directive } from "./actions";

const SCOPE_STYLES: Record<string, string> = {
  general: "bg-zinc-800 text-zinc-300 border-zinc-700",
  code: "bg-blue-950 text-blue-300 border-blue-900",
  calendar: "bg-purple-950 text-purple-300 border-purple-900",
  email: "bg-amber-950 text-amber-300 border-amber-900",
  tasks: "bg-emerald-950 text-emerald-300 border-emerald-900",
  news: "bg-sky-950 text-sky-300 border-sky-900",
  health: "bg-rose-950 text-rose-300 border-rose-900",
  travel: "bg-teal-950 text-teal-300 border-teal-900",
};

export default function BrainPanel({
  initialDirectives,
  maxDirectives,
}: {
  initialDirectives: Directive[];
  maxDirectives: number;
}) {
  const [directives, setDirectives] = useState(initialDirectives);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [isPending, startTransition] = useTransition();

  function handleRetire(id: string) {
    setError("");
    // Optimistic: the row is gone from the list immediately, restored on failure.
    const previous = directives;
    setDirectives((d) => d.filter((x) => x.id !== id));
    setConfirming(null);
    startTransition(async () => {
      const result = await retireDirective(id);
      if (!result.success) {
        setDirectives(previous);
        setError(result.error ?? "Could not retire that rule.");
      }
    });
  }

  const chars = directives.reduce((n, d) => n + d.directive.length, 0);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-zinc-100">Learned rules</h2>
        <span className="text-xs text-zinc-500 tabular-nums">
          {directives.length}/{maxDirectives} · {chars.toLocaleString()} chars
        </span>
      </div>

      <p className="text-sm text-zinc-400">
        Rules Sunday has been taught about how to work with you. These are added
        to every request, so they cost budget — retire anything that has stopped
        being true.
      </p>

      {error && (
        <p className="text-sm text-red-400 border border-red-900 bg-red-950/40 rounded-lg p-3">
          {error}
        </p>
      )}

      {directives.length === 0 ? (
        <div className="border border-dashed border-zinc-700 rounded-lg p-6 text-center">
          <p className="text-sm text-zinc-400">Nothing learned yet.</p>
          <p className="text-xs text-zinc-500 mt-2">
            Tell Sunday how you want something done — &ldquo;keep answers
            shorter&rdquo;, &ldquo;always show code first&rdquo; — and approve
            the rule when it asks.
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {directives.map((d) => (
            <li
              key={d.id}
              className="border border-zinc-800 bg-zinc-900 rounded-lg p-3 flex flex-col gap-2"
            >
              <p className="text-sm text-zinc-100 leading-snug">{d.directive}</p>

              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`text-[0.65rem] uppercase tracking-wide px-1.5 py-0.5 rounded border ${
                    SCOPE_STYLES[d.scope] ?? SCOPE_STYLES.general
                  }`}
                >
                  {d.scope}
                </span>
                <span className="text-[0.65rem] uppercase tracking-wide text-zinc-500">
                  {d.source === "inferred" ? "inferred" : "you asked"}
                </span>
                <span className="text-[0.65rem] text-zinc-600 tabular-nums">
                  weight {d.weight}
                </span>

                <div className="ml-auto">
                  {confirming === d.id ? (
                    <span className="flex items-center gap-2">
                      <button
                        onClick={() => handleRetire(d.id)}
                        disabled={isPending}
                        className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50 focus:outline-none focus-visible:ring-1 focus-visible:ring-red-400 rounded px-1"
                      >
                        Retire
                      </button>
                      <button
                        onClick={() => setConfirming(null)}
                        className="text-xs text-zinc-500 hover:text-zinc-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-zinc-400 rounded px-1"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => setConfirming(d.id)}
                      className="text-xs text-zinc-500 hover:text-zinc-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-zinc-400 rounded px-1"
                    >
                      Retire
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
