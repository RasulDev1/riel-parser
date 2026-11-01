import type { Listing, SearchFilters } from "@/lib/types";

const inRange = (v: number | null, min?: number, max?: number) => {
  if (min === undefined && max === undefined) return true;
  if (v === null) return false;
  if (min !== undefined && v < min) return false;
  if (max !== undefined && v > max) return false;
  return true;
};

/**
 * Локальная фильтрация. Авито принимает в URL только цену, а площадь, этажи и
 * район кодируются внутренними id, поэтому их проверяем уже после парсинга.
 */
export function applyFilters(listings: Listing[], f: SearchFilters): Listing[] {
  const district = f.district?.trim().toLowerCase();

  return listings.filter((l) => {
    if (!inRange(l.price, f.priceMin, f.priceMax)) return false;
    if (!inRange(l.area, f.areaMin, f.areaMax)) return false;
    if (!inRange(l.floor, f.floorMin, f.floorMax)) return false;
    if (!inRange(l.totalFloors, f.totalFloorsMin, f.totalFloorsMax)) return false;
    if (f.notFirstFloor && l.floor === 1) return false;
    if (f.notLastFloor && l.floor !== null && l.floor === l.totalFloors) return false;
    if (district) {
      const haystack = `${l.address ?? ""} ${l.district ?? ""} ${l.title}`.toLowerCase();
      if (!haystack.includes(district)) return false;
    }
    return true;
  });
}

/** Убирает дубли (Авито иногда повторяет VIP-объявления на разных страницах). */
export function dedupe(listings: Listing[]): Listing[] {
  const seen = new Set<string>();
  return listings.filter((l) => (seen.has(l.id) ? false : (seen.add(l.id), true)));
}
