"use client";

import { useMemo, useState } from "react";
import type { Listing } from "@/lib/types";

type SortKey = "price" | "area" | "pricePerM2" | "floor";

const fmt = (n: number | null, suffix = "") => (n === null ? "—" : `${n.toLocaleString("ru-RU")}${suffix}`);

export function ResultsTable({ listings }: { listings: Listing[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);

  const rows = useMemo(() => {
    if (!sort) return listings;
    return [...listings].sort((a, b) => {
      const av = a[sort.key] ?? Infinity;
      const bv = b[sort.key] ?? Infinity;
      return (av - bv) * sort.dir;
    });
  }, [listings, sort]);

  const header = (key: SortKey, title: string) => (
    <th
      className="cursor-pointer select-none px-3 py-2 text-right font-medium hover:text-slate-900"
      onClick={() => setSort((s) => (s?.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }))}
    >
      {title}
      {sort?.key === key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full min-w-[820px] text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Объявление</th>
            {header("price", "Цена")}
            {header("pricePerM2", "₽/м²")}
            {header("area", "Площадь")}
            {header("floor", "Этаж")}
            <th className="px-3 py-2 text-left font-medium">Адрес</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((l) => (
            <tr key={l.id} className="hover:bg-emerald-50/40">
              <td className="px-3 py-2">
                <a href={l.url} target="_blank" rel="noreferrer" className="font-medium text-emerald-700 hover:underline">
                  {l.title}
                </a>
                {l.publishedAt && <div className="text-xs text-slate-400">{l.publishedAt}</div>}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right font-semibold">{fmt(l.price, " ₽")}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right text-slate-600">{fmt(l.pricePerM2)}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right">{fmt(l.area, " м²")}</td>
              <td className="whitespace-nowrap px-3 py-2 text-right">
                {l.floor ?? "—"}
                {l.totalFloors ? `/${l.totalFloors}` : ""}
              </td>
              <td className="px-3 py-2 text-slate-600">
                {l.address ?? "—"}
                {l.district && <div className="text-xs text-slate-400">{l.district}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
