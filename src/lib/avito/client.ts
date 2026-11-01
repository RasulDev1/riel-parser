import { applyFilters, dedupe } from "@/lib/filter";
import type { ParseResult, SearchFilters } from "@/lib/types";
import { looksLikeBlockPage, parseSearchPage } from "./parse";

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Собирает URL выдачи Авито. Цена передаётся в запрос, остальное фильтруем локально. */
export function buildSearchUrl(f: SearchFilters, page = 1): string {
  const url = new URL(`https://www.avito.ru/${encodeURIComponent(f.city)}/${f.propertyType}/${f.deal}`);
  if (f.priceMin) url.searchParams.set("pmin", String(f.priceMin));
  if (f.priceMax) url.searchParams.set("pmax", String(f.priceMax));
  url.searchParams.set("s", "104"); // сортировка: сначала новые
  if (page > 1) url.searchParams.set("p", String(page));
  return url.toString();
}

async function fetchPage(url: string): Promise<{ html: string; status: number }> {
  const res = await fetch(url, {
    headers: {
      "User-Agent": USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)],
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
      Referer: "https://www.avito.ru/",
    },
    cache: "no-store",
  });
  return { html: await res.text(), status: res.status };
}

export async function searchAvito(f: SearchFilters): Promise<ParseResult> {
  const pages = Math.min(Math.max(f.pages ?? 1, 1), 10);
  const delayMs = Number(process.env.AVITO_DELAY_MS ?? 2500);
  const result: ParseResult = { listings: [], scanned: 0, pagesFetched: 0, sourceUrls: [], warnings: [] };
  const all = [];

  for (let page = 1; page <= pages; page++) {
    const url = buildSearchUrl(f, page);
    result.sourceUrls.push(url);

    let html = "";
    try {
      const res = await fetchPage(url);
      if (res.status === 429 || res.status === 403 || looksLikeBlockPage(res.html)) {
        result.warnings.push(
          `Страница ${page}: Авито ограничил доступ (HTTP ${res.status}). Увеличьте AVITO_DELAY_MS или уменьшите число страниц.`,
        );
        break;
      }
      if (res.status >= 400) {
        result.warnings.push(`Страница ${page}: HTTP ${res.status}`);
        break;
      }
      html = res.html;
    } catch (e) {
      result.warnings.push(`Страница ${page}: ошибка сети (${(e as Error).message})`);
      break;
    }

    const items = parseSearchPage(html);
    result.pagesFetched++;
    if (items.length === 0) {
      if (page === 1) result.warnings.push("На странице не найдено объявлений: возможно, Авито изменил вёрстку.");
      break;
    }
    all.push(...items);

    if (page < pages) await sleep(delayMs + Math.random() * 1000);
  }

  const unique = dedupe(all);
  result.scanned = unique.length;
  result.listings = applyFilters(unique, f);
  return result;
}
