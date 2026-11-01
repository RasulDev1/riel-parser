import { NextResponse } from "next/server";
import { searchAvito } from "@/lib/avito/client";
import type { SearchFilters } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const num = (v: unknown) => {
  if (v === "" || v === null || v === undefined) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
};

export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Некорректный JSON" }, { status: 400 });
  }

  const city = String(body.city ?? "").trim();
  if (!/^[a-z0-9_-]+$/.test(city)) {
    return NextResponse.json({ error: "Укажите город (слаг Авито, например moskva)" }, { status: 400 });
  }

  const filters: SearchFilters = {
    city,
    propertyType: (body.propertyType as SearchFilters["propertyType"]) ?? "kvartiry",
    deal: body.deal === "sdam" ? "sdam" : "prodam",
    district: typeof body.district === "string" ? body.district : undefined,
    priceMin: num(body.priceMin),
    priceMax: num(body.priceMax),
    areaMin: num(body.areaMin),
    areaMax: num(body.areaMax),
    floorMin: num(body.floorMin),
    floorMax: num(body.floorMax),
    totalFloorsMin: num(body.totalFloorsMin),
    totalFloorsMax: num(body.totalFloorsMax),
    notFirstFloor: Boolean(body.notFirstFloor),
    notLastFloor: Boolean(body.notLastFloor),
    pages: num(body.pages) ?? 1,
  };

  const allowedTypes = ["kvartiry", "komnaty", "doma_dachi_kottedzhi", "kommercheskaya_nedvizhimost"];
  if (!allowedTypes.includes(filters.propertyType)) {
    return NextResponse.json({ error: "Неизвестная категория" }, { status: 400 });
  }

  const result = await searchAvito(filters);
  return NextResponse.json(result);
}
