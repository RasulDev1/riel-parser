"use client";

import { useState } from "react";
import { ResultsTable } from "@/components/ResultsTable";
import { DEFAULT_FORM, SearchForm, type FormState } from "@/components/SearchForm";
import { toCsv } from "@/lib/csv";
import type { ParseResult } from "@/lib/types";

export default function Home() {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ParseResult | null>(null);

  async function search() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setResult(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function downloadCsv() {
    if (!result) return;
    const blob = new Blob([toCsv(result.listings)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `avito-${form.city}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Парсер недвижимости Авито</h1>
        <p className="text-sm text-slate-500">
          Собирает объявления по городу, району, цене, площади и этажам. Выдача с Авито фильтруется локально.
        </p>
      </header>

      <SearchForm form={form} setForm={setForm} onSubmit={search} loading={loading} />

      {error && <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {result && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-600">
              Подходит <b>{result.listings.length}</b> из {result.scanned} объявлений · страниц обработано:{" "}
              {result.pagesFetched}
            </p>
            <button
              onClick={downloadCsv}
              disabled={!result.listings.length}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
            >
              Скачать CSV
            </button>
          </div>
          {result.warnings.map((w) => (
            <div key={w} className="rounded-lg bg-amber-50 px-4 py-2 text-sm text-amber-800">
              {w}
            </div>
          ))}
          {result.listings.length > 0 ? (
            <ResultsTable listings={result.listings} />
          ) : (
            <p className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
              Ничего не найдено. Попробуйте ослабить фильтры или увеличить число страниц.
            </p>
          )}
        </section>
      )}
    </main>
  );
}
