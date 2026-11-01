export type Deal = "prodam" | "sdam";

export type PropertyType = "kvartiry" | "komnaty" | "doma_dachi_kottedzhi" | "kommercheskaya_nedvizhimost";

export interface SearchFilters {
  /** Слаг города в URL Авито, например "moskva", "sankt-peterburg" */
  city: string;
  propertyType: PropertyType;
  deal: Deal;
  /** Подстрока района / улицы / метро в адресе объявления (без учёта регистра) */
  district?: string;
  priceMin?: number;
  priceMax?: number;
  areaMin?: number;
  areaMax?: number;
  floorMin?: number;
  floorMax?: number;
  /** Этажность дома */
  totalFloorsMin?: number;
  totalFloorsMax?: number;
  notFirstFloor?: boolean;
  notLastFloor?: boolean;
  /** Сколько страниц выдачи обойти (1–10) */
  pages?: number;
}

export interface Listing {
  id: string;
  title: string;
  url: string;
  price: number | null;
  pricePerM2: number | null;
  area: number | null;
  rooms: string | null;
  floor: number | null;
  totalFloors: number | null;
  address: string | null;
  district: string | null;
  publishedAt: string | null;
}

export interface ParseResult {
  listings: Listing[];
  /** Сколько объявлений пришло с Авито до локальной фильтрации */
  scanned: number;
  pagesFetched: number;
  sourceUrls: string[];
  warnings: string[];
}
