import type { Listing } from "@/lib/types";

const COLUMNS: [keyof Listing, string][] = [
  ["title", "Заголовок"],
  ["price", "Цена"],
  ["pricePerM2", "Цена за м²"],
  ["area", "Площадь"],
  ["rooms", "Комнаты"],
  ["floor", "Этаж"],
  ["totalFloors", "Этажность"],
  ["address", "Адрес"],
  ["district", "Район/метро"],
  ["publishedAt", "Опубликовано"],
  ["url", "Ссылка"],
];

export function toCsv(listings: Listing[]): string {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const head = COLUMNS.map(([, h]) => esc(h)).join(";");
  const rows = listings.map((l) => COLUMNS.map(([k]) => esc(l[k])).join(";"));
  // BOM, чтобы Excel корректно открыл кириллицу
  return "﻿" + [head, ...rows].join("\r\n");
}
